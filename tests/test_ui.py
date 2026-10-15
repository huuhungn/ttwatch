"""Kiểm thử giao diện thật bằng trình duyệt, không gọi TikTok.

App chạy bằng uvicorn trên cổng ngẫu nhiên với DB mẫu và scraper giả (không luồng nền,
không trình duyệt). Bỏ qua nếu máy không có Chrome/Edge/Chromium của Playwright.
Ảnh chụp lưu ở docs/screens/ để xem nhanh sau mỗi lần chạy.
"""
import socket
import threading
import time
import unittest

from test_core import ROOT, _fresh_db, _make_scraper

SHOTS = ROOT / "docs" / "screens"
NOW = int(time.time())
DAY = 86400


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed(db):
    db.add_channels(["alpha", "beta", "gamma"])
    names = {"alpha": ("Alpha Studio", 12000), "beta": ("Beta Official", 800), "gamma": ("Gamma", 50)}
    with db._conn() as c:
        for key, (nick, followers) in names.items():
            c.execute(
                "UPDATE channels SET nickname=?, followers=?, likes=?, video_count=?, status='done', updated_at=?, "
                "unique_id=?, group_name=? WHERE username=?",
                (nick, followers, followers * 9, 6, NOW - 600, key.capitalize(), "Nhóm A" if key != "gamma" else "", key),
            )
        for i in range(30):
            for key, (_, followers) in names.items():
                grow = followers * (0.7 + 0.3 * i / 29) if key != "gamma" else followers
                c.execute(
                    "INSERT INTO snapshots(username, ts, followers, likes, video_count, total_views) VALUES(?,?,?,?,?,?)",
                    (key, NOW - (29 - i) * DAY, int(grow), int(grow) * 9, 6, int(grow) * 40),
                )
        for i in range(8):
            c.execute(
                "INSERT INTO videos(id, username, description, create_time, duration, cover, play, digg, comment, share,"
                " collect, music, is_ad, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
                (f"a{i}", "alpha", f"Video số {i}", NOW - i * 3 * DAY - 3600 * (i % 5), 15, "", 1000 * (i + 1) ** 2,
                 100 * (i + 1), 10, 5, 3, "nhạc", NOW),
            )
        c.execute("INSERT INTO alerts(username, kind, text, ts) VALUES('alpha','followers','@Alpha tăng 12.0% follow (1.000 → 1.120)',?)", (NOW - 300,))
        c.execute("INSERT INTO alerts(username, kind, text, ts, read) VALUES('beta','new_video','@Beta có 1 video mới: xin chào',?,1)", (NOW - 9000,))
    db.set_status("gamma", "error", "Kênh không tồn tại hoặc bị khóa")


