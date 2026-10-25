import csv
import io
import os
import sqlite3
import time
import unittest
from datetime import datetime

from test_core import _fresh_db, _make_scraper, _video

DAY = 86400
NOW = 1_800_000_000


def _snap(db, key, ts, followers, likes=0, videos=0, views=0):
    with db._conn() as c:
        c.execute(
            "INSERT INTO snapshots(username, ts, followers, likes, video_count, total_views) VALUES(?,?,?,?,?,?)",
            (key, ts, followers, likes, videos, views),
        )


def _client(name):
    import app as appmod
    from fastapi.testclient import TestClient

    db = _fresh_db(name)
    appmod.scraper = _make_scraper()
    return TestClient(appmod.app), db


class HistoryTest(unittest.TestCase):
    def test_history_window_order_and_downsample(self):
        import insights

        db = _fresh_db("hist")
        db.add_channels(["demo"])
        with db._conn() as c:
            c.executemany(
                "INSERT INTO snapshots(username, ts, followers, likes, video_count, total_views) VALUES(?,?,?,0,0,0)",
                [("demo", NOW - (2000 - i) * 3600, 1000 + i) for i in range(2000)])
        full = insights.history("demo", now=NOW)
        self.assertLessEqual(len(full), insights.MAX_POINTS + 1)
        self.assertEqual(full[-1]["followers"], 2999)
        self.assertEqual(full[0]["followers"], 1000)
        self.assertEqual([p["ts"] for p in full], sorted(p["ts"] for p in full))
        week = insights.history("DEMO", days=7, now=NOW)
        self.assertEqual(len(week), 7 * 24)
        self.assertTrue(all(p["ts"] >= NOW - 7 * DAY for p in week))

    def test_compare_skips_unknown_channels_and_bad_metric(self):
        import insights

        db = _fresh_db("compare")
        db.add_channels(["a", "b"])
        _snap(db, "a", NOW - 100, 10, views=5)
        _snap(db, "b", NOW - 100, 20, views=7)
        out = insights.compare(["a", "b", "ghost"], "followers", now=NOW)
        self.assertEqual(set(out["series"]), {"a", "b"})
        self.assertEqual(out["series"]["b"], [[NOW - 100, 20]])
        self.assertEqual(insights.compare(["a"], "nope")["metric"], "followers")
        self.assertEqual(insights.compare(["a"], "total_views", now=NOW)["series"]["a"], [[NOW - 100, 5]])


class SparklineTest(unittest.TestCase):
    def test_one_query_for_all_channels_and_skips_single_points(self):
        import insights

        db = _fresh_db("spark")
        db.add_channels(["a", "b", "c"])
        for i in range(100):
            _snap(db, "a", NOW - (100 - i) * 600, 100 + i)
        _snap(db, "b", NOW - 100, 5)  # a single point: no line can be drawn
        _snap(db, "c", NOW - 40 * DAY, 1)
        _snap(db, "c", NOW - 39 * DAY, 2)  # outside the 30-day window
        out = insights.sparklines(30, points=24, now=NOW)
        self.assertEqual(set(out), {"a"})
        self.assertLessEqual(len(out["a"]), 25)
        self.assertEqual(out["a"][0], 100)
        self.assertEqual(out["a"][-1], 199)

    def test_endpoint(self):
        client, db = _client("api-spark")
        db.add_channels(["a"])
        now = int(time.time())
        _snap(db, "a", now - 200, 1)
        _snap(db, "a", now - 100, 2)
        self.assertEqual(client.get("/api/sparklines?days=7").json(), {"a": [1, 2]})


