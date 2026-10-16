import asyncio
import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import socket
import sys
import threading
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel

import db
import insights
import instance_lock
from paths import APP_NAME, DATA_DIR, STATIC_DIR as STATIC
from scraper import Scraper, parse_input

HOST = "127.0.0.1"
PORT = 8765
APP_ID = "theo-doi-kenh-tiktok"
_instance = None

scraper: Scraper = None
app = FastAPI(title=APP_NAME)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/ping")
def ping():
    return {"app": APP_ID}


class AddReq(BaseModel):
    text: str
    scan: dict | None = None


class UsersReq(BaseModel):
    usernames: list[str]


class ScanReq(BaseModel):
    usernames: list[str]
    job: dict


class MetaReq(BaseModel):
    usernames: list[str]
    group_name: str | None = None
    note: str | None = None


class OpenReq(BaseModel):
    urls: list[str]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/videos")
def videos_page():
    return FileResponse(STATIC / "videos.html")


@app.post("/api/channels")
async def add_channels(req: AddReq):
    usernames, invalid = await asyncio.to_thread(parse_input, req.text)
    added, existed = db.add_channels(usernames)
    scraper.enqueue(added, req.scan)
    return {"added": added, "existed": existed, "invalid": invalid}


@app.get("/api/channels")
def list_channels():
    channels = db.list_channels()
    interrupted = sum(1 for c in channels if c["status"] == "error" and (c["message"] or "").startswith("Bị dừng"))
    return {"channels": channels, "worker": scraper.status(), "interrupted": interrupted}


@app.post("/api/channels/delete")
def delete_channels(req: UsersReq):
    db.delete_channels(req.usernames)
    return {"ok": True}


@app.post("/api/channels/refresh")
def refresh(req: ScanReq):
    return {"queued": scraper.enqueue([u.lower() for u in req.usernames if db.channel_exists(u.lower())], req.job)}


@app.post("/api/channels/meta")
def update_meta(req: MetaReq):
    db.update_meta(req.usernames, req.group_name, req.note)
    return {"ok": True}


@app.get("/api/channels/{username}/videos")
def channel_videos(username: str):
    ch = db.get_channel(username)
    if not ch:
        raise HTTPException(404, "Không có kênh này trong danh sách")
    return {"channel": ch, "videos": db.list_videos(username), "worker": scraper.status()}


@app.post("/api/open")
def open_urls(req: OpenReq):
    """Open several tabs at once in the default browser (a web page cannot open many popups)."""
    for u in req.urls[:100]:
        if u.startswith("https://www.tiktok.com/") or u.startswith(f"http://{HOST}:{PORT}/"):
            webbrowser.open_new_tab(u)
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.post("/api/settings")
def set_settings(values: dict):
    db.set_settings(values)
    return db.get_settings()




# ---------------------------------------------------------------- API: history, overview, alerts, import/export

def _need_channel(username):
    if not db.channel_exists(username.lower()):
        raise HTTPException(404, "Không có kênh này trong danh sách")


@app.get("/api/channels/{username}/history")
def channel_history(username: str, days: int = 0):
    _need_channel(username)
    return {"points": insights.history(username, days or None)}


@app.get("/api/channels/{username}/insights")
def channel_insights(username: str):
    _need_channel(username)
    return insights.channel_insights(username)


@app.get("/api/sparklines")
def sparklines(days: int = 30):
    return insights.sparklines(max(1, min(days, 365)))


@app.get("/api/overview")
def overview():
    return insights.overview()


@app.get("/api/compare")
def compare(usernames: str = "", metric: str = "followers", days: int = 0):
    names = [u for u in usernames.split(",") if u.strip()]
    return insights.compare(names, metric, days or None)


class AlertsReadReq(BaseModel):
    ids: list[int] | None = None


@app.get("/api/alerts")
def alerts(unread: bool = False, limit: int = 100):
    return insights.list_alerts(max(1, min(limit, 500)), unread)


@app.post("/api/alerts/read")
def alerts_read(req: AlertsReadReq):
    insights.mark_alerts_read(req.ids)
    return insights.list_alerts(0)


class ViewReq(BaseModel):
    name: str
    data: dict = {}


@app.get("/api/views")
def views():
    return {"views": insights.list_views()}


@app.post("/api/views")
def save_view(req: ViewReq):
    try:
        insights.save_view(req.name, req.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"views": insights.list_views()}


@app.post("/api/views/delete")
def delete_view(req: ViewReq):
    insights.delete_view(req.name)
    return {"views": insights.list_views()}


