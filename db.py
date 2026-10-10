import sqlite3
import threading
import time

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
    full_scan_at INTEGER
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

DEFAULT_SETTINGS = {
    "show_browser": "0",
    "auto_refresh_minutes": "0",
}


def _conn() -> sqlite3.Connection:
    DATA = DB_PATH.parent
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock:
        c = _conn()
        try:
            c.executescript(SCHEMA)
            c.execute("PRAGMA journal_mode=WAL")
            for key, value in DEFAULT_SETTINGS.items():
                c.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (key, value),
                )
            c.execute(
                "UPDATE channels SET status='error', "
                "message='Bị dừng giữa chừng – hãy cập nhật lại' "
                "WHERE status IN ('queued','running')"
            )
            c.commit()
        finally:
            c.close()


def get_setting(key: str, default: str | None = None):
    with _lock:
        c = _conn()
        try:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default
        finally:
            c.close()


def get_settings() -> dict:
    with _lock:
        c = _conn()
        try:
            rows = c.execute("SELECT key, value FROM settings").fetchall()
            out = dict(DEFAULT_SETTINGS)
            out.update({row["key"]: row["value"] for row in rows})
            return out
        finally:
            c.close()


def set_settings(values: dict) -> None:
    with _lock:
        c = _conn()
        try:
            for key, value in values.items():
                c.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
                    (key, str(value)),
                )
            c.commit()
        finally:
            c.close()


def add_channels(usernames: list[str]) -> tuple[list[str], list[str]]:
    """Trả về (đã thêm, đã có sẵn)."""
    added: list[str] = []
    existed: list[str] = []
    now = int(time.time())
    with _lock:
        c = _conn()
        try:
            for username in usernames:
                row = c.execute(
                    "SELECT 1 FROM channels WHERE username=?", (username,)
                ).fetchone()
                if row:
                    existed.append(username)
                    continue
                c.execute(
                    "INSERT INTO channels(username, unique_id, added_at, status) "
                    "VALUES(?,?,?, 'queued')",
                    (username, username, now),
                )
                added.append(username)
            c.commit()
        finally:
            c.close()
    return added, existed


def channel_exists(username: str) -> bool:
    with _lock:
        c = _conn()
        try:
            return (
                c.execute(
                    "SELECT 1 FROM channels WHERE username=?", (username,)
                ).fetchone()
                is not None
            )
        finally:
            c.close()


def all_usernames() -> list[str]:
    with _lock:
        c = _conn()
        try:
            return [
                row["username"]
                for row in c.execute("SELECT username FROM channels").fetchall()
            ]
        finally:
            c.close()


def delete_channels(usernames: list[str]) -> int:
    n = 0
    with _lock:
        c = _conn()
        try:
            for username in usernames:
                c.execute("DELETE FROM channels WHERE username=?", (username,))
                c.execute("DELETE FROM videos WHERE username=?", (username,))
                c.execute("DELETE FROM snapshots WHERE username=?", (username,))
                n += 1
            c.commit()
        finally:
            c.close()
    return n


def update_meta(usernames: list[str], group_name=None, note=None) -> None:
    with _lock:
        c = _conn()
        try:
            for username in usernames:
                if group_name is not None:
                    c.execute(
                        "UPDATE channels SET group_name=? WHERE username=?",
                        (group_name, username),
                    )
                if note is not None:
                    c.execute(
                        "UPDATE channels SET note=? WHERE username=?",
                        (note, username),
                    )
            c.commit()
        finally:
            c.close()


def set_status(username: str, status: str, message: str = "") -> None:
    with _lock:
        c = _conn()
        try:
            c.execute(
                "UPDATE channels SET status=?, message=? WHERE username=?",
                (status, message, username),
            )
            c.commit()
        finally:
            c.close()


def save_channel_info(username: str, info: dict) -> None:
    cols = ", ".join(f"{key}=?" for key in info)
    sql = f"UPDATE channels SET {cols}, updated_at=? WHERE username=?"
    with _lock:
        c = _conn()
        try:
            c.execute(sql, [*info.values(), int(time.time()), username])
            c.commit()
        finally:
            c.close()