class OverviewTest(unittest.TestCase):
    def setUp(self):
        import insights

        self.insights = insights
        self.db = _fresh_db("overview")
        self.db.add_channels(["grow", "flat", "new", "broken", "old"])
        db = self.db
        # grow: 1000 → 1500 over 7 days; the 30-day baseline is 800.
        _snap(db, "grow", NOW - 29 * DAY, 800, views=100)
        _snap(db, "grow", NOW - 8 * DAY, 1000, views=200)
        _snap(db, "grow", NOW - 3600, 1500, views=900)
        _snap(db, "flat", NOW - 8 * DAY, 50, views=10)
        _snap(db, "flat", NOW - 3600, 50, views=10)
        _snap(db, "new", NOW - 3600, 5, views=1)  # only one snapshot: no delta
        with db._conn() as c:
            c.execute("UPDATE channels SET followers=1500, updated_at=?, status='done' WHERE username='grow'", (NOW - 3600,))
            c.execute("UPDATE channels SET followers=50, updated_at=?, status='done' WHERE username='flat'", (NOW - 3600,))
            c.execute("UPDATE channels SET followers=5, updated_at=?, status='done' WHERE username='new'", (NOW - 3600,))
            c.execute("UPDATE channels SET status='error', message='Kênh không tồn tại', updated_at=? WHERE username='broken'", (NOW - 5 * DAY,))
            c.execute("UPDATE channels SET status='done', updated_at=? WHERE username='old'", (NOW - 10 * DAY,))
        with db._conn() as c:
            c.execute("INSERT INTO videos(id, username, create_time, play, digg, comment, share, collect, updated_at) "
                      "VALUES('v1','grow',?,5000,0,0,0,0,?)", (NOW - 2 * DAY, NOW))

    def test_totals_and_lists(self):
        o = self.insights.overview(now=NOW)
        t = o["totals"]
        self.assertEqual(t["channels"], 5)
        self.assertEqual(t["followers"], 1555)
        self.assertEqual(t["errors"], 1)
        self.assertEqual([c["username"] for c in o["errors"]], ["broken"])
        self.assertEqual(o["stale"][0]["username"], "old")
        self.assertEqual([v["id"] for v in o["top_videos"]], ["v1"])

    def test_gainers_windows(self):
        g = self.insights.overview(now=NOW)["gainers"]
        d7 = {r["username"]: r for r in g["d7"]["followers"]}
        self.assertEqual(d7["grow"]["delta"], 500)
        self.assertFalse(d7["grow"]["partial"])
        self.assertEqual(d7["flat"]["delta"], 0)
        self.assertNotIn("new", d7)
        d30 = {r["username"]: r for r in g["d30"]["followers"]}
        self.assertEqual(d30["grow"]["delta"], 700)
        self.assertEqual(g["d7"]["followers"][0]["username"], "grow")
        # 1-day window: the previous snapshot is 8 days old and is still used as the baseline.
        d1 = {r["username"]: r for r in g["d1"]["followers"]}
        self.assertEqual(d1["grow"]["delta"], 500)

    def test_partial_window_marks_young_channels(self):
        db = _fresh_db("overview-partial")
        db.add_channels(["young"])
        _snap(db, "young", NOW - 2 * DAY, 10)
        _snap(db, "young", NOW - 3600, 40)
        row = self.insights.overview(now=NOW)["gainers"]["d30"]["followers"][0]
        self.assertEqual((row["delta"], row["partial"]), (30, True))

    def test_series_is_cumulative_and_carries_forward(self):
        db = _fresh_db("overview-series")
        db.add_channels(["a", "b"])
        _snap(db, "a", NOW - 3 * DAY, 100)
        _snap(db, "b", NOW - 2 * DAY, 10)
        _snap(db, "a", NOW - 1 * DAY, 150)
        s = self.insights.overview(now=NOW)["series"]
        self.assertEqual([p["followers"] for p in s], [100, 110, 160])

    def test_empty_database(self):
        _fresh_db("overview-empty")
        o = self.insights.overview(now=NOW)
        self.assertEqual(o["totals"]["channels"], 0)
        self.assertEqual(o["series"], [])
        self.assertEqual(o["gainers"]["d7"], {"followers": [], "views": []})