class ImportReq(BaseModel):
    text: str
    scan: dict | None = None


@app.post("/api/import/channels")
async def import_channels(req: ImportReq):
    """Import a channel list. With a CSV header row (username,group,note), group and note are imported too."""
    rows = list(csv.reader(io.StringIO(req.text)))
    head = [h.strip().lower() for h in rows[0]] if rows else []
    is_csv = bool(head) and head[0] in ("username", "user", "kênh", "kenh", "channel", "link", "url")
    if not is_csv:
        usernames, invalid = await asyncio.to_thread(parse_input, req.text)
        added, existed = db.add_channels(usernames)
        scraper.enqueue(added, req.scan)
        return {"added": added, "existed": existed, "invalid": invalid, "meta": 0}

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None

    gi, ni = col("group", "nhóm", "nhom", "group_name"), col("note", "ghi chú", "ghi chu")
    added, existed, invalid, meta = [], [], [], 0
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        found, bad = await asyncio.to_thread(parse_input, row[0])
        invalid += bad
        if not found:
            continue
        a, e = db.add_channels(found[:1])
        added += a
        existed += e
        group = row[gi].strip() if gi is not None and gi < len(row) else None
        note = row[ni].strip() if ni is not None and ni < len(row) else None
        if group or note:
            db.update_meta(found[:1], group or None, note or None)
            meta += 1
    scraper.enqueue(added, req.scan)
    return {"added": added, "existed": existed, "invalid": invalid, "meta": meta}


@app.get("/api/backups")
def backups():
    return {"backups": [{"name": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime)}
                        for p in db.list_backups()]}


@app.get("/api/export/backup")
def export_backup():
    """Consistent copy of the whole DB (channels, videos, history, settings)."""
    tmp = Path(tempfile.mkdtemp(prefix="ttwatch-")) / "data.db"
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    try:
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    name = f"ttwatch-backup-{datetime.now():%Y%m%d_%H%M}.db"
    return FileResponse(tmp, media_type="application/octet-stream", filename=name,
                        background=BackgroundTask(lambda: shutil.rmtree(tmp.parent, ignore_errors=True)))


