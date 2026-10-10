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


if __name__ == "__main__":
    unittest.main()