class ChannelInsightsTest(unittest.TestCase):
    def test_distribution_heatmap_and_outperformers(self):
        import insights

        db = _fresh_db("insights")
        db.add_channels(["demo"])
        base = int(datetime(2026, 10, 12, 20, 0).timestamp())  # Monday 20:00 machine local time
        plays = [500, 800, 900, 1000, 1200, 50_000]
        videos = [_video(f"v{i}", create_time=base + i * 7 * DAY, play=p) for i, p in enumerate(plays)]
        db.finish_scan("demo", videos, full=False)
        out = insights.channel_insights("demo", now=base + 6 * 7 * DAY)
        self.assertEqual(out["videos"], 6)
        dist = {d["label"]: d["count"] for d in out["distribution"]}
        self.assertEqual(dist["<1k"], 3)
        self.assertEqual(dist["1k–10k"], 2)
        self.assertEqual(dist["10k–100k"], 1)
        self.assertEqual(out["views"]["median"], 950)
        self.assertEqual(out["views"]["max"], 50_000)
        self.assertEqual(out["heatmap"][0][20]["count"], 6)
        self.assertEqual(out["best_slot"]["weekday"], 0)
        self.assertEqual(out["best_slot"]["hour"], 20)
        self.assertEqual([v["id"] for v in out["outperformers"]], ["v5"])
        self.assertEqual(out["top"][0]["id"], "v5")
        self.assertEqual(sum(w["posts"] for w in out["weekly"]), 6)
        self.assertEqual(len(out["weekly"]), 12)

    def test_few_videos_have_no_outperformers_and_empty_is_safe(self):
        import insights

        db = _fresh_db("insights-few")
        db.add_channels(["demo", "none"])
        db.finish_scan("demo", [_video("a", play=10), _video("b", play=1000)], full=False)
        out = insights.channel_insights("demo")
        self.assertEqual(out["outperformers"], [])
        empty = insights.channel_insights("none")
        self.assertTrue(empty["empty"])
        self.assertEqual(len(empty["heatmap"]), 7)
        self.assertEqual(empty["hashtags"], [])
        self.assertEqual([d["count"] for d in empty["durations"]], [0] * 5)

    def test_hashtags_and_durations(self):
        import insights

        db = _fresh_db("insights-tags")
        db.add_channels(["demo"])
        rows = [("#Mèo #meo #chó", 10, 100), ("#mèo vui", 20, 300), ("#mèo", 45, 900),
                ("#chó", 90, 50), ("không tag", 0, 70), ("#một", 400, 10)]
        db.finish_scan("demo", [_video(f"v{i}", description=d, duration=s, play=p)
                                for i, (d, s, p) in enumerate(rows)], full=False)
        out = insights.channel_insights("demo")
        tags = {t["tag"]: t for t in out["hashtags"]}
        # Case-insensitive, Vietnamese letters kept, counted once per video, single-use tags dropped.
        self.assertEqual(set(tags), {"mèo", "chó"})
        self.assertEqual(tags["mèo"]["count"], 3)
        self.assertEqual(tags["mèo"]["median_views"], 300)
        self.assertEqual(out["hashtags"][0]["tag"], "mèo")
        self.assertEqual(tags["mèo"]["lift"], round(300 / out["views"]["median"], 2))
        dur = {d["label"]: (d["count"], d["median_views"]) for d in out["durations"]}
        self.assertEqual(dur["<15s"], (1, 100))
        self.assertEqual(dur["15–30s"], (1, 300))
        self.assertEqual(dur["30–60s"], (1, 900))
        self.assertEqual(dur["1–3 phút"], (1, 50))
        self.assertEqual(dur["≥3 phút"], (1, 10))  # the 0-second row is left out


