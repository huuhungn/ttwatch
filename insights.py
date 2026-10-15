"""Phân tích dữ liệu đã quét: lịch sử, tổng quan, insight, so sánh, cảnh báo, chế độ xem.

Chỉ đọc (trừ cảnh báo và chế độ xem) và chỉ dùng bảng sẵn có của db.py, nên không đổi
hành vi quét. Thời gian hiển thị theo múi giờ của máy chạy tool.
"""
import json
import statistics
import time
from datetime import datetime

import db

DAY = 86400
METRICS = ("followers", "likes", "video_count", "total_views")
MAX_POINTS = 500


def _downsample(rows, limit=MAX_POINTS):
    """Giữ điểm đầu, điểm cuối và các điểm cách đều ở giữa."""
    if len(rows) <= limit:
        return rows
    step = (len(rows) - 1) / (limit - 1)
    picked = sorted({round(i * step) for i in range(limit)} | {len(rows) - 1})
    return [rows[i] for i in picked]


def history(username, days=None, now=None):
    """Chuỗi snapshot của một kênh, cũ → mới."""
    key = username.lower()
    now = int(now or time.time())
    sql = "SELECT ts, followers, likes, video_count, total_views FROM snapshots WHERE username=?"
    args = [key]
    if days:
        sql += " AND ts >= ?"
        args.append(now - int(days) * DAY)
    with db._lock, db._conn() as c:
        rows = [dict(r) for r in c.execute(sql + " ORDER BY ts, id", args)]
    return _downsample(rows)


def sparklines(days=30, points=24, now=None):
    """{username: [followers...]} cho cột xu hướng; một truy vấn cho mọi kênh."""
    now = int(now or time.time())
    out = {}
    with db._lock, db._conn() as c:
        for r in c.execute(
            "SELECT username, followers FROM snapshots WHERE ts >= ? AND followers IS NOT NULL ORDER BY username, ts, id",
            (now - int(days) * DAY,),
        ):
            out.setdefault(r["username"], []).append(r["followers"])
    return {u: _downsample(v, points) for u, v in out.items() if len(v) >= 2}


def compare(usernames, metric="followers", days=None, now=None):
    if metric not in METRICS:
        metric = "followers"
    series = {}
    for u in usernames[:8]:
        key = u.lower()
        if not db.channel_exists(key):
            continue
        series[key] = [[r["ts"], r[metric]] for r in history(key, days, now) if r[metric] is not None]
    return {"metric": metric, "series": series}


# ---------------------------------------------------------------- tổng quan

def _delta_at(rows, cutoff, field):
    """Mức tăng của `field` từ mốc `cutoff` đến snapshot mới nhất.

    Mốc là snapshot cuối cùng trước hoặc tại cutoff; nếu kênh mới hơn cửa sổ thì lấy
    snapshot sớm nhất trong cửa sổ (partial=True). Cần tối thiểu hai snapshot.
    """
    if len(rows) < 2:
        return None
    latest = rows[-1]
    base = None
    for r in rows:
        if r["ts"] <= cutoff:
            base = r
        else:
            break
    partial = False
    if base is None:
        base, partial = rows[0], True
    if base is latest or base[field] is None or latest[field] is None:
        return None
    return {"delta": latest[field] - base[field], "since": base["ts"], "partial": partial}


