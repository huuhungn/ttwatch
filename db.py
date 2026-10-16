import sqlite3
import threading
import time
from datetime import datetime

from paths import DB_PATH
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    username TEXT PRIMARY KEY,          -- lowercase
    unique_id TEXT,
    nickname TEXT,
    avatar TEXT,
    verified INTEGER DEFAULT 0,
    private INTEGER DEFAULT 0,
    sec_uid TEXT,
    followers INTEGER,
    following INTEGER,
    likes INTEGER,
    video_count INTEGER,
    bio TEXT,
    bio_link TEXT,
    created_at INTEGER,
    group_name TEXT DEFAULT '',
    note TEXT DEFAULT '',
    status TEXT DEFAULT 'queued',
    message TEXT DEFAULT '',
    added_at INTEGER,
    updated_at INTEGER,
    full_scan_at INTEGER,
    last_scan_at INTEGER,
    last_scan_label TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    ts INTEGER,
    followers INTEGER,
    likes INTEGER,
    video_count INTEGER,
    total_views INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snap_user ON snapshots(username, ts);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    username TEXT,
    description TEXT,
    create_time INTEGER,
    duration INTEGER,
    cover TEXT,
    play INTEGER,
    digg INTEGER,
    comment INTEGER,
    share INTEGER,
    collect INTEGER,
    music TEXT,
    is_ad INTEGER DEFAULT 0,
    prev_play INTEGER,
    prev_ts INTEGER,
    updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(username);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


class _Conn(sqlite3.Connection):
    """`with _conn() as c` commits or rolls back, then closes the connection.

    By default sqlite3 only commits and the connection lingers until it is garbage-collected:
    on Windows the DB file stays locked, so it cannot be deleted, moved or backed up right after use.
    """

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, factory=_Conn)
    c.row_factory = sqlite3.Row
    return c


def init():
    existed = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    if existed:
        _backup_before_start()
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)
        c.execute("PRAGMA journal_mode=WAL")
        # The previous run was killed midway: channels still queued/running have no real job behind them.
        c.execute("UPDATE channels SET status='error', message='Bị dừng giữa chừng – hãy cập nhật lại' WHERE status IN ('queued','running')")


# show_browser: "1" = show the browser window so a captcha can be solved.
# auto_refresh_minutes: "0" = off; N > 0 = quick-refresh every channel every N minutes.

DEFAULT_SETTINGS = {
    "show_browser": "0",
    "auto_refresh_minutes": "0",
    # Auto-refresh mode ("quick" | "scan10"), quiet hours (whole hours 0-23,
    # empty = off) and alert thresholds.
    "auto_refresh_mode": "quick",
    "quiet_start": "",
    "quiet_end": "",
    "alerts_enabled": "1",
    "alert_follow_pct": "5",
    "alert_new_video": "1",
    # Scan pacing (pacing.py): "off" | "normal" | "slow".
    "scan_pace": "normal",
    # Start with Windows (autostart.py); the registry entry is written through /api/autostart.
    "autostart": "0",
    # Self-update (updater.py): check GitHub, install when idle, the version the user skipped,
    # and the version whose automatic install failed (not retried on its own).
    "update_check": "1",
    "update_auto": "1",
    "update_skip": "",
    "update_failed": "",
}


def get_setting(key, default=None):
    with _lock, _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, default)


def get_settings():
    with _lock, _conn() as c:
        # "view:*" keys are saved views (insights.py), not settings.
        rows = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings WHERE key NOT LIKE 'view:%'")}
    return {**DEFAULT_SETTINGS, **rows}


def set_settings(values):
    with _lock, _conn() as c:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, str(v)))




def add_channels(usernames):
    """Return (added, already existed)."""
    added, existed = [], []
    now = int(time.time())
    with _lock, _conn() as c:
        for u in usernames:
            key = u.lower()
            if c.execute("SELECT 1 FROM channels WHERE username=?", (key,)).fetchone():
                existed.append(u)
            else:
                c.execute("INSERT INTO channels(username, unique_id, added_at, status) VALUES(?,?,?, 'queued')",
                          (key, u, now))
                added.append(u)
    return added, existed


def channel_exists(key):
    with _lock, _conn() as c:
        return c.execute("SELECT 1 FROM channels WHERE username=?", (key,)).fetchone() is not None


def all_usernames():
    with _lock, _conn() as c:
        return [r["username"] for r in c.execute("SELECT username FROM channels")]


