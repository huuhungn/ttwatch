"""Lấy dữ liệu TikTok bằng trình duyệt thật (Playwright, sync API, chạy trong 1 thread riêng).

TikTok chặn chế độ headless khi tải danh sách video, nên luôn chạy trình duyệt có cửa sổ;
chế độ "ẩn" chỉ là đẩy cửa sổ ra ngoài màn hình.
"""
import json
import queue
import re
import threading
import time
import traceback
import urllib.request

from playwright.sync_api import sync_playwright

import db
from paths import PROFILE_DIR

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{2,24}$")
URL_USER_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._]{2,24})", re.I)
SHORT_URL_RE = re.compile(r"(?:vt|vm)\.tiktok\.com/\w+|tiktok\.com/t/\w+", re.I)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"





# --- Phần bổ sung sau bản gốc ------------------------------------------------------
ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
WRAP_OPEN = "([{<\"'\u201c\u2018\u00ab"
WRAP_CLOSE = ")]}>\"'\u201d\u2019\u00bb"
TRAILING_PUNCT = "!?:\u2026"
# Lỗi tạm thời (mạng chậm, TikTok chuyển trang, trình duyệt bị đóng) được quét lại sau
# các khoảng chờ trong Scraper.RETRY_DELAYS; lỗi cố định thì báo ngay.
TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "execution context was destroyed",
    "net::err_",
    "target page, context or browser has been closed",
)


class ProfileBusyError(RuntimeError):
    """Profile trình duyệt đang bị process khác giữ: thử lại ngay không có ích."""


def _first_line(exc):
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def _is_transient(exc):
    if isinstance(exc, ProfileBusyError):
        return False
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)


def _evaluate_after_navigation(page, script):
    """Chạy JS; nếu TikTok chuyển trang giữa chừng thì chờ trang mới và trả None.

    Bản gốc gọi thẳng page.evaluate nên "Execution context was destroyed" làm cả kênh
    thành lỗi; trả None để vòng lặp sẵn có tự thử lại.
    """
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


def _clean_token(tok):
    """Bỏ nhiễu khi dán: ký tự rộng 0, @ toàn chiều rộng, ngoặc/nháy bao quanh, dấu câu cuối."""
    tok = ZERO_WIDTH_RE.sub("", tok).replace("\uff20", "@")
    tok = tok.lstrip(WRAP_OPEN)
    if tok.startswith("@") or "tiktok.com" in tok.lower():
        return tok.rstrip(WRAP_CLOSE + TRAILING_PUNCT)
    return tok.rstrip(WRAP_CLOSE)


def resolve_short_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            final = r.geturl()
    except Exception:
        return None
    m = URL_USER_RE.search(final)
    return m.group(1) if m else None


def parse_input(text):
    """Tách text thành danh sách username. Trả về (usernames, invalid_tokens)."""
    tokens = re.split(r"[\s,;]+", (text or "").strip())
    found, invalid = [], []
    seen = set()
    for raw in tokens:
        if not raw:
            continue
        tok = _clean_token(raw)
        m = URL_USER_RE.search(tok)
        if m:
            username = m.group(1).lower()
        elif SHORT_URL_RE.search(tok) or "tiktok.com" in tok.lower():
            username = resolve_short_url(tok)
            if not username:
                invalid.append(raw)
                continue
            username = username.lower()
        else:
            username = tok.lstrip("@").lower()
            if not USERNAME_RE.match(username):
                invalid.append(raw)
                continue
        if username not in seen:
            seen.add(username)
            found.append(username)
    return found, invalid