@app.get("/api/export/history/{username}.csv")
def export_history_csv(username: str):
    _need_channel(username)
    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(["Thời điểm", "Follow", "Lượt thích", "Số video", "Tổng view"])
    for p in insights.history(username):
        w.writerow([_ts(p["ts"]), p["followers"], p["likes"], p["video_count"], p["total_views"]])
    return Response(out.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="lich_su_{username.lower()}.csv"'})


def _ts(v):
    return datetime.fromtimestamp(v).strftime("%d/%m/%Y %H:%M") if v else ""


def _xlsx(name, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in list(col)[:200])
        ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export/channels.xlsx")
def export_channels(usernames: str = ""):
    wanted = {u.lower() for u in usernames.split(",") if u}
    rows = [c for c in db.list_channels() if not wanted or c["username"] in wanted]
    headers = ["Username", "Tên kênh", "Link", "Follow", "Tăng follow", "Following", "Lượt thích", "Tổng view", "Tăng view",
               "Số video", "Video đã quét", "View TB/video", "Tỷ lệ tương tác %", "View cao nhất", "Video 7 ngày",
               "Video 30 ngày", "View 30 ngày", "Đăng gần nhất", "Tick xanh", "Riêng tư", "Nhóm", "Ghi chú", "Bio",
               "Link bio", "Cập nhật lúc"]
    data = [[c["unique_id"], c["nickname"], f"https://www.tiktok.com/@{c['unique_id']}", c["followers"],
             c["d_followers"], c["following"], c["likes"], c["total_views"], c["d_views"], c["video_count"],
             c["scanned"], c["avg_views"], c["er"], c["top_views"], c["posts_7d"], c["posts_30d"], c["views_30d"],
             _ts(c["last_post"]), "Có" if c["verified"] else "", "Có" if c["private"] else "", c["group_name"],
             c["note"], c["bio"], c["bio_link"], _ts(c["updated_at"])] for c in rows]
    return _xlsx(f"kenh_tiktok_{datetime.now():%Y%m%d_%H%M}.xlsx", headers, data)


def _video_table(username):
    ch = db.get_channel(username)
    if not ch:
        raise HTTPException(404)
    uid = ch["unique_id"] or username
    headers = ["Link", "Mô tả", "Ngày đăng", "Thời lượng (s)", "View", "Tăng view", "Tim", "Bình luận", "Chia sẻ",
               "Lưu", "Tỷ lệ tương tác %", "Nhạc"]
    data = []
    for v in db.list_videos(username):
        inter = v["digg"] + v["comment"] + v["share"] + v["collect"]
        data.append([f"https://www.tiktok.com/@{uid}/video/{v['id']}", v["description"], _ts(v["create_time"]),
                     v["duration"], v["play"], v["play"] - v["prev_play"] if v["prev_play"] is not None else None,
                     v["digg"], v["comment"], v["share"], v["collect"],
                     round(inter / v["play"] * 100, 2) if v["play"] else None, v["music"]])
    return uid, headers, data


@app.get("/api/export/videos/{username}.xlsx")
def export_videos(username: str):
    uid, headers, data = _video_table(username)
    return _xlsx(f"video_{uid}_{datetime.now():%Y%m%d_%H%M}.xlsx", headers, data)


def _csv_cell(value):
    # Spreadsheets treat text cells starting with = + - @ as formulas; numbers are left as is.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@app.get("/api/export/videos/{username}.csv")
def export_videos_csv(username: str):
    uid, headers, data = _video_table(username)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    for row in data:
        writer.writerow([_csv_cell(cell) for cell in row])
    name = f"video_{uid}_{datetime.now():%Y%m%d_%H%M}.csv"
    return Response(
        out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _is_our_tool(port):
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/ping", timeout=2) as r:
            return json.load(r).get("app") == APP_ID
    except Exception:
        return False


def _port_free(port):
    with socket.socket() as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def _message_box(text):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 64)
    else:
        print(text)


server: uvicorn.Server = None


def shutdown():
    if server:
        server.should_exit = True
    # Wait briefly so the HTTP response is sent before the process exits for good.
    threading.Timer(1.5, lambda: os._exit(0)).start()


@app.post("/api/shutdown")
def api_shutdown():
    shutdown()
    return {"ok": True}


def main():
    global PORT, scraper, server, _instance
    open_browser = not os.environ.get("NO_OPEN")
    # Another copy of the tool is already running (same default data folder): just reopen the page
    # instead of starting a second copy that would fight over the browser and the database.
    # Skipped when TDK_DATA_DIR is set (separate run, tests).
    for port in ([] if os.environ.get("TDK_DATA_DIR") else range(8765, 8775)):
        if _is_our_tool(port):
            print(f"{APP_NAME} đang chạy sẵn tại http://{HOST}:{port} – đang mở lại trang...")
            if open_browser:
                webbrowser.open(f"http://{HOST}:{port}")
            return
    # Two copies sharing one data folder would fight over the browser profile and overwrite
    # each other's channel state, even when they listen on different ports.
    try:
        _instance = instance_lock.acquire(DATA_DIR)
    except instance_lock.AlreadyRunning as exc:
        _message_box(str(exc))
        return
    PORT = next((p for p in range(8765, 8775) if _port_free(p)), 0)
    if not PORT:
        _message_box("Không tìm được cổng trống (8765-8774) để chạy tool.\nHãy khởi động lại máy rồi thử lại.")
        return

    db.init()
    scraper = Scraper()
    url = f"http://{HOST}:{PORT}"
    print(f"{APP_NAME} đang chạy tại: {url}\nDữ liệu lưu tại: {DATA_DIR}")
    # Disable the access log; keep warnings only.
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning",
                                           loop="asyncio", http="h11", ws="none", log_config=None))
    threading.Thread(target=server.run, daemon=True).start()

    def open_when_ready():
        for _ in range(100):
            if server.started:
                break
            threading.Event().wait(0.1)
        if open_browser:
            webbrowser.open(url)
    threading.Thread(target=open_when_ready, daemon=True).start()

    if os.environ.get("NO_TRAY"):
        threading.Event().wait()
    else:
        from tray import run_tray
        run_tray(url, shutdown)


if __name__ == "__main__":
    if sys.stdout is None:
        # Running as an exe without a console: write all printed output to log.txt next to the data.
        log_path = DATA_DIR / "log.txt"
        too_big = log_path.exists() and log_path.stat().st_size > 2000000
        log = open(log_path, "w" if too_big else "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        print(f"\n===== {datetime.now():%d/%m/%Y %H:%M:%S} =====")
    else:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _message_box(f"Tool gặp lỗi khi khởi động:\n{e}\n\nChi tiết trong file log.txt ở thư mục dữ liệu.")