class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("không có playwright")
        import app as appmod
        import uvicorn

        cls.db = _fresh_db("ui")
        _seed(cls.db)
        appmod.scraper = _make_scraper()
        port = _free_port()
        cls.server = uvicorn.Server(uvicorn.Config(appmod.app, host="127.0.0.1", port=port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        cls.base = f"http://127.0.0.1:{port}"
        cls.pw = sync_playwright().start()
        cls.browser = None
        for channel in ("msedge", "chrome", None):
            try:
                cls.browser = cls.pw.chromium.launch(channel=channel)
                break
            except Exception:
                continue
        if cls.browser is None:
            cls.pw.stop()
            cls.server.should_exit = True
            raise unittest.SkipTest("không có trình duyệt cho Playwright")
        SHOTS.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
            cls.pw.stop()
        if getattr(cls, "server", None):
            cls.server.should_exit = True
            cls.thread.join(timeout=5)

    def setUp(self):
        self.ctx = self.browser.new_context(viewport={"width": 1360, "height": 820}, locale="vi-VN")
        self.ctx.add_init_script("window.UNDO_MS = 600;")
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.errors, [])

    def shot(self, name):
        self.page.screenshot(path=str(SHOTS / f"{name}.png"))

    def open_home(self):
        self.page.goto(self.base + "/")
        self.page.wait_for_selector("#table tbody tr")

    def test_channels_table_trend_and_filters(self):
        p = self.page
        self.open_home()
        self.assertEqual(p.locator("#table tbody tr").count(), 3)
        p.wait_for_selector("#table svg.spark")
        self.assertGreaterEqual(p.locator("#table svg.spark").count(), 2)
        self.assertIn("Kênh không tồn tại", p.locator("#table tr.err, #table .badge.err").first.inner_text())
        p.fill("#search", "beta")
        self.assertEqual(p.locator("#table tbody tr").count(), 1)
        p.fill("#search", "")
        p.select_option("#groupFilter", "Nhóm A")
        self.assertEqual(p.locator("#table tbody tr").count(), 2)
        self.shot("channels")

    def test_overview_and_alerts_tabs(self):
        p = self.page
        self.open_home()
        p.click('.tab[data-tab="overview"]')
        p.wait_for_selector("#ovFollowers svg path.ln")
        self.assertIn("Kênh", p.locator("#pane-overview .cards").inner_text())
        self.assertIn("@Alpha", p.locator("#pane-overview").inner_text())
        self.assertTrue(p.url.endswith("#overview"))
        self.shot("overview")
        self.assertEqual(p.locator("#alertCount").inner_text(), "1")
        p.click('.tab[data-tab="alerts"]')
        p.wait_for_selector(".alert-item.unread")
        self.assertEqual(p.locator(".alert-item").count(), 2)
        p.click("#alertsRead")
        p.wait_for_selector("#alertCount", state="hidden")
        self.shot("alerts")
        p.keyboard.press("1")
        self.assertTrue(p.locator("#pane-channels").is_visible())

    def test_drawer_and_keyboard(self):
        p = self.page
        self.open_home()
        p.click('#table tbody tr:has-text("Alpha")')
        p.keyboard.press("Space")
        p.wait_for_selector("#drChart svg path.ln")
        p.wait_for_timeout(350)  # chờ drawer trượt vào hẳn trước khi chụp
        self.assertTrue(p.locator("#drawer.on").count())
        self.assertIn("View trung vị", p.locator("#drawer").inner_text())
        self.assertGreater(p.locator("#drawer .heat-c").count(), 100)
        self.shot("drawer")
        p.click('#drawer [data-ddays="7"]')
        p.wait_for_selector("#drChart svg path.ln")
        p.keyboard.press("Escape")
        p.wait_for_function("!document.querySelector('#drawer').classList.contains('on')")

    def test_delete_has_undo_and_really_deletes_otherwise(self):
        p = self.page
        self.open_home()
        p.click('#table tbody tr:has-text("Gamma")')
        p.keyboard.press("Delete")
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 2")
        p.click(".toast .act")
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 3")
        time.sleep(1.2)
        self.assertTrue(self.db.channel_exists("gamma"))
        p.click('#table tbody tr:has-text("Gamma")')
        p.keyboard.press("Delete")
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 2")
        time.sleep(1.6)
        self.assertFalse(self.db.channel_exists("gamma"))
        self.db.add_channels(["gamma"])  # trả lại dữ liệu cho các test khác
        self.db.set_status("gamma", "error", "Kênh không tồn tại hoặc bị khóa")

    def test_palette_and_theme(self):
        p = self.page
        self.open_home()
        p.keyboard.press("Control+k")
        p.fill(".palette input", "beta")
        self.assertIn("Beta", p.locator(".palette li").first.inner_text())
        p.keyboard.press("Enter")
        p.wait_for_selector("#drChart svg")
        self.assertIn("@Beta", p.locator("#drawer .drawer-head").inner_text())
        p.keyboard.press("Escape")
        p.click("#btnSettings")
        p.select_option("#setTheme", "dark")
        p.check("#setDense")
        p.click("#setSave")
        self.assertEqual(p.evaluate("document.documentElement.dataset.theme"), "dark")
        self.assertTrue(p.evaluate("document.body.classList.contains('dense')"))
        p.reload()
        self.assertEqual(p.evaluate("document.documentElement.dataset.theme"), "dark")
        p.keyboard.press("?")
        self.assertTrue(p.locator("#dlgHelp").is_visible())
        self.shot("dark")

    def test_compare_dialog(self):
        p = self.page
        self.open_home()
        p.click('#table tbody tr:has-text("Alpha")')
        p.click('#table tbody tr:has-text("Beta")', modifiers=["Control"])
        p.click('#table tbody tr:has-text("Beta")', button="right", modifiers=["Control"])
        p.click('.ctx-item:has-text("So sánh")')
        p.wait_for_selector("#cmpChart svg path.ln")
        self.assertEqual(p.locator("#cmpChart path.ln").count(), 2)
        p.click('[data-cm="total_views"]')
        p.wait_for_function("document.querySelector('#cmpMetric .on').dataset.cm === 'total_views'")
        self.shot("compare")
        p.click("#cmpClose")

    def test_import_dialog_and_views(self):
        p = self.page
        self.open_home()
        p.click("#btnImport")
        p.fill("#importText", "username,group,note\n@newone,Nhóm Z,thử nhập\n")
        self.assertIn("CSV", p.locator("#importInfo").inner_text())
        p.select_option('#importScan [data-k="type"]', "limit")
        p.click("#importOk")
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 4")
        ch = self.db.get_channel("newone")
        self.assertEqual((ch["group_name"], ch["note"]), ("Nhóm Z", "thử nhập"))
        with self.db._conn() as c:
            c.execute("DELETE FROM channels WHERE username='newone'")
        # chế độ xem đã lưu
        p.fill("#search", "alpha")
        p.click("#btnViews")
        p.click('.ctx-item:has-text("Lưu bộ lọc")')
        p.fill("#promptInput", "Chỉ Alpha")
        p.click("#promptOk")
        p.wait_for_function("true")
        p.fill("#search", "")
        p.click("#btnViews")
        p.click('.ctx-item:has-text("Chỉ Alpha")')
        p.wait_for_function("document.querySelector('#search').value === 'alpha'")

    def test_videos_page_summary_and_star(self):
        p = self.page
        p.goto(self.base + "/videos?u=alpha")
        p.wait_for_selector("#table tbody tr")
        self.assertEqual(p.locator("#table tbody tr").count(), 8)
        p.wait_for_selector("#summary .card")
        self.assertIn("Tổng view", p.locator("#summary").inner_text())
        p.click("#analysis summary")
        p.wait_for_selector("#anTimeline svg path.ln")
        self.assertGreater(p.locator("#anHeat .heat-c").count(), 100)
        self.assertGreaterEqual(p.locator("#table tr.row-star").count(), 1)
        self.shot("videos")
        p.fill("#search", "Video số 7")
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 1")


if __name__ == "__main__":
    unittest.main()
