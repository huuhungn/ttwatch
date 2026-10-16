"""UI tests in a real browser; TikTok is never called.

The app runs under uvicorn on a random port with sample DB data and a fake scraper (no background
threads, no browser). Skipped if the machine has no Chrome/Edge/Playwright Chromium.
Screenshots are saved to docs/screens/ for a quick look after each run.
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
            raise unittest.SkipTest("playwright is not installed")
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
            raise unittest.SkipTest("no browser available for Playwright")
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
        p.wait_for_timeout(350)  # wait for the drawer to finish sliding in before taking the screenshot
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
        self.db.add_channels(["gamma"])  # restore the data for the other tests
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
        p.click('[data-cp="1"]')
        # in % mode every channel starts at 0%, so the lines share a starting point regardless of scale
        p.wait_for_function("""() => {
            const ys = [...document.querySelectorAll('#cmpChart path.ln')].map(x => x.getAttribute('d').match(/^M[\d.]+,([\d.]+)/)[1]);
            return ys.length === 2 && ys[0] === ys[1];
        }""")
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
        # saved views
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

    def test_group_chips_filter_rename_and_clear(self):
        p = self.page
        self.open_home()
        p.wait_for_selector("#groupChips .chip")
        names = p.locator("#groupChips .chip").all_inner_texts()
        self.assertTrue(any("Nhóm A" in n for n in names))
        self.assertTrue(any("Chưa gắn nhóm" in n for n in names))
        p.click('#groupChips .chip:has-text("Chưa gắn nhóm")')
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 1")
        p.click('#groupChips .chip:has-text("Tất cả")')
        p.wait_for_function("document.querySelectorAll('#table tbody tr').length === 3")
        p.click('#groupChips .chip:has-text("Nhóm A")', button="right")
        p.click('.ctx-item:has-text("Đổi tên nhóm")')
        p.fill("#promptInput", "Nhóm B")
        p.click("#promptOk")
        p.wait_for_selector('#groupChips .chip:has-text("Nhóm B")')
        self.assertEqual(self.db.get_channel("alpha")["group_name"], "Nhóm B")
        p.click('#groupChips .chip:has-text("Nhóm B")', button="right")
        p.click('.ctx-item:has-text("Bỏ nhóm này")')
        p.wait_for_function("document.querySelectorAll('#groupChips .chip').length === 0 || document.querySelector('#groupChips').hidden")
        self.assertEqual(self.db.get_channel("alpha")["group_name"], "")
        # restore the data for the other tests
        self.db.update_meta(["alpha", "beta"], "Nhóm A")

    def test_keyboard_only_navigation(self):
        p = self.page
        self.open_home()
        p.focus("#tab-channels")
        p.keyboard.press("ArrowRight")
        p.wait_for_selector("#pane-overview.on")
        self.assertEqual(p.evaluate("document.activeElement.id"), "tab-overview")
        self.assertEqual(p.evaluate("document.querySelector('#tab-channels').tabIndex"), -1)
        p.keyboard.press("Home")
        p.wait_for_selector("#pane-channels.on")
        p.focus("body")
        p.keyboard.press("ArrowDown")
        p.keyboard.press("ArrowDown")
        self.assertEqual(p.locator("#table tbody tr.sel").count(), 1)
        self.assertIn("Beta", p.locator("#table tbody tr.sel").inner_text())
        p.keyboard.press("Shift+ArrowDown")
        self.assertEqual(p.locator("#table tbody tr.sel").count(), 2)
        p.keyboard.press("Space")
        p.wait_for_selector("#drawer.on")
        # focus must be inside the drawer, and returned when it closes
        self.assertTrue(p.evaluate("document.querySelector('#drawer').contains(document.activeElement)"))
        p.keyboard.press("Escape")
        p.wait_for_function("!document.querySelector('#drawer').classList.contains('on')")

    def test_name_and_username_columns_stay_while_scrolling(self):
        p = self.page
        p.set_viewport_size({"width": 700, "height": 700})
        self.open_home()
        p.evaluate("document.querySelector('#table').scrollLeft = 400")
        a = p.evaluate("document.querySelector('td.col-stt').getBoundingClientRect().left")
        b = p.evaluate("document.querySelector('td.col-username').getBoundingClientRect().left")
        wrap = p.evaluate("document.querySelector('#table').getBoundingClientRect().left")
        self.assertAlmostEqual(a, wrap, delta=3)
        self.assertAlmostEqual(b, wrap + 44, delta=4)
        self.shot("narrow")

    def test_text_contrast_meets_aa_in_both_themes(self):
        p = self.page
        self.open_home()
        p.click('.tab[data-tab="alerts"]')
        p.wait_for_selector(".alert-item")
        p.click('.tab[data-tab="channels"]')
        script = """
        () => {
          const lum = (c) => { const f = (v) => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
            return 0.2126*f(c[0]) + 0.7152*f(c[1]) + 0.0722*f(c[2]); };
          const parse = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
            const a = m[1].split(',').map(x => parseFloat(x)); return [a[0], a[1], a[2], a.length > 3 ? a[3] : 1]; };
          const bgOf = (el) => { for (let e = el; e; e = e.parentElement) {
              const c = parse(getComputedStyle(e).backgroundColor); if (c && c[3] > 0.5) return c; }
            return parse(getComputedStyle(document.body).backgroundColor); };
          const bad = [];
          const seen = new Set();
          const sel = 'th, td, .muted, .badge, .btn, .tab, .delta, .statusbar, .toolbar, .chip, .detect, .add-scan, label, small, h3, .logo';
          for (const el of document.querySelectorAll(sel)) {
            if (!el.offsetParent && el.tagName !== 'BODY') continue;
            const text = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
            if (!text) continue;
            const fg = parse(getComputedStyle(el).color), bg = bgOf(el);
            if (!fg || !bg) continue;
            const L1 = lum(fg), L2 = lum(bg);
            const r = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
            const key = el.className + '|' + getComputedStyle(el).color + '|' + getComputedStyle(el).backgroundColor;
            if (r < 4.5 && !seen.has(key)) { seen.add(key); bad.push([el.tagName + '.' + el.className, el.textContent.trim().slice(0, 24), r.toFixed(2)]); }
          }
          return bad;
        }
        """
        for theme in ("light", "dark"):
            p.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
            p.wait_for_timeout(50)
            bad = p.evaluate(script)
            self.assertEqual(bad, [], f"contrast below 4.5:1 in the {theme} theme")

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

    # ------------------------------------------------------------ self-update bar (the server's answer is faked)

    def _fake_update(self, **over):
        state = {"current": "0.1.2", "latest": "0.2.0", "available": True, "status": "available", "progress": 0,
                 "check_error": None, "install_error": None, "checked_at": NOW, "skipped": False,
                 "page": "https://github.com/huuhungn/ttwatch/releases/tag/v0.2.0", "size": 104857600,
                 "can_install": True, "block_reason": None, "last_result": None}
        state.update(over)
        installs = []

        def get_state(route):
            route.fulfill(json=state)

        def install(route):
            installs.append(route.request.post_data_json)
            state.update(status="downloading", progress=0.4)
            route.fulfill(json=state)

        self.page.route("**/api/update", get_state)
        self.page.route("**/api/update/install", install)
        return state, installs

    def test_update_bar_offers_installs_and_can_be_dismissed(self):
        p = self.page
        state, installs = self._fake_update()
        self.open_home()
        p.wait_for_selector("#updateBar:not([hidden])")
        text = p.locator("#updateText").inner_text()
        self.assertIn("0.2.0", text)
        self.assertIn("100 MB", text)
        self.assertEqual(p.locator("#updateNotes").get_attribute("href"), state["page"])
        p.click("#updateLater")
        self.assertTrue(p.locator("#updateBar").is_hidden())
        p.reload()
        p.wait_for_selector("#updateBar:not([hidden])")  # "later" only lasts until the page is reloaded
        p.click("#updateNow")
        p.wait_for_function("document.querySelector('#updateText').textContent.includes('Đang tải')")
        self.assertEqual(installs, [{"force": False}])
        self.assertTrue(p.locator("#updateProgress").is_visible())
        self.assertTrue(p.locator("#updateNow").is_hidden())

    def test_update_bar_without_install_support_points_to_the_download(self):
        p = self.page
        self._fake_update(can_install=False, block_reason="Bạn đang chạy từ mã nguồn; chỉ bản exe mới tự cập nhật.")
        self.open_home()
        p.wait_for_selector("#updateBar:not([hidden])")
        self.assertIn("chạy từ mã nguồn", p.locator("#updateText").inner_text())
        self.assertTrue(p.locator("#updateNow").is_hidden())
        self.assertTrue(p.locator("#updateNotes").is_visible())

    def test_update_bar_hidden_when_up_to_date_or_skipped(self):
        p = self.page
        state, _ = self._fake_update(available=False, status="uptodate", latest="0.1.2")
        self.open_home()
        p.wait_for_function("document.querySelector('#aboutVersion').textContent === '0.1.2'")
        self.assertTrue(p.locator("#updateBar").is_hidden())
        state.update(available=True, latest="0.2.0", status="available", skipped=True)
        p.wait_for_timeout(3300)
        self.assertTrue(p.locator("#updateBar").is_hidden())

    def test_update_settings_are_saved(self):
        p = self.page
        self._fake_update(available=False, status="uptodate", latest="0.1.2")
        self.open_home()
        p.click("#btnSettings")
        p.wait_for_selector("#dlgSettings[open]")
        self.assertTrue(p.locator("#setUpdCheck").is_checked())
        self.assertTrue(p.locator("#setUpdAuto").is_checked())
        p.uncheck("#setUpdAuto")
        try:
            p.click("#setSave")
            p.wait_for_function("!document.querySelector('#dlgSettings').open")
            self.assertEqual(self.db.get_setting("update_auto"), "0")
            self.assertEqual(self.db.get_setting("update_check"), "1")
        finally:
            self.db.set_settings({"update_auto": "1"})

    # ------------------------------------------------------------ scan pacing

    def test_worker_bar_shows_the_pause_and_can_skip_it(self):
        p = self.page
        paused = {"seconds": 95, "reason": "captcha", "streak": 2}
        resumed = []

        def channels(route):
            response = route.fetch()
            data = response.json()
            data["worker"] = {"queue": 3, "current": None, "pause": paused}
            route.fulfill(json=data)

        def resume(route):
            resumed.append(True)
            paused.clear()
            route.fulfill(json={"worker": {"queue": 3, "current": None, "pause": None}})

        p.route("**/api/channels", channels)
        p.route("**/api/worker/resume", resume)
        self.open_home()
        p.wait_for_selector("#btnResume")
        text = p.locator("#worker").inner_text()
        self.assertIn("captcha", text)
        self.assertIn("1 phút 35 giây", text)
        self.assertIn("còn 3 kênh chờ", text)
        p.click("#btnResume")
        p.wait_for_function("!document.querySelector('#btnResume')")
        self.assertEqual(resumed, [True])

    def test_scan_pace_setting_is_saved(self):
        p = self.page
        self.open_home()
        p.click("#btnSettings")
        p.wait_for_selector("#dlgSettings[open]")
        self.assertEqual(p.locator("#setPace").input_value(), "normal")
        p.select_option("#setPace", "slow")
        try:
            p.click("#setSave")
            p.wait_for_function("!document.querySelector('#dlgSettings').open")
            self.assertEqual(self.db.get_setting("scan_pace"), "slow")
        finally:
            self.db.set_settings({"scan_pace": "normal"})

    # ------------------------------------------------------------ start with Windows

    def test_autostart_is_disabled_with_a_reason_when_running_from_source(self):
        p = self.page
        self.open_home()
        p.click("#btnSettings")
        p.wait_for_selector("#dlgSettings[open]")
        p.wait_for_function("document.querySelector('#autostartInfo').textContent !== ''")
        self.assertTrue(p.locator("#setAutostart").is_disabled())
        self.assertFalse(p.locator("#setAutostart").is_checked())
        self.assertIn("mã nguồn", p.locator("#autostartInfo").inner_text())

    def _fake_autostart(self, **state):
        base = {"supported": True, "reason": None, "enabled": False, "stale": False, "blocked": False}
        base.update(state)
        posts = []

        def handle(route):
            if route.request.method == "POST":
                posts.append(route.request.post_data_json)
                base["enabled"] = posts[-1]["enabled"]
                base["blocked"] = False
            route.fulfill(json=base)

        self.page.route("**/api/autostart", handle)
        return posts

    def test_autostart_checkbox_is_saved_through_its_own_endpoint(self):
        p = self.page
        posts = self._fake_autostart()
        self.open_home()
        p.click("#btnSettings")
        p.wait_for_selector("#dlgSettings[open]")
        p.wait_for_function("!document.querySelector('#setAutostart').disabled")
        self.assertFalse(p.locator("#setAutostart").is_checked())
        p.click("#setSave")   # nothing changed: no request
        p.wait_for_function("!document.querySelector('#dlgSettings').open")
        self.assertEqual(posts, [])
        p.click("#btnSettings")
        p.wait_for_selector("#dlgSettings[open]")
        p.wait_for_function("!document.querySelector('#setAutostart').disabled")
        p.check("#setAutostart")
        p.click("#setSave")
        p.wait_for_function("!document.querySelector('#dlgSettings').open")
        self.assertEqual(posts, [{"enabled": True}])

    def test_autostart_blocked_in_task_manager_is_explained_and_can_be_switched_back_on(self):
        p = self.page
        posts = self._fake_autostart(enabled=True, blocked=True)
        self.open_home()
        p.click("#btnSettings")
        p.wait_for_selector("#dlgSettings[open]")
        p.wait_for_function("document.querySelector('#autostartInfo').textContent !== ''")
        self.assertIn("Task Manager", p.locator("#autostartInfo").inner_text())
        self.assertFalse(p.locator("#setAutostart").is_checked())
        p.check("#setAutostart")
        p.click("#setSave")
        p.wait_for_function("!document.querySelector('#dlgSettings').open")
        self.assertEqual(posts, [{"enabled": True}])


if __name__ == "__main__":
    unittest.main()
