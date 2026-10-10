"""Lấy dữ liệu TikTok bằng trình duyệt thật (Playwright, sync API, chạy trong 1 thread riêng).

TikTok chặn chế độ headless khi tải danh sách video, nên luôn chạy trình duyệt có cửa sổ;
chế độ "ẩn" chỉ là đẩy cửa sổ ra ngoài màn hình.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.request

import db
from paths import PROFILE_DIR

USERNAME_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._]{2,24})")
SHORT_RE = re.compile(r"(?:vt|vm)\.tiktok\.com/\w+|tiktok\.com/t/\w+")


def resolve_short_url(url: str) -> str | None:
    if not url.startswith("http"):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            final = response.geturl()
    except Exception:
        return None
    match = USERNAME_RE.search(final)
    return match.group(1).lower() if match else None


def parse_input(text: str) -> tuple[list[str], list[str]]:
    tokens = re.split(r"[\s,;]+", text.strip())
    found: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if not tok:
            continue
        match = USERNAME_RE.search(tok)
        if match:
            username = match.group(1).lower()
        elif SHORT_RE.search(tok) or "tiktok.com" in tok:
            username = resolve_short_url(tok)
            if not username:
                invalid.append(tok)
                continue
        else:
            username = tok.lstrip("@").lower()
            if not re.fullmatch(r"[A-Za-z0-9._]{2,24}", username):
                invalid.append(tok)
                continue
        if username not in seen:
            seen.add(username)
            found.append(username)
    return found, invalid


class Scraper:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._playwright = None
        self._context = None
        self._thread = threading.Thread(target=self._run, name="scraper", daemon=True)
        self._refresh = threading.Thread(
            target=self._auto_refresh_loop, name="refresh", daemon=True
        )
        self._thread.start()
        self._refresh.start()

    def enqueue(self, usernames: list[str], job: dict) -> int:
        """job: {"mode": "quick"} = thông tin kênh + video mới nhất,
        {"mode": "scan", "limit": N, "since": ts, "until": ts} = cuộn kênh.
        limit/since/until = 0 nghĩa là không giới hạn.
        """
        added = 0
        with self._lock:
            for username in usernames:
                key = username.lower()
                prev = self._jobs.get(key)
                if prev and prev.get("status") in ("queued", "running"):
                    continue
                self._jobs[key] = {
                    "username": key,
                    "status": "queued",
                    "mode": job.get("mode", "quick"),
                    "job": job,
                    "videos": 0,
                    "message": "",
                }
                self._queue.put((key, job))
                added += 1
                db.set_status(key, "queued", "")
        return added

    def status(self) -> dict:
        with self._lock:
            current = next(
                (item for item in self._jobs.values() if item["status"] == "running"),
                None,
            )
            queue_items = [
                item for item in self._jobs.values() if item["status"] == "queued"
            ]
            return {"current": current, "queue": queue_items}

    def _run(self) -> None:
        while True:
            key, job = self._queue.get()
            try:
                with self._lock:
                    if key in self._jobs:
                        self._jobs[key]["status"] = "running"
                db.set_status(key, "running", "")
                count = self._scrape(key, job)
                with self._lock:
                    if key in self._jobs:
                        self._jobs[key]["status"] = "done"
                        self._jobs[key]["videos"] = count
                        self._jobs[key]["total"] = count
                db.set_status(key, "done", "")
            except Exception as exc:
                message = "Lỗi: " + str(exc)
                with self._lock:
                    if key in self._jobs:
                        self._jobs[key]["status"] = "error"
                        self._jobs[key]["message"] = message
                db.set_status(key, "error", message)
            finally:
                self._queue.task_done()
                time.sleep(1.5)

    def _auto_refresh_loop(self) -> None:
        while True:
            time.sleep(30)
            raw = db.get_setting("auto_refresh_minutes", "0") or "0"
            try:
                minutes = int(raw)
            except ValueError:
                minutes = 0
            if minutes <= 0:
                continue
            now = time.time()
            for username in db.all_usernames():
                channel = db.get_channel(username)
                if not channel:
                    continue
                updated = channel.get("updated_at") or 0
                if now - updated >= minutes * 60:
                    self.enqueue([username], {"mode": "quick"})

    def _browser(self):
        from playwright.sync_api import sync_playwright

        visible = db.get_setting("show_browser", "0") == "1"
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-features=CalculateNativeWinOcclusion",
        ]
        if not visible:
            args.append("--window-position=-32000,-32000")
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        errors = []
        for channel in ("msedge", "chrome", None):
            try:
                kwargs = {
                    "headless": False,
                    "args": args,
                    "locale": "vi-VN",
                    "viewport": {"width": 1280, "height": 900},
                }
                if channel:
                    kwargs["channel"] = channel
                PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(PROFILE_DIR), **kwargs
                )
                return self._context
            except Exception as exc:
                errors.append(f"{channel or 'chromium'}: {exc}")
        raise RuntimeError(
            "Không mở được trình duyệt – hãy cài Microsoft Edge hoặc Google Chrome\n"
            + "\n".join(errors)
        )

    def _close_browser(self) -> None:
        try:
            if self._context:
                self._context.close()
        finally:
            self._context = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None

    def _scrape(self, key: str, job: dict) -> int:
        ctx = self._browser()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        captured: list[dict] = []

        def on_response(response):
            url = response.url
            if "/api/post/item_list" not in url:
                return
            try:
                payload = response.json()
            except Exception:
                return
            captured.append(payload)

        page.on("response", on_response)
        page.goto(
            "https://www.tiktok.com/@" + key,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        raw = None
        for _ in range(20):
            raw = page.evaluate(
                "() => document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent"
            )
            if raw:
                break
            page.wait_for_timeout(500)
        if not raw:
            body = page.content()
            if "captcha" in body.lower():
                raise RuntimeError(
                    "Bị captcha – bật 'Hiện trình duyệt' trong Cài đặt rồi giải captcha"
                )
            raise RuntimeError("Không đọc được trang kênh")
        data = json.loads(raw)
        scope = data.get("__DEFAULT_SCOPE__", {})
        detail = scope.get("webapp.user-detail", {})
        info = detail.get("userInfo") or {}
        user = info.get("user") or {}
        if not user.get("uniqueId"):
            code = detail.get("statusCode")
            if code in (10221, 10202, 404):
                raise RuntimeError("Kênh không tồn tại hoặc bị khóa")
            raise RuntimeError(f"Không lấy được kênh (mã {code})")
        stats = info.get("stats") or info.get("statsV2") or {}
        bio_link = (user.get("bioLink") or {}).get("link") or ""
        channel_info = {
            "unique_id": user.get("uniqueId") or key,
            "nickname": user.get("nickname") or "",
            "avatar": user.get("avatarMedium") or user.get("avatarThumb") or "",
            "verified": 1 if user.get("verified") else 0,
            "private": 1 if user.get("privateAccount") else 0,
            "sec_uid": user.get("secUid") or "",
            "followers": _num(stats.get("followerCount")),
            "following": _num(stats.get("followingCount")),
            "likes": _num(stats.get("heartCount") or stats.get("heart")),
            "video_count": _num(stats.get("videoCount")),
            "bio": user.get("signature") or "",
            "bio_link": bio_link,
            "created_at": user.get("createTime") or 0,
        }
        db.save_channel_info(key, channel_info)
        if channel_info["private"]:
            db.set_status(key, "done", "Tài khoản riêng tư – không xem được video")
            return 0

        limit = int(job.get("limit") or 0)
        since = int(job.get("since") or 0)
        until = int(job.get("until") or 0)
        days = int(job.get("days") or 0)
        if days and not since:
            since = int(time.time()) - days * 86400
        mode = job.get("mode") or "quick"
        max_scrolls = 30 if mode == "scan" else 2
        seen: set[str] = set()
        videos: list[dict] = []
        idle = 0
        for _ in range(max_scrolls):
            before = len(captured)
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            if len(captured) == before:
                idle += 1
                if idle >= 3:
                    break
            else:
                idle = 0
            for payload in captured:
                for item in payload.get("itemList") or []:
                    video = _video_from_item(item, key)
                    if not video or video["id"] in seen:
                        continue
                    created = video.get("create_time") or 0
                    if since and created < since:
                        continue
                    if until and created > until:
                        continue
                    seen.add(video["id"])
                    videos.append(video)
                    if limit and len(videos) >= limit:
                        break
            if limit and len(videos) >= limit:
                break
        full = mode == "scan" and not limit and not since and not until
        db.finish_scan(key, videos, full=full)
        return len(videos)


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _video_from_item(item: dict, username: str) -> dict | None:
    video_id = item.get("id")
    if not video_id:
        return None
    stats = item.get("stats") or item.get("statsV2") or {}
    video = item.get("video") or {}
    music = item.get("music") or {}
    return {
        "id": str(video_id),
        "username": username,
        "description": item.get("desc") or "",
        "create_time": _num(item.get("createTime")),
        "duration": _num(video.get("duration")),
        "cover": video.get("cover") or video.get("originCover") or "",
        "play": _num(stats.get("playCount")),
        "digg": _num(stats.get("diggCount")),
        "comment": _num(stats.get("commentCount")),
        "share": _num(stats.get("shareCount")),
        "collect": _num(stats.get("collectCount")),
        "music": music.get("title") or "",
        "is_ad": 1 if item.get("isAd") else 0,
    }