class Scraper:
    RETRY_DELAYS = (5, 15)

    def __init__(self):
        self.jobs = queue.Queue()
        self.pending = {}
        self.current = None
        self.lock = threading.Lock()
        self._pw = None
        self._ctx = None
        self._ctx_visible = None
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()


    def enqueue(self, usernames, job=None):
        """job: {"mode": "quick"} = thông tin kênh + video mới nhất,
        {"mode": "scan", "limit": N, "since": ts, "until": ts} = cuộn kênh để lấy video
        (limit/since/until = 0 nghĩa là không giới hạn; cả 3 đều 0 = quét toàn bộ),
        {"mode": "videos", "ids": [...]} = cập nhật số liệu của từng video cụ thể."""
        job = normalize_job(job)
        added = 0
        with self.lock:
            running = self.current["username"] if self.current else None
            for u in usernames:
                key = u.lower()
                # Job video có hàng đợi riêng (khóa key#videos) để không đè job quét kênh.
                qkey = f"{key}#videos" if job["mode"] == "videos" else key
                prev = self.pending.get(qkey)
                new = job
                if job["mode"] == "videos" and prev:
                    new = {"mode": "videos", "ids": list(dict.fromkeys(prev["ids"] + job["ids"]))}
                # Job y hệt, hoặc job nhanh khi đã có job chờ: không xếp thêm.
                elif prev == job or (prev is not None and job["mode"] == "quick"):
                    continue
                if prev is None:
                    self.jobs.put(qkey)
                    if key != running:
                        db.set_status(key, "queued")
                self.pending[qkey] = new
                added += 1
        return added

    def status(self):
        with self.lock:
            return {
                "queue": len(self.pending) + (1 if self.current else 0),
                "current": dict(self.current) if self.current else None}


    def _run(self):
        while True:
            qkey = self.jobs.get()
            key = qkey.split("#")[0]
            with self.lock:
                job = self.pending.pop(qkey, None)
            if job is None or not db.channel_exists(key):
                continue
            with self.lock:
                self.current = {"username": key, "label": describe_job(job), "videos": 0,
                                "total": len(job.get("ids", [])), "started": time.time()}
            db.set_status(key, "running")
            try:
                self._execute(key, job)
            finally:
                with self.lock:
                    self.current = None
                    # Có job mới được xếp cho kênh này trong lúc đang chạy: trả về trạng thái chờ.
                    if key in self.pending or f"{key}#videos" in self.pending:
                        db.set_status(key, "queued")
            time.sleep(1.5)

    def _execute(self, key, job):
        """Chạy một job; lỗi tạm thời được thử lại, lỗi khác báo ngay như bản gốc."""
        attempts = len(self.RETRY_DELAYS) + 1
        for attempt in range(1, attempts + 1):
            try:
                if job["mode"] == "videos":
                    self._update_videos(key, job["ids"])
                else:
                    self._scrape(key, job)
                ch = db.get_channel(key)
                if ch and ch["status"] == "done":
                    db.record_scan(key, describe_job(job))
                return
            except Exception as e:
                traceback.print_exc()
                self._close_browser()
                if attempt < attempts and _is_transient(e):
                    db.set_status(
                        key, "running",
                        f"Lỗi tạm thời, sẽ thử lại lần {attempt + 1}/{attempts}: {_first_line(e)}")
                    time.sleep(self.RETRY_DELAYS[attempt - 1])
                    continue
                suffix = f" (đã thử {attempt} lần)" if attempt > 1 else ""
                db.set_status(key, "error", f"Lỗi: {e}{suffix}")
                return

    def _auto_refresh_loop(self):
        last = time.time()
        while True:
            time.sleep(30)
            minutes = int(db.get_setting("auto_refresh_minutes", "0") or 0)
            if minutes <= 0:
                last = time.time()
                continue
            if time.time() - last >= minutes * 60:
                last = time.time()
                self.enqueue(db.all_usernames(), {"mode": "quick"})


    def _browser(self):
        visible = db.get_setting("show_browser", "0") == "1"
        if self._ctx is not None and self._ctx_visible == visible:
            return self._ctx
        self._close_browser()
        self._pw = sync_playwright().start()
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-features=CalculateNativeWinOcclusion",
        ]
        if not visible:
            args.append("--window-position=-32000,-32000")

        errors = []
        profile_busy = False
        for channel in ("msedge", "chrome", None):
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(PROFILE_DIR), channel=channel, headless=False, args=args, locale="vi-VN",
                    viewport={"width": 1280, "height": 900})

                break
            except Exception as e:
                profile_busy = profile_busy or "existing browser session" in str(e) or "already in use" in str(e)
                errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0]}")
        else:
            self._close_browser()
            print("\n".join(errors))
            if profile_busy:
                raise ProfileBusyError(
                    f"Hồ sơ trình duyệt của tool đang bị một cửa sổ trình duyệt khác giữ ({PROFILE_DIR}). "
                    "Hãy tắt tool hoặc trình duyệt còn chạy với thư mục dữ liệu này rồi thử lại.")
            raise RuntimeError("Không mở được trình duyệt – hãy cài Microsoft Edge hoặc Google Chrome")
        self._ctx_visible = visible
        return self._ctx

    def _close_browser(self):
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = None


    def _scrape(self, key, job):
        ctx = self._browser()
        page = ctx.new_page()
        responses = []
        page.on("response", lambda r: responses.append(r) if "/api/post/item_list" in r.url else None)
        try:
            page.goto(f"https://www.tiktok.com/@{key}", wait_until="domcontentloaded", timeout=60000)
            raw = None
            for _ in range(20):
                raw = _evaluate_after_navigation(
                    page, "() => document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent")
                if raw:
                    break
                page.wait_for_timeout(500)
            if not raw:
                if self._has_captcha(page):
                    db.set_status(key, "error", "Bị captcha – bật 'Hiện trình duyệt' trong Cài đặt rồi giải captcha")
                else:
                    db.set_status(key, "error", "Không đọc được trang kênh")
                return

            scope = json.loads(raw).get("__DEFAULT_SCOPE__", {})
            detail = scope.get("webapp.user-detail", {})
            info = detail.get("userInfo") or {}
            user = info.get("user") or {}
            if not user.get("uniqueId"):
                code = detail.get("statusCode")
                msg = "Kênh không tồn tại hoặc bị khóa" if code in (10221, 10202) else f"Không lấy được kênh (mã {code})"
                db.set_status(key, "error", msg)
                return

            stats = {**(info.get("stats") or {}), **{k: v for k, v in (info.get("statsV2") or {}).items() if v not in (None, "")}}
            bio_link = (user.get("bioLink") or {}).get("link") or ""
            db.save_channel_info(key, {
                "unique_id": user.get("uniqueId"),
                "nickname": user.get("nickname"),
                "avatar": user.get("avatarMedium") or user.get("avatarThumb"),
                "verified": 1 if user.get("verified") else 0,
                "private": 1 if user.get("privateAccount") else 0,
                "sec_uid": user.get("secUid"),
                "followers": _int(stats.get("followerCount")),
                "following": _int(stats.get("followingCount")),
                "likes": _int(stats.get("heartCount") or stats.get("heart")),
                "video_count": _int(stats.get("videoCount")),
                "bio": user.get("signature") or "",
                "bio_link": bio_link,
                "created_at": _int(user.get("createTime")) or None,
            })

            if user.get("privateAccount"):
                db.finish_scan(key, [], full=False)
                db.set_status(key, "done", "Tài khoản riêng tư – không xem được video")
                return

            limit, since, until = job.get("limit", 0), job.get("since", 0), job.get("until", 0)
            video_count = _int(stats.get("videoCount"))
            items, seen = [], set()
            done_responses = 0
            idle = 0
            has_more = True
            tail_time = None

            def collect():
                nonlocal done_responses, has_more, tail_time
                new = 0
                while done_responses < len(responses):
                    r = responses[done_responses]
                    done_responses += 1
                    try:
                        data = r.json()
                    except Exception:
                        continue
                    batch = data.get("itemList") or []
                    for it in batch:
                        if it.get("id") and it["id"] not in seen:
                            seen.add(it["id"])
                            items.append(it)
                            new += 1
                    if batch:
                        tail_time = _int(batch[-1].get("createTime"))
                    has_more = bool(data.get("hasMore"))
                with self.lock:
                    if self.current:
                        self.current["videos"] = len(items)
                return new

            def enough():
                if limit and len(items) >= limit + MAX_PINNED:
                    return True
                return bool(since and tail_time and tail_time < since)

            # Chờ trang kênh tự gọi API danh sách video (tối đa 30 x 500ms).
            for _ in range(30):
                page.wait_for_timeout(500)
                collect()
                if items or (responses and not has_more):
                    break
            if not items and video_count and self._has_captcha(page):
                db.set_status(key, "error", "Bị captcha – bật 'Hiện trình duyệt' trong Cài đặt rồi giải captcha")
                return

            if job["mode"] == "scan":
                while has_more and idle < 10 and not enough():
                    _evaluate_after_navigation(page, "() => window.scrollTo(0, document.body.scrollHeight)")
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(1200)
                    idle = 0 if collect() else idle + 1
                    if self._has_captcha(page):
                        page.wait_for_timeout(3000)

            videos = sorted((_video_row(it, key) for it in items), key=lambda v: v["create_time"], reverse=True)
            if job["mode"] == "scan":
                if since:
                    videos = [v for v in videos if v["create_time"] >= since]
                if until:
                    videos = [v for v in videos if v["create_time"] <= until]
                if limit:
                    videos = videos[:limit]
            is_full = job["mode"] == "scan" and not (limit or since or until)
            db.finish_scan(key, videos, full=is_full and not has_more)

            if job["mode"] == "quick":
                note = ""
            elif has_more and not enough():
                note = f"{describe_job(job)}: mới lấy được {len(videos)} video – TikTok ngừng trả thêm, thử quét lại sau"
            elif is_full:
                note = ""
            else:
                note = f"{describe_job(job)}: {len(videos)} video"
            db.set_status(key, "done", note)
        finally:
            try:
                page.close()
            except Exception:
                pass


    def _update_videos(self, key, ids):
        ch = db.get_channel(key) or {}
        uid = ch.get("unique_id") or key

        page = self._browser().new_page()
        rows, missing = [], 0
        try:
            for n, vid in enumerate(ids, 1):
                item = None
                try:
                    page.goto(f"https://www.tiktok.com/@{uid}/video/{vid}", wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
                for _ in range(24):
                    try:
                        raw = page.evaluate(
                            "() => document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent")
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
                with self.lock:
                    if self.current:
                        self.current["videos"] = n
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

    @staticmethod
    def _has_captcha(page):
        try:
            return page.locator("#captcha-container, .captcha_verify_container, [class*='captcha']").count() > 0
        except Exception:
            return False


MAX_PINNED = 3


def normalize_job(job):
    job = job or {}
    if job.get("mode") == "quick":
        return {"mode": "quick"}
    if job.get("mode") == "videos":
        ids = [str(i) for i in (job.get("ids") or []) if str(i).isdigit()]
        return {"mode": "videos", "ids": list(dict.fromkeys(ids))}
    days = max(0, _int(job.get("days")))
    since, until = max(0, _int(job.get("since"))), max(0, _int(job.get("until")))
    if days:
        since, until = int(time.time()) - days * 86400, 0
    if since and until and since > until:
        since, until = until, since
    return {"mode": "scan", "limit": max(0, _int(job.get("limit"))), "days": days, "since": since, "until": until}


def describe_job(job):
    if job["mode"] == "quick":
        return "Cập nhật nhanh"
    if job["mode"] == "videos":
        return f"Cập nhật view {len(job['ids'])} video"
    fmt = lambda ts: time.strftime("%d/%m/%Y", time.localtime(ts))
    parts = []
    if job["limit"]:
        parts.append(f"{job['limit']} video gần nhất")
    if job["days"]:
        parts.append(f"{job['days']} ngày qua")
    elif job["since"] and job["until"]:
        parts.append(f"từ {fmt(job['since'])} đến {fmt(job['until'])}")
    elif job["since"]:
        parts.append(f"từ {fmt(job['since'])}")
    elif job["until"]:
        parts.append(f"đến {fmt(job['until'])}")
    return "Quét " + (", ".join(parts) if parts else "toàn bộ video")


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _video_detail(raw):
    try:
        detail = json.loads(raw).get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
    except ValueError:
        return None, None
    item = (detail.get("itemInfo") or {}).get("itemStruct")
    return (item if item and item.get("id") else None), detail.get("statusCode")


def _video_row(it, username):
    st = {**(it.get("stats") or {}), **{k: v for k, v in (it.get("statsV2") or {}).items() if v not in (None, "")}}
    video = it.get("video") or {}
    return {
        "id": it["id"],
        "username": username,
        "description": it.get("desc") or "",
        "create_time": _int(it.get("createTime")),
        "duration": _int(video.get("duration")),
        "cover": video.get("cover") or video.get("originCover") or "",
        "play": _int(st.get("playCount")),
        "digg": _int(st.get("diggCount")),
        "comment": _int(st.get("commentCount")),
        "share": _int(st.get("shareCount")),
        "collect": _int(st.get("collectCount")),
        "music": (it.get("music") or {}).get("title") or "",
        "is_ad": 1 if it.get("isAd") else 0,
    }
