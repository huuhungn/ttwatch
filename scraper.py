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
            if code in (10221, 10202):
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
        video_count = int(channel_info["video_count"] or 0)
        responses = captured
        items: dict[str, dict] = {}
        seen: set[str] = set()
        done_responses = 0
        has_more = True
        tail_time = None

        def collect() -> None:
            nonlocal done_responses, has_more, tail_time
            while done_responses < len(responses):
                payload = responses[done_responses]
                done_responses += 1
                if not payload:
                    continue
                has_more = bool(payload.get("hasMore", has_more))
                for raw_item in payload.get("itemList") or []:
                    video = _video_row(raw_item, key)
                    if not video or video["id"] in seen:
                        continue
                    seen.add(video["id"])
                    items[video["id"]] = video
                    created = video["create_time"]
                    if created and (tail_time is None or created < tail_time):
                        tail_time = created

        def enough() -> bool:
            if limit and len(items) >= limit:
                return True
            if since and tail_time is not None and tail_time < since:
                return True
            return False

        for _ in range(30):
            page.wait_for_timeout(500)
            collect()
            if items:
                break
            if not (responses and done_responses < len(responses) and has_more):
                break

        if not items and video_count and _has_captcha(page):
            db.set_status(
                key,
                "error",
                "Bị captcha – bật 'Hiện trình duyệt' trong Cài đặt rồi giải captcha",
            )
            page.close()
            return 0

        if job.get("mode") == "scan":
            idle = 0
            for _ in range(30):
                if not has_more or idle >= 10 or enough():
                    break
                before = len(responses)
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1200)
                collect()
                idle = idle + 1 if len(responses) == before else 0

        videos = list(items.values())
        if until:
            videos = [video for video in videos if video["create_time"] <= until]
        videos.sort(key=lambda video: video["create_time"], reverse=True)
        if limit:
            videos = videos[:limit]
        is_full = job["mode"] == "scan" and not limit and not since and not until
        result = db.finish_scan(key, videos, full=is_full)
        note = ""
        if not has_more and video_count and len(videos) < video_count:
            note = f"{len(videos)}/{video_count} video – TikTok ngừng trả thêm, thử quét lại sau"
        if note:
            db.set_status(key, "done", note)
        if job.get("ids"):
            self._update_videos(key, job["ids"])
        return int(result.get("new") or 0) + int(result.get("updated") or 0)

    def _update_videos(self, key: str, ids) -> None:
        wanted = {str(video_id) for video_id in ids}
        if not wanted:
            return
        channel = db.get_channel(key) or {}
        username = channel.get("unique_id") or key
        ctx = self._browser()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        captured: list[dict] = []

        def on_response(response):
            if "/api/post/item_list" not in response.url:
                return
            try:
                captured.append(response.json())
            except Exception:
                return

        page.on("response", on_response)
        page.goto(
            "https://www.tiktok.com/@" + username,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        found: dict[str, dict] = {}
        for _ in range(20):
            page.wait_for_timeout(500)
            for payload in captured:
                for raw_item in payload.get("itemList") or []:
                    video = _video_row(raw_item, key)
                    if video and video["id"] in wanted:
                        found[video["id"]] = video
            if wanted <= set(found):
                break
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.mouse.wheel(0, 3000)
        if found:
            db.finish_scan(key, list(found.values()), full=False)


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _video_row(item: dict, username: str) -> dict | None:
    return _video_from_item(item, username)


def _has_captcha(page) -> bool:
    try:
        return bool(
            page.locator(
                "[class*='captcha-verify'], [id*='captcha-verify'], iframe[src*='captcha']"
            ).count()
        )
    except Exception:
        return False


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