def overview(now=None, stale_days=3, top=10):
    now = int(now or time.time())
    channels = db.list_channels()
    with db._lock, db._conn() as c:
        snaps = {}
        for r in c.execute(
            "SELECT username, ts, followers, likes, total_views FROM snapshots WHERE ts >= ? ORDER BY username, ts, id",
            (now - 31 * DAY,),
        ):
            snaps.setdefault(r["username"], []).append(dict(r))
        # Mốc trước cửa sổ 30 ngày, để kênh có lịch sử dài vẫn tính được mức tăng 30 ngày.
        for r in c.execute(
            """SELECT s.username, s.ts, s.followers, s.likes, s.total_views FROM snapshots s
               WHERE s.ts < ? AND s.id = (SELECT id FROM snapshots x WHERE x.username = s.username AND x.ts < ?
                                          ORDER BY ts DESC, id DESC LIMIT 1)""",
            (now - 31 * DAY, now - 31 * DAY),
        ):
            snaps.setdefault(r["username"], []).insert(0, dict(r))
        top_videos = [dict(r) for r in c.execute(
            """SELECT id, username, description, create_time, play, digg, comment, share, collect, cover
               FROM videos WHERE create_time >= ? ORDER BY play DESC LIMIT ?""",
            (now - 30 * DAY, top),
        )]
        n_videos = c.execute("SELECT COUNT(*) FROM videos").fetchone()[0]

    interrupted = [ch for ch in channels if ch["status"] == "error" and (ch["message"] or "").startswith("Bị dừng")]
    errors = [ch for ch in channels if ch["status"] == "error" and ch not in interrupted]
    stale_cut = now - stale_days * DAY
    stale = sorted(
        (ch for ch in channels if ch["status"] not in ("queued", "running") and (ch["updated_at"] or 0) < stale_cut),
        key=lambda ch: ch["updated_at"] or 0,
    )

    def brief(ch):
        return {"username": ch["username"], "unique_id": ch["unique_id"], "nickname": ch["nickname"],
                "avatar": ch["avatar"], "followers": ch["followers"], "updated_at": ch["updated_at"],
                "status": ch["status"], "message": ch["message"]}

    gainers = {}
    for label, days in (("d1", 1), ("d7", 7), ("d30", 30)):
        by_followers, by_views = [], []
        for ch in channels:
            rows = snaps.get(ch["username"], [])
            f = _delta_at(rows, now - days * DAY, "followers")
            v = _delta_at(rows, now - days * DAY, "total_views")
            if f is not None:
                by_followers.append({**brief(ch), **f})
            if v is not None:
                by_views.append({**brief(ch), **v})
        by_followers.sort(key=lambda r: r["delta"], reverse=True)
        by_views.sort(key=lambda r: r["delta"], reverse=True)
        gainers[label] = {"followers": by_followers[:top], "views": by_views[:top]}

    # Tổng follow/view theo ngày: mỗi kênh lấy snapshot cuối ngày và giữ nguyên đến khi có mốc mới.
    day_keys = sorted({r["ts"] // DAY for rows in snaps.values() for r in rows})
    series = []
    last_value = {}
    per_day = {}
    for user, rows in snaps.items():
        for r in rows:
            per_day.setdefault(r["ts"] // DAY, {})[user] = r
    for d in day_keys:
        for user, r in per_day[d].items():
            last_value[user] = r
        series.append({
            "ts": (d + 1) * DAY - 1,
            "followers": sum(v["followers"] or 0 for v in last_value.values()),
            "total_views": sum(v["total_views"] or 0 for v in last_value.values()),
        })

    totals = {
        "channels": len(channels),
        "followers": sum(ch["followers"] or 0 for ch in channels),
        "likes": sum(ch["likes"] or 0 for ch in channels),
        "total_views": sum(ch["total_views"] or 0 for ch in channels),
        "videos": n_videos,
        "posts_7d": sum(ch["posts_7d"] or 0 for ch in channels),
        "errors": len(errors),
        "interrupted": len(interrupted),
        "stale": len(stale),
        "working": sum(1 for ch in channels if ch["status"] in ("queued", "running")),
    }
    return {
        "totals": totals,
        "gainers": gainers,
        "stale": [brief(ch) for ch in stale[:top]],
        "errors": [brief(ch) for ch in errors[:20]],
        "interrupted": [brief(ch) for ch in interrupted[:50]],
        "top_videos": top_videos,
        "series": series[-90:],
        "generated_at": now,
    }


# ---------------------------------------------------------------- insight một kênh

def _bucket(play):
    for limit, label in ((1_000, "<1k"), (10_000, "1k–10k"), (100_000, "10k–100k"), (1_000_000, "100k–1M")):
        if play < limit:
            return label
    return "≥1M"


BUCKETS = ["<1k", "1k–10k", "10k–100k", "100k–1M", "≥1M"]


def channel_insights(username, now=None):
    key = username.lower()
    now = int(now or time.time())
    vids = db.list_videos(key)
    out = {"videos": len(vids)}
    if not vids:
        return {**out, "empty": True, "distribution": [{"label": b, "count": 0} for b in BUCKETS],
                "heatmap": [[{"count": 0, "avg_views": 0} for _ in range(24)] for _ in range(7)],
                "weekly": [], "top": [], "outperformers": []}
    plays = [v["play"] or 0 for v in vids]
    median = statistics.median(plays)
    mean = statistics.fmean(plays)
    ordered = sorted(plays)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    interactions = sum((v["digg"] or 0) + (v["comment"] or 0) + (v["share"] or 0) + (v["collect"] or 0) for v in vids)

    counts = {b: 0 for b in BUCKETS}
    for p in plays:
        counts[_bucket(p)] += 1

    cells = [[[] for _ in range(24)] for _ in range(7)]
    for v in vids:
        if not v["create_time"]:
            continue
        t = datetime.fromtimestamp(v["create_time"])
        cells[t.weekday()][t.hour].append(v["play"] or 0)
    heatmap = [[{"count": len(c), "avg_views": round(statistics.fmean(c)) if c else 0} for c in row] for row in cells]

    weeks = {}
    week_now = now // (7 * DAY)
    for v in vids:
        if v["create_time"]:
            w = week_now - v["create_time"] // (7 * DAY)
            if 0 <= w < 12:
                weeks[w] = weeks.get(w, 0) + 1
    weekly = [{"weeks_ago": w, "posts": weeks.get(w, 0)} for w in range(11, -1, -1)]

    def brief(v):
        return {"id": v["id"], "description": v["description"], "create_time": v["create_time"], "play": v["play"],
                "digg": v["digg"], "comment": v["comment"], "share": v["share"], "collect": v["collect"],
                "cover": v["cover"]}

    top = sorted(vids, key=lambda v: v["play"] or 0, reverse=True)[:5]
    # "Vượt trội": gấp đôi trung vị, và đủ nhiều video để trung vị có nghĩa.
    outperformers = [brief(v) for v in vids if len(vids) >= 5 and median and (v["play"] or 0) >= 2 * median]
    best_hour = None
    flat = [(len(c), r, h) for r, row in enumerate(cells) for h, c in enumerate(row) if len(c) >= 2]
    if flat:
        r, h = max(((r, h) for _, r, h in flat), key=lambda rh: statistics.fmean(cells[rh[0]][rh[1]]))
        best_hour = {"weekday": r, "hour": h, "avg_views": round(statistics.fmean(cells[r][h])),
                     "count": len(cells[r][h])}
    return {
        **out,
        "empty": False,
        "views": {"total": sum(plays), "mean": round(mean), "median": round(median), "p90": p90, "max": max(plays)},
        "er": round(interactions / sum(plays) * 100, 2) if sum(plays) else None,
        "distribution": [{"label": b, "count": counts[b]} for b in BUCKETS],
        "heatmap": heatmap,
        "best_slot": best_hour,
        "weekly": weekly,
        "top": [brief(v) for v in top],
        "outperformers": outperformers[:20],
    }


# ---------------------------------------------------------------- cảnh báo

ALERT_DEFAULTS = {"alerts_enabled": "1", "alert_follow_pct": "5", "alert_new_video": "1"}


def _alert_settings():
    s = db.get_settings()
    return {k: s.get(k, v) for k, v in ALERT_DEFAULTS.items()}


def add_alert(key, kind, text, ts=None):
    with db._lock, db._conn() as c:
        c.execute("INSERT INTO alerts(username, kind, text, ts) VALUES(?,?,?,?)", (key, kind, text, int(ts or time.time())))
        # Giữ bảng gọn: tối đa 500 dòng gần nhất.
        c.execute("DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY id DESC LIMIT 500)")


def check_alerts(key):
    """Gọi sau mỗi lần quét thành công; trả về danh sách cảnh báo vừa tạo."""
    cfg = _alert_settings()
    if cfg["alerts_enabled"] != "1":
        return []
    with db._lock, db._conn() as c:
        snaps = [dict(r) for r in c.execute(
            "SELECT ts, followers, video_count FROM snapshots WHERE username=? ORDER BY ts DESC, id DESC LIMIT 2", (key,))]
        if len(snaps) < 2:
            return []  # lần quét đầu tiên: mọi thứ đều "mới", không cảnh báo
        cur, prev = snaps
        new_videos = [dict(r) for r in c.execute(
            "SELECT id, description FROM videos WHERE username=? AND prev_ts IS NULL AND updated_at >= ? "
            "AND create_time > ? ORDER BY create_time DESC", (key, cur["ts"] - 5, prev["ts"] - DAY))]
        ch = c.execute("SELECT unique_id, followers FROM channels WHERE username=?", (key,)).fetchone()
    name = "@" + ((ch and ch["unique_id"]) or key)
    made = []
    try:
        threshold = float(cfg["alert_follow_pct"])
    except ValueError:
        threshold = 5.0
    if prev["followers"] and cur["followers"] is not None and threshold > 0:
        change = (cur["followers"] - prev["followers"]) / prev["followers"] * 100
        if abs(change) >= threshold:
            sign = "tăng" if change > 0 else "giảm"
            made.append(("followers", f"{name} {sign} {abs(change):.1f}% follow "
                                      f"({prev['followers']:,} → {cur['followers']:,})".replace(",", ".")))
    if cfg["alert_new_video"] == "1" and new_videos:
        n = len(new_videos)
        first = (new_videos[0]["description"] or "").strip().replace("\n", " ")[:80]
        made.append(("new_video", f"{name} có {n} video mới" + (f": {first}" if first else "")))
    for kind, text in made:
        add_alert(key, kind, text)
    return [{"kind": k, "text": t} for k, t in made]


def list_alerts(limit=100, unread_only=False):
    with db._lock, db._conn() as c:
        where = "WHERE read=0" if unread_only else ""
        rows = [dict(r) for r in c.execute(f"SELECT * FROM alerts {where} ORDER BY ts DESC, id DESC LIMIT ?", (limit,))]
        unread = c.execute("SELECT COUNT(*) FROM alerts WHERE read=0").fetchone()[0]
    return {"alerts": rows, "unread": unread}


def mark_alerts_read(ids=None):
    with db._lock, db._conn() as c:
        if ids:
            c.execute(f"UPDATE alerts SET read=1 WHERE id IN ({','.join('?' * len(ids))})", [int(i) for i in ids])
        else:
            c.execute("UPDATE alerts SET read=1")


# ---------------------------------------------------------------- chế độ xem đã lưu

VIEW_PREFIX = "view:"


def list_views():
    with db._lock, db._conn() as c:
        rows = c.execute("SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key", (VIEW_PREFIX + "%",)).fetchall()
    out = []
    for r in rows:
        try:
            out.append({"name": r["key"][len(VIEW_PREFIX):], "data": json.loads(r["value"])})
        except ValueError:
            continue
    return out


def save_view(name, data):
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("Tên chế độ xem trống")
    with db._lock, db._conn() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
                  (VIEW_PREFIX + name, json.dumps(data, ensure_ascii=False)))
    return name


def delete_view(name):
    with db._lock, db._conn() as c:
        c.execute("DELETE FROM settings WHERE key=?", (VIEW_PREFIX + (name or "").strip(),))


# ---------------------------------------------------------------- tự làm mới nâng cao

def in_quiet_hours(hour, start, end):
    """start/end là giờ nguyên 0–23 (chuỗi rỗng = tắt). Khoảng có thể qua nửa đêm."""
    try:
        s, e = int(start), int(end)
    except (TypeError, ValueError):
        return False
    if s == e:
        return False
    return s <= hour < e if s < e else (hour >= s or hour < e)


def auto_job(mode):
    """Job cho lần tự làm mới theo cài đặt `auto_refresh_mode`."""
    if mode == "scan10":
        return {"mode": "scan", "limit": 10}
    return {"mode": "quick"}
