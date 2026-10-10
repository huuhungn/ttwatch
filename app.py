import asyncio
import io
import json
import os
import socket
import sys
import threading
import urllib.request
import webbrowser
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel

import db
from paths import APP_NAME, DATA_DIR, STATIC_DIR
from scraper import Scraper, parse_input

HOST = "127.0.0.1"
app = FastAPI(title=APP_NAME)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
scraper = Scraper()


class AddReq(BaseModel):
    text: str = ""
    scan: dict | None = None


class UsersReq(BaseModel):
    usernames: list[str]


class RefreshReq(BaseModel):
    usernames: list[str] = []
    job: dict | None = None


class MetaReq(BaseModel):
    usernames: list[str]
    group_name: str | None = None
    note: str | None = None


class OpenReq(BaseModel):
    urls: list[str] = []


class SettingsReq(BaseModel):
    show_browser: str | None = None
    auto_refresh_minutes: int | str | None = None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


@app.get("/api/ping")
def ping():
    return {"ok": True, "name": APP_NAME}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/videos")
def videos_page():
    return FileResponse(STATIC_DIR / "videos.html")


@app.post("/api/channels")
def add_channels(req: AddReq):
    usernames, invalid = parse_input(req.text)
    added, existed = db.add_channels(usernames)
    job = req.scan or {"mode": "quick"}
    scraper.enqueue(added, job)
    return {"added": added, "existed": existed, "invalid": invalid}


@app.get("/api/channels")
def list_channels():
    return {"channels": db.list_channels(), "worker": scraper.status()}


@app.post("/api/channels/delete")
def delete_channels(req: UsersReq):
    return {"deleted": db.delete_channels(req.usernames)}


@app.post("/api/channels/refresh")
def refresh(req: RefreshReq):
    usernames = req.usernames or db.all_usernames()
    job = req.job or {"mode": "quick"}
    queued = scraper.enqueue(usernames, job)
    return {"queued": queued}


@app.post("/api/channels/meta")
def update_meta(req: MetaReq):
    db.update_meta(req.usernames, req.group_name, req.note)
    return {"ok": True}


@app.get("/api/channels/{username}/videos")
def channel_videos(username: str):
    channel = db.get_channel(username)
    if not channel:
        raise HTTPException(404, "Không có kênh này")
    return {
        "channel": channel,
        "videos": db.list_videos(username),
        "worker": scraper.status(),
    }


@app.post("/api/open")
def open_urls(req: OpenReq):
    for url in req.urls:
        webbrowser.open(url)
    return {"opened": len(req.urls)}


@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.post("/api/settings")
def set_settings(req: SettingsReq):
    values = {
        key: value
        for key, value in req.model_dump().items()
        if value is not None
    }
    db.set_settings(values)
    return db.get_settings()


def _workbook(headers: list[str], rows: list[list]) -> io.BytesIO:
    book = Workbook()
    sheet = book.active
    if sheet is None:
        sheet = book.create_sheet("Sheet")
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    buf = io.BytesIO()
    book.save(buf)
    buf.seek(0)
    return buf


@app.get("/api/export/channels.xlsx")
def export_channels(usernames: str = ""):
    selected = [u for u in usernames.split(",") if u] if usernames else None
    channels = db.list_channels()
    if selected:
        wanted = set(selected)
        channels = [ch for ch in channels if ch["username"] in wanted]
    headers = [
        "username",
        "nickname",
        "followers",
        "following",
        "likes",
        "video_count",
        "group_name",
        "note",
        "status",
        "message",
    ]
    rows = [[ch.get(h) for h in headers] for ch in channels]
    buf = _workbook(headers, rows)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=channels.xlsx"},
    )


@app.get("/api/export/videos/{username}.xlsx")
def export_videos(username: str):
    videos = db.list_videos(username)
    headers = [
        "id",
        "description",
        "create_time",
        "duration",
        "play",
        "digg",
        "comment",
        "share",
        "collect",
        "music",
    ]
    rows = [[video.get(h) for h in headers] for video in videos]
    buf = _workbook(headers, rows)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={username}.xlsx"},
    )


@app.post("/api/shutdown")
def shutdown():
    threading.Thread(target=_exit_soon, daemon=True).start()
    return {"ok": True}


def _exit_soon() -> None:
    import time

    time.sleep(0.3)
    os._exit(0)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db.init()
    port = _free_port()
    url = f"http://{HOST}:{port}/"
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    webbrowser.open(url)
    try:
        from tray import run_tray

        run_tray(url, on_quit=lambda: os._exit(0))
    except Exception:
        # Không có khay hệ thống thì giữ process bằng server.
        server_thread_join()


def server_thread_join() -> None:
    while True:
        import time

        time.sleep(3600)


if __name__ == "__main__":
    main()
