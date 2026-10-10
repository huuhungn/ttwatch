import os
import shutil
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


if __name__ == "__main__":
    unittest.main()
