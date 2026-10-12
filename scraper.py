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
import traceback
import urllib.request

import db
from paths import PROFILE_DIR

USERNAME_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._]{2,24})")
SHORT_RE = re.compile(r"(?:vt|vm)\.tiktok\.com/\w+|tiktok\.com/t/\w+")
CAPTCHA_MESSAGE = "Bị captcha – bật 'Hiện trình duyệt' trong Cài đặt rồi giải captcha"
TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "execution context was destroyed",
    "net::err_",
    "target page, context or browser has been closed",
    "không đọc được trang kênh",
)


class CaptchaError(RuntimeError):
    """TikTok hiện captcha: quét lại ngay chỉ làm bị chặn nặng hơn."""


class ProfileBusyError(RuntimeError):
    """Profile trình duyệt đang bị process khác giữ: thử lại ngay không có ích."""


def _first_line(exc: BaseException) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def _profile_in_use(exc: BaseException) -> bool:
    text = str(exc)
    return "existing browser session" in text or "already in use" in text


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (CaptchaError, ProfileBusyError)):
        return False
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)


def describe_job(job: dict) -> str:
    """Mô tả kiểu quét, theo hàm describe_job của bản gốc."""
    mode = job.get("mode", "quick")
    if mode == "quick":
        return "Cập nhật nhanh"
    if mode == "videos":
        return f"Cập nhật view {len(job.get('ids') or [])} video"

    def fmt(ts):
        return time.strftime("%d/%m/%Y", time.localtime(ts))

    parts = []
    if job.get("limit"):
        parts.append(f"{job['limit']} video gần nhất")
    if job.get("days"):
        parts.append(f"{job['days']} ngày qua")
    elif job.get("since") and job.get("until"):
        parts.append(f"từ {fmt(job['since'])} đến {fmt(job['until'])}")
    elif job.get("since"):
        parts.append(f"từ {fmt(job['since'])}")
    elif job.get("until"):
        parts.append(f"đến {fmt(job['until'])}")
    return "Quét " + (", ".join(parts) if parts else "toàn bộ video")


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

    # Lỗi tạm thời (mạng chậm, TikTok chuyển trang, trình duyệt bị đóng) được quét lại
    # sau các khoảng chờ này; lỗi cố định như kênh không tồn tại thì báo ngay.
    RETRY_DELAYS: tuple[int, ...] = (5, 15)

    def _run(self) -> None:
        while True:
            key, job = self._queue.get()
            try:
                self._process(key, job)
            finally:
                self._queue.task_done()
                time.sleep(1.5)

    def _process(self, key: str, job: dict) -> None:
        with self._lock:
            if key in self._jobs:
                self._jobs[key]["status"] = "running"
        attempts = len(self.RETRY_DELAYS) + 1
        for attempt in range(1, attempts + 1):
            db.set_status(key, "running", "" if attempt == 1 else f"Thử lại lần {attempt}/{attempts}")
            try:
                if job.get("mode") == "videos":
                    self._update_videos(key, job.get("ids") or [])
                    count = len(job.get("ids") or [])
                else:
                    count = self._scrape(key, job)
            except Exception as exc:
                traceback.print_exc()
                self._close_browser()
                if attempt < attempts and _is_transient(exc):
                    db.set_status(
                        key,
                        "running",
                        f"Lỗi tạm thời, sẽ thử lại lần {attempt + 1}/{attempts}: {_first_line(exc)}",
                    )
                    time.sleep(self.RETRY_DELAYS[attempt - 1])
                    continue
                message = "Lỗi: " + str(exc)
                if attempt > 1:
                    message += f" (đã thử {attempt} lần)"
                with self._lock:
                    if key in self._jobs:
                        self._jobs[key]["status"] = "error"
                        self._jobs[key]["message"] = message
                db.set_status(key, "error", message)
                return
            with self._lock:
                if key in self._jobs:
                    self._jobs[key]["status"] = "done"
                    self._jobs[key]["videos"] = count
                    self._jobs[key]["total"] = count
            channel = db.get_channel(key) or {}
            if channel.get("status") == "running":
                db.set_status(key, "done", "")
                channel["status"] = "done"
            if channel.get("status") == "done":
                db.record_scan(key, describe_job(job))
            return

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
        # Như bản gốc: dùng lại trình duyệt đang mở. Mở profile lần hai trong cùng app
        # sẽ bị Chrome từ chối vì profile đang được dùng.
        if self._context is not None and getattr(self, "_context_visible", None) == visible:
            return self._context
        self._close_browser()
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
        profile_busy = False
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
                self._context_visible = visible
                return self._context
            except Exception as exc:
                profile_busy = profile_busy or _profile_in_use(exc)
                errors.append(f"{channel or 'chromium'}: {_first_line(exc)}")
        self._close_browser()
        print("\n".join(errors))
        if profile_busy:
            raise ProfileBusyError(
                "Hồ sơ trình duyệt của tool đang bị một cửa sổ trình duyệt khác giữ "
                f"({PROFILE_DIR}). Hãy tắt tool hoặc trình duyệt còn chạy với thư mục dữ liệu này rồi thử lại."
            )
        raise RuntimeError("Không mở được trình duyệt – hãy cài Microsoft Edge hoặc Google Chrome")

    def _close_browser(self) -> None:
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        finally:
            self._context = None
            self._context_visible = None
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
            raw = _evaluate_after_navigation(
                page,
                "() => document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent",
            )
            if raw:
                break
            page.wait_for_timeout(500)
        if not raw:
            if _has_captcha(page):
                raise CaptchaError(CAPTCHA_MESSAGE)
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
            db.set_status(key, "error", CAPTCHA_MESSAGE)
            page.close()
            return 0

        if job.get("mode") == "scan":
            idle = 0
            for _ in range(30):
                if not has_more or idle >= 10 or enough():
                    break
                before = len(responses)
                _evaluate_after_navigation(
                    page, "() => window.scrollTo(0, document.body.scrollHeight)"
                )
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
        return int(result.get("new") or 0) + int(result.get("updated") or 0)

    def _update_videos(self, key: str, ids) -> None:
        channel = db.get_channel(key) or {}
        username = channel.get("unique_id") or key
        page = self._browser().new_page()
        rows = []
        missing = 0
        try:
            for n, video_id in enumerate(ids, 1):
                item = None
                try:
                    page.goto(
                        f"https://www.tiktok.com/@{username}/video/{video_id}",
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                except Exception:
                    pass
                for _ in range(24):
                    try:
                        raw = page.evaluate(
                            "() => document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent"
                        )
                    except Exception:
                        raw = None
                    if raw:
                        item, status = _video_detail(raw)
                        if item or status:
                            break
                    page.wait_for_timeout(500)
                if item:
                    rows.append(_video_row(item, key))
                else:
                    missing += 1
                with self._lock:
                    job = self._jobs.get(key)
                    if job:
                        job["videos"] = n
        finally:
            try:
                page.close()
            except Exception:
                pass
        db.finish_scan(key, rows, full=False)
        note = f"Cập nhật view {len(rows)} video"
        if missing:
            note += f" – {missing} video không lấy được (đã xóa, bị ẩn hoặc bị chặn)"
        db.set_status(key, "done", note)


def _evaluate_after_navigation(page, script: str):
    """Chạy JS; nếu TikTok chuyển trang giữa chừng thì chờ trang mới và trả None."""
    try:
        return page.evaluate(script)
    except Exception as exc:
        text = str(exc)
        if "Execution context was destroyed" not in text and "navigat" not in text.lower():
            raise
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    return None


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _video_detail(raw: str):
    try:
        detail = json.loads(raw).get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
    except ValueError:
        return None, None
    item = (detail.get("itemInfo") or {}).get("itemStruct")
    return (item if item and item.get("id") else None), detail.get("statusCode")


def _video_row(item: dict, username: str) -> dict | None:
    return _video_from_item(item, username)


def _has_captcha(page) -> bool:
    try:
        return page.locator(
            "#captcha-container, .captcha_verify_container, [class*='captcha']"
        ).count() > 0
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