def delete_channels(usernames):
    keys = [u.lower() for u in usernames]
    with _lock, _conn() as c:
        for k in keys:
            c.execute("DELETE FROM channels WHERE username=?", (k,))
            c.execute("DELETE FROM videos WHERE username=?", (k,))
            c.execute("DELETE FROM snapshots WHERE username=?", (k,))


def update_meta(usernames, group_name=None, note=None):
    with _lock, _conn() as c:
        for u in usernames:
            if group_name is not None:
                c.execute("UPDATE channels SET group_name=? WHERE username=?", (group_name, u.lower()))
            if note is not None:
                c.execute("UPDATE channels SET note=? WHERE username=?", (note, u.lower()))


def set_status(key, status, message=""):
    with _lock, _conn() as c:
        c.execute("UPDATE channels SET status=?, message=? WHERE username=?", (status, message, key))


def save_channel_info(key, info):
    cols = ", ".join(f"{k}=?" for k in info)
    with _lock, _conn() as c:
        c.execute(f"UPDATE channels SET {cols}, updated_at=? WHERE username=?",
                  (*info.values(), int(time.time()), key))


def finish_scan(key, videos, full):
    now = int(time.time())
    with _lock, _conn() as c:
        for v in videos:
            old = c.execute("SELECT play, updated_at FROM videos WHERE id=?", (v["id"],)).fetchone()
            if old:
                c.execute("""UPDATE videos SET description=?, duration=?, cover=?, play=?, digg=?, comment=?,
                             share=?, collect=?, music=?, is_ad=?, prev_play=?, prev_ts=?, updated_at=? WHERE id=?""",
                          (v["description"], v["duration"], v["cover"], v["play"], v["digg"], v["comment"],
                           v["share"], v["collect"], v["music"], v["is_ad"], old["play"], old["updated_at"], now, v["id"]))
            else:
                c.execute("""INSERT INTO videos(id, username, description, create_time, duration, cover, play, digg,
                             comment, share, collect, music, is_ad, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (v["id"], key, v["description"], v["create_time"], v["duration"], v["cover"], v["play"],
                           v["digg"], v["comment"], v["share"], v["collect"], v["music"], v["is_ad"], now))
        if full:
            # Full scan: videos no longer in the list TikTok returns are deleted from the DB.
            ids = [v["id"] for v in videos]
            if ids:
                c.execute(f"DELETE FROM videos WHERE username=? AND id NOT IN ({','.join('?' * len(ids))})", (key, *ids))
            c.execute("UPDATE channels SET full_scan_at=? WHERE username=?", (now, key))
        ch = c.execute("SELECT followers, likes, video_count FROM channels WHERE username=?", (key,)).fetchone()
        total = c.execute("SELECT COALESCE(SUM(play),0) t FROM videos WHERE username=?", (key,)).fetchone()["t"]
        if ch:
            c.execute("INSERT INTO snapshots(username, ts, followers, likes, video_count, total_views) VALUES(?,?,?,?,?,?)",
                      (key, now, ch["followers"], ch["likes"], ch["video_count"], total))


def list_channels():
    now = int(time.time())
    d7, d30 = now - 604800, now - 2592000
    with _lock, _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM channels ORDER BY added_at, rowid")]
        agg = {r["username"]: dict(r) for r in c.execute(f"""
            SELECT username, COUNT(*) scanned, SUM(play) total_views, SUM(digg) v_likes, SUM(comment) v_comments,
                   SUM(share) v_shares, SUM(collect) v_saves, MAX(play) top_views, MAX(create_time) last_post,
                   SUM(CASE WHEN create_time >= {d7} THEN 1 ELSE 0 END) posts_7d,
                   SUM(CASE WHEN create_time >= {d30} THEN 1 ELSE 0 END) posts_30d,
                   SUM(CASE WHEN create_time >= {d30} THEN play ELSE 0 END) views_30d
            FROM videos GROUP BY username""")}
        snaps = {}
        for r in c.execute("""SELECT username, ts, followers, likes, total_views FROM snapshots s
                              WHERE id IN (SELECT id FROM snapshots s2 WHERE s2.username = s.username
                                           ORDER BY ts DESC, id DESC LIMIT 2)
                              ORDER BY username, ts DESC, id DESC"""):
            snaps.setdefault(r["username"], []).append(dict(r))
    for ch in rows:
        a = agg.get(ch["username"], {})
        ch["scanned"] = a.get("scanned") or 0
        ch["total_views"] = a.get("total_views") if a else None
        ch["top_views"] = a.get("top_views")
        ch["last_post"] = a.get("last_post")
        ch["posts_7d"] = a.get("posts_7d")
        ch["posts_30d"] = a.get("posts_30d")
        ch["views_30d"] = a.get("views_30d")
        ch["avg_views"] = round(a["total_views"] / a["scanned"]) if a.get("scanned") else None
        inter = sum(a.get(k) or 0 for k in ("v_likes", "v_comments", "v_shares", "v_saves"))
        ch["er"] = round(inter / a["total_views"] * 100, 2) if a.get("total_views") else None
        s = snaps.get(ch["username"], [])
        if len(s) >= 2:
            cur, prev = s[0], s[1]
            ch["d_followers"] = (cur["followers"] or 0) - (prev["followers"] or 0)
            ch["d_likes"] = (cur["likes"] or 0) - (prev["likes"] or 0)
            ch["d_views"] = (cur["total_views"] or 0) - (prev["total_views"] or 0)
            ch["prev_ts"] = prev["ts"]
        else:
            ch["d_followers"] = ch["d_likes"] = ch["d_views"] = ch["prev_ts"] = None
    return rows


def get_channel(key):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM channels WHERE username=?", (key.lower(),)).fetchone()
    return dict(r) if r else None


def list_videos(key):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM videos WHERE username=? ORDER BY create_time DESC", (key.lower(),))]


# Columns added later: older DBs get them when the app starts; existing data is untouched.
ADDED_COLUMNS = {
    "channels": {
        "last_scan_at": "INTEGER",
        "last_scan_label": "TEXT DEFAULT ''",
    },
}


def _add_missing_columns(c):
    for table, columns in ADDED_COLUMNS.items():
        have = {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _m_alerts(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            kind TEXT,
            text TEXT,
            ts INTEGER,
            read INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
    """)