def finish_scan(username: str, videos: list[dict], full: bool) -> dict:
    now = int(time.time())
    new_count = updated = 0
    total_views = 0
    with _lock:
        c = _conn()
        try:
            for video in videos:
                total_views += int(video.get("play") or 0)
                prev = c.execute(
                    "SELECT play, updated_at FROM videos WHERE id=?",
                    (video["id"],),
                ).fetchone()
                if prev is None:
                    c.execute(
                        "INSERT INTO videos(id, username, description, create_time, duration, "
                        "cover, play, digg, comment, share, collect, music, is_ad, "
                        "prev_play, prev_ts, updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            video["id"],
                            username,
                            video.get("description"),
                            video.get("create_time"),
                            video.get("duration"),
                            video.get("cover"),
                            video.get("play"),
                            video.get("digg"),
                            video.get("comment"),
                            video.get("share"),
                            video.get("collect"),
                            video.get("music"),
                            video.get("is_ad") or 0,
                            None,
                            None,
                            now,
                        ),
                    )
                    new_count += 1
                else:
                    c.execute(
                        "UPDATE videos SET description=?, duration=?, cover=?, play=?, digg=?, comment=?,\n"
                        "                             share=?, collect=?, music=?, is_ad=?, prev_play=?, prev_ts=?, updated_at=? WHERE id=?",
                        (
                            video.get("description"),
                            video.get("duration"),
                            video.get("cover"),
                            video.get("play"),
                            video.get("digg"),
                            video.get("comment"),
                            video.get("share"),
                            video.get("collect"),
                            video.get("music"),
                            video.get("is_ad") or 0,
                            prev["play"],
                            prev["updated_at"],
                            now,
                            video["id"],
                        ),
                    )
                    updated += 1
            ch = c.execute(
                "SELECT followers, likes, video_count FROM channels WHERE username=?",
                (username,),
            ).fetchone()
            if ch:
                c.execute(
                    "INSERT INTO snapshots(username, ts, followers, likes, video_count, total_views) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        username,
                        now,
                        ch["followers"],
                        ch["likes"],
                        ch["video_count"],
                        total_views,
                    ),
                )
            if full:
                c.execute(
                    "UPDATE channels SET full_scan_at=?, status='done', message='' WHERE username=?",
                    (now, username),
                )
            else:
                c.execute(
                    "UPDATE channels SET status='done', message='' WHERE username=?",
                    (username,),
                )
            c.commit()
        finally:
            c.close()
    return {"new": new_count, "updated": updated, "total_views": total_views}


def list_channels() -> list[dict]:
    now = int(time.time())
    day = 86400
    with _lock:
        c = _conn()
        try:
            rows = c.execute("SELECT * FROM channels ORDER BY added_at DESC").fetchall()
            out = []
            for row in rows:
                item = dict(row)
                username = item["username"]
                videos = c.execute(
                    "SELECT play, digg, comment, share, create_time FROM videos WHERE username=?",
                    (username,),
                ).fetchall()
                plays = [int(v["play"] or 0) for v in videos]
                item["scanned"] = len(videos)
                item["total_views"] = sum(plays)
                item["avg_views"] = int(sum(plays) / len(plays)) if plays else 0
                item["top_views"] = max(plays) if plays else 0
                recent = [v for v in videos if v["create_time"] and now - int(v["create_time"]) <= 30 * day]
                week = [v for v in recent if now - int(v["create_time"]) <= 7 * day]
                item["posts_7d"] = len(week)
                item["posts_30d"] = len(recent)
                item["views_30d"] = sum(int(v["play"] or 0) for v in recent)
                times = [int(v["create_time"]) for v in videos if v["create_time"]]
                item["last_post"] = max(times) if times else None
                engagement = sum(int(v["digg"] or 0) + int(v["comment"] or 0) + int(v["share"] or 0) for v in videos)
                item["er"] = (engagement / item["total_views"]) if item["total_views"] else 0
                snaps = c.execute(
                    "SELECT followers, likes, total_views FROM snapshots WHERE username=? "
                    "ORDER BY ts DESC LIMIT 2",
                    (username,),
                ).fetchall()
                if len(snaps) >= 2:
                    item["d_followers"] = (snaps[0]["followers"] or 0) - (snaps[1]["followers"] or 0)
                    item["d_likes"] = (snaps[0]["likes"] or 0) - (snaps[1]["likes"] or 0)
                    item["d_views"] = (snaps[0]["total_views"] or 0) - (snaps[1]["total_views"] or 0)
                else:
                    item["d_followers"] = item["d_likes"] = item["d_views"] = None
                out.append(item)
            return out
        finally:
            c.close()


def get_channel(username: str):
    with _lock:
        c = _conn()
        try:
            row = c.execute(
                "SELECT * FROM channels WHERE username=?", (username,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            c.close()


def list_videos(username: str) -> list[dict]:
    with _lock:
        c = _conn()
        try:
            rows = c.execute(
                "SELECT * FROM videos WHERE username=? ORDER BY create_time DESC",
                (username,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            c.close()
