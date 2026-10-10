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


if __name__ == "__main__":
    unittest.main()
