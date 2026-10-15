import os
import shutil
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ["TDK_DATA_DIR"])


class ParseInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys

        sys.path.insert(0, str(ROOT))
        from scraper import parse_input

        cls.parse_input = staticmethod(parse_input)

    def test_username_url_and_junk(self):
        found, invalid = self.parse_input("@Demo.User, https://www.tiktok.com/@Other_1\nnope!")
        self.assertEqual(found, ["demo.user", "other_1"])
        self.assertEqual(invalid, ["nope!"])

    def test_dedupes_same_channel(self):
        found, invalid = self.parse_input("demo.user @demo.user")
        self.assertEqual(found, ["demo.user"])
        self.assertEqual(invalid, [])

    def test_wrapped_and_trailing_punctuation(self):
        found, invalid = self.parse_input('(@Demo.User) "@other_1" @third! (https://www.tiktok.com/@Fourth_4).')
        self.assertEqual(found, ["demo.user", "other_1", "third", "fourth_4"])
        self.assertEqual(invalid, [])

    def test_uppercase_url(self):
        found, invalid = self.parse_input("HTTPS://WWW.TIKTOK.COM/@Demo.User")
        self.assertEqual(found, ["demo.user"])
        self.assertEqual(invalid, [])

    def test_zero_width_and_fullwidth_at(self):
        found, invalid = self.parse_input("@demo​.user ＠Other_1 ​third")
        self.assertEqual(found, ["demo.user", "other_1", "third"])
        self.assertEqual(invalid, [])

    def test_dedupes_across_noisy_forms(self):
        text = 'demo.user (@Demo.User) "@demo.user" @demo.user! ＠demo​.user HTTPS://WWW.TIKTOK.COM/@DEMO.USER'
        self.assertEqual(self.parse_input(text), (["demo.user"], []))

    def test_invalid_stays_invalid(self):
        found, invalid = self.parse_input("nope! (x) @a$b")
        self.assertEqual(found, [])
        self.assertEqual(invalid, ["nope!", "(x)", "@a$b"])

    def test_empty(self):
        self.assertEqual(self.parse_input("  \n,"), ([], []))


