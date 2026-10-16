"""Time the aggregate queries on large synthetic data (no network)."""
import time
import unittest

from test_core import _fresh_db

CHANNELS, VIDEOS, SNAPSHOTS = 300, 200, 60
NOW = int(time.time())


class LargeDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = _fresh_db("perf")
        with cls.db._conn() as c:
            c.executemany(
                "INSERT INTO channels(username, unique_id, nickname, followers, likes, video_count, status, added_at, updated_at)"
                " VALUES(?,?,?,?,?,?,'done',?,?)",
                [(f"ch{i:04d}", f"ch{i:04d}", f"Kênh {i}", 1000 + i, 5000 + i, VIDEOS, NOW - i, NOW - 3600) for i in range(CHANNELS)],
            )
            c.executemany(
                "INSERT INTO videos(id, username, description, create_time, duration, cover, play, digg, comment, share,"
                " collect, music, is_ad, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
                [(f"v{i}-{j}", f"ch{i:04d}", f"video {j}", NOW - j * 36000, 10, "", (j * 37) % 5000, j % 90, 3, 2, 1, "", NOW)
                 for i in range(CHANNELS) for j in range(VIDEOS)],
            )
            c.executemany(
                "INSERT INTO snapshots(username, ts, followers, likes, video_count, total_views) VALUES(?,?,?,?,?,?)",
                [(f"ch{i:04d}", NOW - (SNAPSHOTS - k) * 3600 * 12, 1000 + i + k, 5000 + k, VIDEOS, 100000 + k * 10)
                 for i in range(CHANNELS) for k in range(SNAPSHOTS)],
            )

    def timed(self, fn, *args):
        start = time.perf_counter()
        out = fn(*args)
        return time.perf_counter() - start, out

    def test_queries_stay_fast(self):
        import insights

        t_list, rows = self.timed(self.db.list_channels)
        self.assertEqual(len(rows), CHANNELS)
        t_over, over = self.timed(insights.overview)
        self.assertEqual(over["totals"]["channels"], CHANNELS)
        t_spark, spark = self.timed(insights.sparklines)
        self.assertEqual(len(spark), CHANNELS)
        t_ins, ins = self.timed(insights.channel_insights, "ch0001")
        self.assertEqual(ins["videos"], VIDEOS)
        t_hist, hist = self.timed(insights.history, "ch0001")
        self.assertEqual(len(hist), SNAPSHOTS)
        print(f"\n[perf] list_channels {t_list*1000:.0f} ms, overview {t_over*1000:.0f} ms, "
              f"sparklines {t_spark*1000:.0f} ms, insights {t_ins*1000:.0f} ms, history {t_hist*1000:.0f} ms")
        # Generous threshold (slow machine, slow disk); measured at roughly 30-70 ms.
        for name, t in (("list_channels", t_list), ("overview", t_over), ("sparklines", t_spark), ("insights", t_ins)):
            self.assertLess(t, 1.0, name)


if __name__ == "__main__":
    unittest.main()