class AlertsTest(unittest.TestCase):
    def _channel(self, name):
        db = _fresh_db(name)
        db.add_channels(["demo"])
        return db

    def test_no_alert_on_first_scan(self):
        import insights

        db = self._channel("alert-first")
        db.save_channel_info("demo", {"followers": 100})
        db.finish_scan("demo", [_video("a")], full=False)
        self.assertEqual(insights.check_alerts("demo"), [])

    def test_follower_jump_and_new_video(self):
        import insights

        db = self._channel("alert-jump")
        db.save_channel_info("demo", {"followers": 1000})
        db.finish_scan("demo", [_video("a", create_time=int(time.time()) - 5000)], full=False)
        time.sleep(1.1)
        db.save_channel_info("demo", {"followers": 1100})
        db.finish_scan("demo", [_video("a", create_time=int(time.time()) - 5000),
                                _video("b", create_time=int(time.time()) - 60, description="video mới")], full=False)
        kinds = {a["kind"]: a["text"] for a in insights.check_alerts("demo")}
        self.assertIn("followers", kinds)
        self.assertIn("tăng 10.0% follow", kinds["followers"])
        self.assertIn("1.000 → 1.100", kinds["followers"])
        self.assertIn("1 video mới: video mới", kinds["new_video"])
        listing = insights.list_alerts()
        self.assertEqual(listing["unread"], 2)
        insights.mark_alerts_read([listing["alerts"][0]["id"]])
        self.assertEqual(insights.list_alerts()["unread"], 1)
        insights.mark_alerts_read()
        self.assertEqual(insights.list_alerts(unread_only=True)["alerts"], [])

    def test_viral_video_alert_fires_once_when_crossing(self):
        import insights

        db = self._channel("alert-viral")
        db.set_settings({"alert_new_video": "0"})
        now = int(time.time())
        base = [_video(f"o{i}", create_time=now - 40 * 86400, play=1000) for i in range(5)]
        db.save_channel_info("demo", {"followers": 1000})
        db.finish_scan("demo", base + [_video("hot", create_time=now - 3600, play=1500, description="clip hot")],
                       full=False)
        time.sleep(1.1)
        db.finish_scan("demo", base + [_video("hot", create_time=now - 3600, play=50000, description="clip hot")],
                       full=False)
        made = insights.check_alerts("demo")
        self.assertEqual([a["kind"] for a in made], ["viral"])
        self.assertIn("clip hot", made[0]["text"])
        self.assertIn("50.000 view", made[0]["text"])
        # Already above the bar on the previous scan: no repeat.
        time.sleep(1.1)
        db.finish_scan("demo", base + [_video("hot", create_time=now - 3600, play=60000)], full=False)
        self.assertEqual(insights.check_alerts("demo"), [])
        # Old videos never count, and 0 turns the alert off.
        time.sleep(1.1)
        db.finish_scan("demo", [_video("o0", create_time=now - 40 * 86400, play=10 ** 6)] + base[1:], full=False)
        self.assertEqual(insights.check_alerts("demo"), [])
        db.set_settings({"alert_viral_x": "0"})
        time.sleep(1.1)
        db.finish_scan("demo", base + [_video("new", create_time=now - 60, play=90000)], full=False)
        self.assertEqual(insights.check_alerts("demo"), [])

    def test_below_threshold_and_disabled(self):
        import insights

        db = self._channel("alert-quiet")
        db.save_channel_info("demo", {"followers": 1000})
        db.finish_scan("demo", [], full=False)
        time.sleep(1.1)
        db.save_channel_info("demo", {"followers": 1010})
        db.finish_scan("demo", [], full=False)
        self.assertEqual(insights.check_alerts("demo"), [])
        db.set_settings({"alert_follow_pct": "0.5"})
        self.assertEqual([a["kind"] for a in insights.check_alerts("demo")], ["followers"])
        db.set_settings({"alerts_enabled": "0"})
        self.assertEqual(insights.check_alerts("demo"), [])

    def test_tray_notification_only_when_tray_is_running(self):
        import sys
        import types

        import scraper

        sent = []
        scraper._notify_tray([{"kind": "followers", "text": "x"}])  # no tray yet: no error
        fake = types.ModuleType("tray")
        fake.notify = lambda msg, title=None: sent.append((msg, title))
        sys.modules["tray"] = fake
        try:
            scraper._notify_tray([])
            scraper._notify_tray([{"kind": "a", "text": "một"}, {"kind": "b", "text": "hai"}])
        finally:
            del sys.modules["tray"]
        self.assertEqual(sent, [("một\nhai", "Cảnh báo kênh TikTok")])

    def test_list_is_newest_first_by_time_not_insertion(self):
        import insights

        self._channel("alert-order")
        insights.add_alert("demo", "x", "cũ", ts=1000)
        insights.add_alert("demo", "x", "mới", ts=5000)
        insights.add_alert("demo", "x", "giữa", ts=3000)
        self.assertEqual([a["text"] for a in insights.list_alerts()["alerts"]], ["mới", "giữa", "cũ"])

    def test_table_is_capped(self):
        import insights

        db = self._channel("alert-cap")
        for i in range(520):
            insights.add_alert("demo", "x", str(i))
        with db._conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 500)


class ViewsAndAutoTest(unittest.TestCase):
    def test_views_roundtrip_with_unicode(self):
        import insights

        _fresh_db("views")
        insights.save_view("Kênh tăng nhanh", {"sort": "d_followers", "dir": -1, "group": "A"})
        insights.save_view("Tất cả", {})
        names = [v["name"] for v in insights.list_views()]
        self.assertEqual(names, sorted(["Kênh tăng nhanh", "Tất cả"]))
        self.assertEqual(next(v for v in insights.list_views() if v["name"] == "Kênh tăng nhanh")["data"]["dir"], -1)
        insights.delete_view("Tất cả")
        self.assertEqual([v["name"] for v in insights.list_views()], ["Kênh tăng nhanh"])
        with self.assertRaises(ValueError):
            insights.save_view("   ", {})

    def test_views_do_not_leak_into_settings(self):
        import insights

        db = _fresh_db("views-settings")
        insights.save_view("x", {"a": 1})
        self.assertNotIn("view:x", db.get_settings())

    def test_quiet_hours(self):
        from insights import in_quiet_hours as q

        self.assertTrue(q(23, "22", "7"))
        self.assertTrue(q(3, "22", "7"))
        self.assertFalse(q(12, "22", "7"))
        self.assertTrue(q(9, "9", "17"))
        self.assertFalse(q(17, "9", "17"))
        self.assertFalse(q(5, "", ""))
        self.assertFalse(q(5, "8", "8"))
        self.assertFalse(q(5, "x", "y"))

    def test_auto_job(self):
        from insights import auto_job

        self.assertEqual(auto_job("quick"), {"mode": "quick"})
        self.assertEqual(auto_job("scan10"), {"mode": "scan", "limit": 10})
        self.assertEqual(auto_job("???"), {"mode": "quick"})