class SchemaTest(unittest.TestCase):
    def test_tables_and_channel_roundtrip(self):
        import db

        if DATA.exists():
            shutil.rmtree(DATA)
        db.init()
        added, existed = db.add_channels(["demo_user", "demo_user"])
        self.assertEqual(added, ["demo_user"])
        self.assertEqual(existed, ["demo_user"])
        db.save_channel_info("demo_user", {"followers": 10, "likes": 2, "video_count": 1})
        db.finish_scan(
            "demo_user",
            [
                {
                    "id": "v1",
                    "description": "hello",
                    "create_time": 1_700_000_000,
                    "duration": 5,
                    "cover": "",
                    "play": 100,
                    "digg": 4,
                    "comment": 1,
                    "share": 0,
                    "collect": 0,
                    "music": "",
                    "is_ad": 0,
                }
            ],
            full=True,
        )
        db.save_channel_info("demo_user", {"followers": 12, "likes": 3})
        db.finish_scan(
            "demo_user",
            [
                {
                    "id": "v1",
                    "description": "hello",
                    "create_time": 1_700_000_000,
                    "duration": 5,
                    "cover": "",
                    "play": 130,
                    "digg": 4,
                    "comment": 1,
                    "share": 0,
                    "collect": 0,
                    "music": "",
                    "is_ad": 0,
                }
            ],
            full=False,
        )
        row = next(item for item in db.list_channels() if item["username"] == "demo_user")
        self.assertEqual(row["total_views"], 130)
        self.assertEqual(row["d_followers"], 2)
        import sqlite3

        names = [
            row[0]
            for row in sqlite3.connect(db.DB_PATH).execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        self.assertEqual(names, ["channels", "settings", "snapshots", "videos"])


class _Response:
    def __init__(self, url, payload):
        self.url = url
        self._payload = payload

    def json(self):
        return self._payload


class _Mouse:
    def __init__(self):
        self.wheels = []

    def wheel(self, x, y):
        self.wheels.append((x, y))


class _Page:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.mouse = _Mouse()
        self._handler = None
        self.scrolls = 0
        self.closed = False

    def on(self, event, handler):
        self._handler = handler

    def goto(self, url, **kwargs):
        self._emit()

    def evaluate(self, script):
        if "scrollTo" in script:
            self.scrolls += 1
            self._emit()
            return None
        if "UNIVERSAL_DATA" in script:
            return (
                '{"__DEFAULT_SCOPE__":{"webapp.user-detail":{"userInfo":{"user":'
                '{"uniqueId":"demo","nickname":"Demo","privateAccount":false,"secUid":"s",'
                '"verified":false,"signature":"","createTime":1},"stats":{"followerCount":3,'
                '"followingCount":1,"heartCount":2,"videoCount":2}}}}}'
            )
        return None

    def wait_for_timeout(self, ms):
        return None

    def content(self):
        return "<html></html>"

    def close(self):
        self.closed = True

    def _emit(self):
        if self._payloads and self._handler:
            self._handler(self._payloads.pop(0))


class _Context:
    def __init__(self, page):
        self.pages = [page]


class ScrollLoopTest(unittest.TestCase):
    def test_scan_stops_when_has_more_is_false(self):
        import db as dbmod
        from scraper import Scraper

        scroll_data = DATA / "scroll"
        if scroll_data.exists():
            shutil.rmtree(scroll_data)
        scroll_data.mkdir(parents=True)
        dbmod.DB_PATH = scroll_data / "data.db"
        dbmod.init()
        dbmod.add_channels(["demo"])
        page = _Page(
            [
                _Response(
                    "https://www.tiktok.com/api/post/item_list?cursor=0",
                    {
                        "hasMore": False,
                        "itemList": [
                            {"id": "2", "desc": "new", "createTime": 200, "stats": {"playCount": 5}, "video": {}},
                            {"id": "1", "desc": "old", "createTime": 100, "stats": {"playCount": 9}, "video": {}},
                        ],
                    },
                )
            ]
        )
        scraper = Scraper.__new__(Scraper)
        scraper._browser = lambda: _Context(page)
        count = scraper._scrape("demo", {"mode": "scan"})
        self.assertEqual(count, 2)
        self.assertEqual(page.scrolls, 0)
        self.assertEqual(page.mouse.wheels, [])
        stored = dbmod.list_videos("demo")
        self.assertEqual([video["id"] for video in stored], ["2", "1"])


class _NavigatingPage(_Page):
    def __init__(self, payloads):
        super().__init__(payloads)
        self.navigations = 0
        self.load_waits = 0

    def evaluate(self, script):
        if "UNIVERSAL_DATA" in script and not self.navigations:
            self.navigations += 1
            raise RuntimeError(
                "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
            )
        return super().evaluate(script)

    def wait_for_load_state(self, state, timeout=None):
        self.load_waits += 1


class NavigationTest(unittest.TestCase):
    def test_scan_survives_navigation_during_evaluate(self):
        import db as dbmod
        from scraper import Scraper

        data = DATA / "navigation"
        if data.exists():
            shutil.rmtree(data)
        data.mkdir(parents=True)
        dbmod.DB_PATH = data / "data.db"
        dbmod.init()
        dbmod.add_channels(["demo"])
        page = _NavigatingPage(
            [
                _Response(
                    "https://www.tiktok.com/api/post/item_list?cursor=0",
                    {
                        "hasMore": False,
                        "itemList": [
                            {"id": "1", "desc": "one", "createTime": 100, "stats": {"playCount": 9}, "video": {}},
                        ],
                    },
                )
            ]
        )
        scraper = Scraper.__new__(Scraper)
        scraper._browser = lambda: _Context(page)
        count = scraper._scrape("demo", {"mode": "scan"})
        self.assertEqual(count, 1)
        self.assertEqual(page.navigations, 1)
        self.assertEqual(page.load_waits, 1)

    def test_other_evaluate_errors_still_raise(self):
        from scraper import _evaluate_after_navigation

        class Broken:
            def evaluate(self, script):
                raise RuntimeError("Target page, context or browser has been closed")

        with self.assertRaises(RuntimeError):
            _evaluate_after_navigation(Broken(), "() => 1")


class _Locator:
    def __init__(self, selector, html):
        self.selector = selector
        self.html = html

    def count(self):
        if "#captcha-container" in self.selector and 'id="captcha-container"' in self.html:
            return 1
        if "captcha_verify_container" in self.selector and "captcha_verify_container" in self.html:
            return 1
        if "[class*='captcha']" in self.selector and 'class="secsdk-captcha"' in self.html:
            return 1
        return 0


class _DetailPage:
    def __init__(self):
        self.urls = []
        self.html = "<html>captcha word only</html>"

    def goto(self, url, **kwargs):
        self.urls.append(url)

    def evaluate(self, script):
        if "UNIVERSAL_DATA" not in script:
            return None
        video_id = self.urls[-1].rsplit("/", 1)[-1]
        if video_id == "missing":
            return None
        return (
            '{"__DEFAULT_SCOPE__":{"webapp.video-detail":{"itemInfo":{"itemStruct":'
            '{"id":"%s","desc":"kept","createTime":300,"stats":{"playCount":7},"video":{}}}}}}'
            % video_id
        )

    def wait_for_timeout(self, ms):
        return None

    def close(self):
        self.closed = True

    def locator(self, selector):
        return _Locator(selector, self.html)


class UpdateVideosTest(unittest.TestCase):
    def test_updates_found_video_and_counts_missing(self):
        import db as dbmod
        from scraper import Scraper

        data = DATA / "update"
        if data.exists():
            shutil.rmtree(data)
        data.mkdir(parents=True)
        dbmod.DB_PATH = data / "data.db"
        dbmod.init()
        dbmod.add_channels(["demo"])
        page = _DetailPage()
        scraper = Scraper.__new__(Scraper)
        scraper._lock = threading.Lock()
        scraper._jobs = {"demo": {"videos": 0}}
        scraper._browser = lambda: type("Ctx", (), {"new_page": lambda self: page})()
        scraper._update_videos("demo", ["kept", "missing"])
        self.assertTrue(page.closed)
        self.assertEqual(scraper._jobs["demo"]["videos"], 2)
        stored = dbmod.list_videos("demo")
        self.assertEqual([video["id"] for video in stored], ["kept"])
        self.assertTrue(page.urls[0].endswith("/@demo/video/kept"))
        self.assertTrue(page.urls[1].endswith("/@demo/video/missing"))
        note = dbmod.get_channel("demo")["message"]
        self.assertIn("Cập nhật view 1 video", note)
        self.assertIn("1 video không lấy được", note)


class VideosJobTest(unittest.TestCase):
    def test_videos_mode_skips_channel_scrape(self):
        import queue
        from scraper import Scraper

        scraper = Scraper.__new__(Scraper)
        scraper._lock = threading.Lock()
        scraper._jobs = {"demo": {"status": "queued"}}
        scraper._queue = queue.Queue()
        calls = []
        scraper._update_videos = lambda key, ids: calls.append(("videos", key, ids))
        scraper._scrape = lambda key, job: calls.append(("scrape", key))
        scraper._queue.put(("demo", {"mode": "videos", "ids": ["1", "2"]}))
        worker = threading.Thread(target=scraper._run, daemon=True)
        worker.start()
        scraper._queue.join()
        self.assertEqual(calls, [("videos", "demo", ["1", "2"])])
        self.assertEqual(scraper._jobs["demo"]["status"], "done")


class CaptchaTest(unittest.TestCase):
    def test_word_in_html_is_not_a_widget(self):
        from scraper import _has_captcha

        page = _DetailPage()
        self.assertFalse(_has_captcha(page))
        page.html = '<div id="captcha-container"></div>'
        self.assertTrue(_has_captcha(page))


def _queue_scraper(name):
    """Scraper chạy hàng đợi thật nhưng trình duyệt giả, không chờ khi thử lại."""
    import queue

    import db as dbmod
    from scraper import Scraper

    data = DATA / name
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    dbmod.DB_PATH = data / "data.db"
    dbmod.init()
    scraper = Scraper.__new__(Scraper)
    scraper._lock = threading.Lock()
    scraper._jobs = {}
    scraper._queue = queue.Queue()
    scraper._context = None
    scraper._playwright = None
    scraper.RETRY_DELAYS = (0, 0)
    return scraper, dbmod


def _one_video_page():
    return _Page(
        [
            _Response(
                "https://www.tiktok.com/api/post/item_list?cursor=0",
                {"hasMore": False, "itemList": [{"id": "9", "createTime": 1, "stats": {"playCount": 1}, "video": {}}]},
            )
        ]
    )


class _CaptchaPage(_Page):
    def locator(self, selector):
        return _Locator(selector, '<div id="captcha-container"></div>')


class CaptchaQueueTest(unittest.TestCase):
    def test_captcha_marks_channel_and_queue_moves_on(self):
        scraper, dbmod = _queue_scraper("captcha-queue")
        dbmod.add_channels(["blocked", "ok"])
        pages = {"blocked": _CaptchaPage([]), "ok": _one_video_page()}
        order = []
        real_scrape = scraper._scrape

        def scrape(key, job):
            order.append(key)
            return real_scrape(key, job)

        scraper._scrape = scrape
        scraper._browser = lambda: _Context(pages[order[-1]])
        scraper.enqueue(["blocked", "ok"], {"mode": "quick"})
        threading.Thread(target=scraper._run, daemon=True).start()
        scraper._queue.join()

        # Hành vi hiện tại: captcha không dừng hàng đợi, kênh sau vẫn được quét
        # và kênh bị captcha không bị quét lại tự động.
        self.assertEqual(order, ["blocked", "ok"])
        blocked = dbmod.get_channel("blocked")
        self.assertEqual(blocked["status"], "error")
        self.assertIn("captcha", blocked["message"])
        self.assertIsNone(blocked["last_scan_at"])
        self.assertEqual(dbmod.get_channel("ok")["status"], "done")


class RetryTest(unittest.TestCase):
    def _run_one(self, name, failures):
        scraper, dbmod = _queue_scraper(name)
        dbmod.add_channels(["demo"])
        calls = []

        def scrape(key, job):
            calls.append(key)
            if len(calls) <= len(failures):
                raise failures[len(calls) - 1]
            return 3

        scraper._scrape = scrape
        scraper.enqueue(["demo"], {"mode": "scan", "limit": 3})
        threading.Thread(target=scraper._run, daemon=True).start()
        scraper._queue.join()
        return calls, dbmod.get_channel("demo"), scraper

    def test_transient_error_is_retried_then_succeeds(self):
        calls, channel, scraper = self._run_one(
            "retry-ok", [RuntimeError("Timeout 30000ms exceeded")]
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(channel["status"], "done")
        self.assertEqual(channel["last_scan_label"], "Quét 3 video gần nhất")
        self.assertIsNotNone(channel["last_scan_at"])
        self.assertEqual(scraper._jobs["demo"]["status"], "done")

    def test_transient_error_gives_up_after_three_attempts(self):
        errors = [RuntimeError("net::ERR_CONNECTION_RESET")] * 3
        calls, channel, _ = self._run_one("retry-fail", errors)
        self.assertEqual(len(calls), 3)
        self.assertEqual(channel["status"], "error")
        self.assertIn("đã thử 3 lần", channel["message"])

    def test_permanent_and_captcha_errors_are_not_retried(self):
        from scraper import CAPTCHA_MESSAGE, CaptchaError

        for name, error in (
            ("no-retry-missing", RuntimeError("Kênh không tồn tại")),
            ("no-retry-captcha", CaptchaError(CAPTCHA_MESSAGE)),
        ):
            calls, channel, _ = self._run_one(name, [error])
            self.assertEqual(len(calls), 1, name)
            self.assertEqual(channel["status"], "error", name)
            self.assertNotIn("đã thử", channel["message"], name)


class DescribeJobTest(unittest.TestCase):
    def test_labels(self):
        from scraper import describe_job

        self.assertEqual(describe_job({"mode": "quick"}), "Cập nhật nhanh")
        self.assertEqual(describe_job({"mode": "scan"}), "Quét toàn bộ video")
        self.assertEqual(describe_job({"mode": "scan", "days": 7}), "Quét 7 ngày qua")
        self.assertEqual(describe_job({"mode": "videos", "ids": ["1", "2"]}), "Cập nhật view 2 video")


class InstanceLockTest(unittest.TestCase):
    def test_second_app_on_same_data_dir_is_refused(self):
        import subprocess
        import sys

        import instance_lock

        data = DATA / "lock"
        if data.exists():
            shutil.rmtree(data)
        held = instance_lock.acquire(data)
        try:
            probe = (
                "import sys, instance_lock\n"
                "try:\n"
                "    instance_lock.acquire(sys.argv[1])\n"
                "except instance_lock.AlreadyRunning as exc:\n"
                "    print('busy', exc)\n"
                "else:\n"
                "    print('acquired')\n"
            )
            out = subprocess.run(
                [sys.executable, "-c", probe, str(data)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            ).stdout
            self.assertTrue(out.startswith("busy"), out)
            self.assertIn(f"PID {os.getpid()}", out)
        finally:
            held.release()
        again = instance_lock.acquire(data)
        again.release()
        self.assertFalse((data / instance_lock.PID_NAME).exists())

    def test_old_database_gets_new_columns(self):
        import sqlite3

        import db as dbmod

        data = DATA / "migrate"
        if data.exists():
            shutil.rmtree(data)
        data.mkdir(parents=True)
        path = data / "data.db"
        old = sqlite3.connect(path)
        legacy_schema = dbmod.SCHEMA.replace(
            ",\n    last_scan_at INTEGER,\n    last_scan_label TEXT DEFAULT ''", ""
        )
        self.assertNotIn("last_scan_at", legacy_schema)
        old.executescript(legacy_schema)
        old.execute("INSERT INTO channels(username) VALUES('legacy')")
        old.commit()
        old.close()
        dbmod.DB_PATH = path
        dbmod.init()
        dbmod.init()
        columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(channels)")}
        self.assertTrue({"last_scan_at", "last_scan_label"} <= columns)
        self.assertEqual(dbmod.get_channel("legacy")["username"], "legacy")


class ExportCsvTest(unittest.TestCase):
    def _client(self, name):
        import sys

        sys.path.insert(0, str(ROOT))
        import app as appmod
        import db as dbmod
        from fastapi.testclient import TestClient

        # Nhả khóa dữ liệu của app để các test khác còn xóa được thư mục DATA.
        appmod._instance.release()
        data = DATA / name
        if data.exists():
            shutil.rmtree(data)
        data.mkdir(parents=True)
        dbmod.DB_PATH = data / "data.db"
        dbmod.init()
        dbmod.add_channels(["demo"])
        return TestClient(appmod.app), dbmod

    def test_csv_matches_xlsx_and_neutralises_formulas(self):
        import csv
        import io

        from openpyxl import load_workbook

        client, dbmod = self._client("export_csv")
        base = {"cover": "", "duration": 5, "digg": 4, "comment": 3, "share": 2, "collect": 1}
        videos = [
            {"id": "v1", "description": "=SUM(A1)", "create_time": 1_700_000_001, "play": 100, "music": "@mix"},
            {"id": "v2", "description": "Xin chào, \"Việt\"\nNam", "create_time": 1_700_000_002, "play": -7, "music": "-x"},
            {"id": "v3", "description": "+1 ok", "create_time": 1_700_000_003, "play": 0, "music": ""},
        ]
        dbmod.finish_scan("demo", [{**base, **video} for video in videos], full=True)

        res = client.get("/api/export/videos/demo.csv")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["content-type"].startswith("text/csv"))
        self.assertEqual(res.headers["content-disposition"], "attachment; filename=demo.csv")
        self.assertTrue(res.content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"), newline="")))

        sheet = load_workbook(io.BytesIO(client.get("/api/export/videos/demo.xlsx").content)).active
        xlsx = [[cell.value for cell in row] for row in sheet.iter_rows()]
        self.assertEqual(rows[0], xlsx[0])
        self.assertEqual([row[0] for row in rows[1:]], ["v3", "v2", "v1"])
        self.assertEqual([row[0] for row in rows[1:]], [row[0] for row in xlsx[1:]])
        by_id = {row[0]: row for row in rows[1:]}
        self.assertEqual(by_id["v1"][1], "'=SUM(A1)")
        self.assertEqual(by_id["v1"][9], "'@mix")
        self.assertEqual(by_id["v2"][1], "Xin chào, \"Việt\"\nNam")
        self.assertEqual(by_id["v2"][9], "'-x")
        self.assertEqual(by_id["v2"][4], "-7")
        self.assertEqual(by_id["v3"][1], "'+1 ok")
        self.assertEqual(by_id["v3"][9], "")

    def test_no_videos_returns_only_header(self):
        import csv
        import io

        client, _ = self._client("export_csv_empty")
        res = client.get("/api/export/videos/nobody.csv")
        self.assertEqual(res.status_code, 200)
        rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"), newline="")))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:3], ["id", "description", "create_time"])


if __name__ == "__main__":
    unittest.main()