def _m_video_index(c):
    c.execute("CREATE INDEX IF NOT EXISTS idx_videos_user_time ON videos(username, create_time)")


# Each migration runs exactly once, in order, and must be idempotent (a DB created from the
# current SCHEMA already has part of it). The version is stored in PRAGMA user_version; a DB without one is 0.
MIGRATIONS = [
    (1, _add_missing_columns),
    (2, _m_alerts),
    (3, _m_video_index),
]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def schema_version(c):
    return c.execute("PRAGMA user_version").fetchone()[0]


def _migrate(c):
    current = schema_version(c)
    for version, fn in MIGRATIONS:
        if version > current:
            fn(c)
    if current < SCHEMA_VERSION:
        c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


BACKUP_KEEP = 7
BACKUP_EVERY = 24 * 3600


def backup_dir():
    return DB_PATH.parent / "backups"


def list_backups():
    d = backup_dir()
    return sorted(d.glob("data-*.db"), reverse=True) if d.is_dir() else []


def backup_now(tag=""):
    """Consistent copy (SQLite backup API, safe while writing). Returns the path or None."""
    try:
        d = backup_dir()
        d.mkdir(parents=True, exist_ok=True)
        base = f"data-{datetime.now():%Y%m%d-%H%M%S}{'-' + tag if tag else ''}"
        dest = d / f"{base}.db"
        n = 1
        while dest.exists():
            n += 1
            dest = d / f"{base}-{n}.db"
        with _lock:
            src = sqlite3.connect(DB_PATH, timeout=30)
            try:
                out = sqlite3.connect(dest)
                try:
                    src.backup(out)
                finally:
                    out.close()
            finally:
                src.close()
        for old in list_backups()[BACKUP_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass
        return dest
    except (OSError, sqlite3.Error):
        # A failed backup (full disk, read-only folder) must not block app startup.
        return None


def _backup_before_start():
    try:
        probe = sqlite3.connect(DB_PATH, timeout=30)
        try:
            version = probe.execute("PRAGMA user_version").fetchone()[0]
        finally:
            probe.close()
    except sqlite3.Error:
        return
    if version < SCHEMA_VERSION:
        backup_now(f"v{version}")
        return
    last = list_backups()
    if not last or time.time() - last[0].stat().st_mtime > BACKUP_EVERY:
        backup_now()


def record_scan(key, label):
    """Record the latest successful scan and its type, shown on the videos page."""
    with _lock, _conn() as c:
        c.execute(
            "UPDATE channels SET last_scan_at=?, last_scan_label=? WHERE username=?",
            (int(time.time()), label, key),
        )