class ApiTest(unittest.TestCase):
    def test_history_insights_compare_overview(self):
        client, db = _client("api-insights")
        db.add_channels(["demo", "other"])
        _snap(db, "demo", int(time.time()) - 100, 10, views=3)
        db.finish_scan("demo", [_video("a", play=10)], full=False)
        self.assertEqual(len(client.get("/api/channels/DEMO/history").json()["points"]), 2)
        self.assertEqual(client.get("/api/channels/ghost/history").status_code, 404)
        self.assertEqual(client.get("/api/channels/demo/insights").json()["videos"], 1)
        self.assertEqual(client.get("/api/channels/ghost/insights").status_code, 404)
        cmp = client.get("/api/compare?usernames=demo,other,ghost&metric=total_views").json()
        self.assertEqual(set(cmp["series"]), {"demo", "other"})
        self.assertEqual(client.get("/api/overview").json()["totals"]["channels"], 2)

    def test_channels_reports_interrupted(self):
        client, db = _client("api-interrupted")
        db.add_channels(["demo"])
        db.set_status("demo", "running")
        db.init()
        self.assertEqual(client.get("/api/channels").json()["interrupted"], 1)

    def test_alerts_and_views_endpoints(self):
        import insights

        client, db = _client("api-alerts")
        insights.add_alert("demo", "followers", "x")
        self.assertEqual(client.get("/api/alerts").json()["unread"], 1)
        self.assertEqual(client.post("/api/alerts/read", json={}).json()["unread"], 0)
        res = client.post("/api/views", json={"name": "Của tôi", "data": {"q": "abc"}})
        self.assertEqual(res.json()["views"][0]["data"], {"q": "abc"})
        self.assertEqual(client.post("/api/views", json={"name": " "}).status_code, 400)
        self.assertEqual(client.post("/api/views/delete", json={"name": "Của tôi"}).json(), {"views": []})

    def test_import_plain_and_csv_with_groups(self):
        client, db = _client("api-import")
        plain = client.post("/api/import/channels", json={"text": "@one two! https://www.tiktok.com/@three"}).json()
        self.assertEqual(plain["added"], ["one", "three"])
        self.assertEqual(plain["invalid"], ["two!"])
        text = "username,group,note\n@four,Nhóm A,ghi chú 4\nfive,,\none,Nhóm B,\nbad!,,\n"
        res = client.post("/api/import/channels", json={"text": text}).json()
        self.assertEqual(res["added"], ["four", "five"])
        self.assertEqual(res["existed"], ["one"])
        self.assertEqual(res["invalid"], ["bad!"])
        self.assertEqual(res["meta"], 2)
        self.assertEqual(db.get_channel("four")["group_name"], "Nhóm A")
        self.assertEqual(db.get_channel("four")["note"], "ghi chú 4")
        self.assertEqual(db.get_channel("one")["group_name"], "Nhóm B")
        self.assertEqual(db.get_channel("five")["group_name"], "")

    def test_backup_download_is_a_valid_database(self):
        client, db = _client("api-backup")
        db.add_channels(["demo"])
        res = client.get("/api/export/backup")
        self.assertEqual(res.status_code, 200)
        self.assertRegex(res.headers["content-disposition"], r"ttwatch-backup-\d{8}_\d{4}\.db")
        path = os.path.join(os.environ["TDK_DATA_DIR"], "dl.db")
        with open(path, "wb") as f:
            f.write(res.content)
        con = sqlite3.connect(path)
        try:
            self.assertEqual(con.execute("SELECT username FROM channels").fetchall(), [("demo",)])
        finally:
            con.close()
        names = [b["name"] for b in client.get("/api/backups").json()["backups"]]
        self.assertIsInstance(names, list)

    def test_history_csv_export(self):
        client, db = _client("api-history-csv")
        db.add_channels(["demo"])
        _snap(db, "demo", NOW, 12, 3, 1, 99)
        res = client.get("/api/export/history/demo.csv")
        rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:2], ["Thời điểm", "Follow"])
        self.assertEqual(rows[1][1:], ["12", "3", "1", "99"])
        self.assertEqual(client.get("/api/export/history/ghost.csv").status_code, 404)


if __name__ == "__main__":
    unittest.main()
