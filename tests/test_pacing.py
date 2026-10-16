import random
import threading
import unittest
from unittest import mock

import db as dbmod
import pacing
from test_core import _Context, _Page, _SolvablePage, _fresh_db, _item_list, _make_scraper, _wait_until


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _pacer(pace="normal", seed=1):
    clock = _Clock()
    return pacing.Pacer(pace=lambda: pace, now=clock, rng=random.Random(seed)), clock


class GapTest(unittest.TestCase):
    def test_gap_is_random_and_inside_the_range(self):
        pacer, clock = _pacer()
        waits = {pacer.after_job("quick", pacing.OK) for _ in range(30)}
        self.assertGreater(len(waits), 5)
        self.assertTrue(all(2.5 <= w <= 6.0 for w in waits), waits)
        heavy = [pacer.after_job("scan", pacing.OK) for _ in range(30)]
        self.assertTrue(all(4.0 <= w <= 10.0 for w in heavy), heavy)
        self.assertGreater(max(heavy), 6.0)

    def test_slow_pace_waits_longer_than_normal(self):
        normal, _ = _pacer("normal")
        slow, _ = _pacer("slow")
        n = [normal.after_job("quick", pacing.OK) for _ in range(20)]
        s = [slow.after_job("quick", pacing.OK) for _ in range(20)]
        self.assertGreater(min(s), max(n) - 0.01)

    def test_off_keeps_the_old_fixed_pause_and_never_backs_off(self):
        pacer, _ = _pacer("off")
        for outcome in (pacing.BLOCKED, pacing.CAPTCHA, pacing.BLOCKED):
            self.assertEqual(pacer.after_job("scan", outcome), 0.0)
        self.assertAlmostEqual(pacer.remaining(), pacing.OFF_GAP)
        self.assertIsNone(pacer.backing_off())
        self.assertEqual(pacer.scroll_ms(), 1200)
        self.assertEqual(pacer.page_ms(), 0)

    def test_unknown_setting_value_falls_back_to_normal(self):
        pacer, _ = _pacer("turbo")
        self.assertEqual(pacer.mode(), "normal")

    def test_scroll_and_page_pauses_are_random_too(self):
        pacer, _ = _pacer()
        scrolls = {pacer.scroll_ms() for _ in range(40)}
        self.assertGreater(len(scrolls), 5)
        self.assertTrue(all(pacing.SCROLL_MS[0] <= v <= pacing.SCROLL_MS[1] for v in scrolls))
        self.assertTrue(all(pacing.PAGE_MS[0] <= pacer.page_ms() <= pacing.PAGE_MS[1] for _ in range(20)))


class BackoffTest(unittest.TestCase):
    def test_pause_doubles_with_every_consecutive_trouble(self):
        pacer, _ = _pacer()
        waits = [pacer.after_job("quick", pacing.BLOCKED) for _ in range(4)]
        for n, wait in enumerate(waits):
            base = 45.0 * 2 ** n
            self.assertTrue(base * 0.85 <= wait <= base * 1.15, (n, wait))
        self.assertEqual(pacer.streak, 4)

    def test_pause_is_capped(self):
        pacer, _ = _pacer()
        waits = [pacer.after_job("quick", pacing.CAPTCHA) for _ in range(12)]
        self.assertLessEqual(max(waits), pacing.BACKOFF_CAP)
        self.assertGreater(waits[-1], pacing.BACKOFF_CAP * 0.85 - 0.001)

    def test_no_pause_ever_exceeds_fifteen_minutes_at_any_pace(self):
        """The Settings text promises "at most 15 minutes": hold every pace, outcome, seed and streak length to it."""
        limit = 15 * 60
        self.assertEqual(pacing.BACKOFF_CAP, limit)
        for pace in ("normal", "slow"):
            for outcome in (pacing.BLOCKED, pacing.CAPTCHA):
                for seed in range(40):
                    pacer, clock = _pacer(pace, seed)
                    for n in range(1, 31):
                        wait = pacer.after_job("scan", outcome)
                        self.assertLessEqual(wait, limit, (pace, outcome, seed, n))
                        self.assertLessEqual(pacer.remaining(), limit + 1e-6, (pace, outcome, seed, n))   # float error of now+wait-now
                        self.assertLessEqual(pacer.backing_off()["seconds"], limit, (pace, outcome, seed, n))
                        clock.t += wait   # the next trouble comes right after the pause, so the streak keeps growing

    def test_slow_pace_reaches_the_cap_but_not_beyond_it(self):
        pacer, clock = _pacer("slow", seed=7)
        waits = []
        for _ in range(12):
            waits.append(pacer.after_job("scan", pacing.CAPTCHA))
            clock.t += waits[-1]
        self.assertEqual(max(waits), min(max(waits), pacing.BACKOFF_CAP))
        self.assertGreater(waits[-1], pacing.BACKOFF_CAP * 0.8)
        self.assertEqual(len({round(w, 3) for w in waits[-5:]}), 5, "pauses at the cap should still be random")

    def test_a_very_long_streak_neither_overflows_nor_exceeds_the_cap(self):
        pacer, _ = _pacer("slow")
        pacer.streak = 5000
        self.assertLessEqual(pacer.after_job("quick", pacing.BLOCKED), pacing.BACKOFF_CAP)

    def test_an_old_trouble_is_forgotten_but_a_recent_one_is_not(self):
        pacer, clock = _pacer()
        pacer.after_job("quick", pacing.BLOCKED)
        clock.t += 10 * 60   # inside the memory: this is the second trouble of one streak
        self.assertTrue(90 * 0.85 <= pacer.after_job("quick", pacing.BLOCKED) <= 90 * 1.15)
        self.assertEqual(pacer.streak, 2)
        clock.t += 31 * 60   # a quiet spell longer than the 30 minutes promised in the docs: a new incident starts from the first step
        self.assertTrue(45 * 0.85 <= pacer.after_job("quick", pacing.BLOCKED) <= 45 * 1.15)
        self.assertEqual(pacer.streak, 1)

    def test_the_memory_window_is_longer_than_the_longest_pause(self):
        """Otherwise a streak at the cap would be forgotten between two of its own troubles."""
        self.assertGreater(pacing.STREAK_MEMORY, pacing.BACKOFF_CAP * 1.5)

    def test_neutral_jobs_do_not_refresh_the_memory(self):
        pacer, clock = _pacer()
        pacer.after_job("quick", pacing.BLOCKED)
        for _ in range(5):
            clock.t += 10 * 60
            pacer.after_job("quick", pacing.NEUTRAL)
        self.assertTrue(45 * 0.85 <= pacer.after_job("quick", pacing.BLOCKED) <= 45 * 1.15)

    def test_captcha_waits_longer_than_an_unreadable_page(self):
        a, _ = _pacer(seed=3)
        b, _ = _pacer(seed=3)
        self.assertGreater(b.after_job("quick", pacing.CAPTCHA), a.after_job("quick", pacing.BLOCKED))

    def test_success_resets_the_streak(self):
        pacer, _ = _pacer()
        pacer.after_job("quick", pacing.BLOCKED)
        pacer.after_job("quick", pacing.BLOCKED)
        self.assertEqual(pacer.streak, 2)
        wait = pacer.after_job("quick", pacing.OK)
        self.assertEqual(pacer.streak, 0)
        self.assertLessEqual(wait, 6.0)
        self.assertIsNone(pacer.backing_off())
        self.assertTrue(45 * 0.85 <= pacer.after_job("quick", pacing.BLOCKED) <= 45 * 1.15)

    def test_neutral_outcome_neither_extends_nor_resets(self):
        pacer, _ = _pacer()
        pacer.after_job("quick", pacing.BLOCKED)
        wait = pacer.after_job("quick", pacing.NEUTRAL)
        self.assertEqual(pacer.streak, 1)
        self.assertLessEqual(wait, 6.0)
        # the next trouble is the second in a row: twice the base pause
        self.assertTrue(90 * 0.85 <= pacer.after_job("quick", pacing.BLOCKED) <= 90 * 1.15)

    def test_slow_pace_backs_off_longer(self):
        normal, _ = _pacer("normal", seed=5)
        slow, _ = _pacer("slow", seed=5)
        self.assertAlmostEqual(slow.after_job("quick", pacing.BLOCKED), normal.after_job("quick", pacing.BLOCKED) * 1.5)

    def test_backing_off_report_counts_down_and_hides_routine_gaps(self):
        pacer, clock = _pacer()
        pacer.after_job("quick", pacing.OK)
        self.assertIsNone(pacer.backing_off())
        wait = pacer.after_job("quick", pacing.CAPTCHA)
        info = pacer.backing_off()
        self.assertEqual(info["reason"], pacing.CAPTCHA)
        self.assertEqual(info["streak"], 1)
        self.assertAlmostEqual(info["seconds"], wait, delta=1.5)
        clock.t += wait - 10
        self.assertLessEqual(pacer.backing_off()["seconds"], 11)
        clock.t += 11
        self.assertIsNone(pacer.backing_off())
        self.assertEqual(pacer.remaining(), 0.0)

    def test_countdown_rounds_up_without_overshooting_the_wait(self):
        """A pause of exactly 15 minutes shows as 900 seconds, never 901; a fraction of a second rounds up to 1."""
        pacer, clock = _pacer()
        pacer.reason = pacing.BLOCKED
        for left, shown in ((900.0, 900), (899.2, 900), (61.0, 61), (60.01, 61), (1.0, 1), (0.4, 1)):
            pacer.resume_at = clock.t + left
            self.assertEqual(pacer.backing_off()["seconds"], shown, left)
        pacer.resume_at = clock.t   # nothing left: no pause to show
        self.assertIsNone(pacer.backing_off())

    def test_countdown_survives_float_error_of_the_clock(self):
        clock = _Clock()
        clock.t = 1023.7964627091891   # (t + 900.0) - t is 900.0000000000001 for this value: a bare ceil shows 901
        self.assertGreater((clock.t + 900.0) - clock.t, 900.0)
        pacer = pacing.Pacer(pace=lambda: "normal", now=clock, rng=random.Random(1))
        pacer.reason = pacing.CAPTCHA
        pacer.resume_at = clock.t + 900.0
        self.assertEqual(pacer.backing_off()["seconds"], 900)
        for pace in ("normal", "slow"):
            pacer = pacing.Pacer(pace=lambda: pace, now=clock, rng=random.Random(2))
            for _ in range(15):
                pacer.after_job("scan", pacing.CAPTCHA)
                self.assertLessEqual(pacer.backing_off()["seconds"], 900)
                clock.t += pacer.remaining()

    def test_skip_drops_the_wait_but_keeps_the_streak(self):
        pacer, _ = _pacer()
        pacer.after_job("quick", pacing.BLOCKED)
        pacer.skip()
        self.assertEqual(pacer.remaining(), 0.0)
        self.assertIsNone(pacer.backing_off())
        self.assertGreater(pacer.after_job("quick", pacing.BLOCKED), 45 * 1.5)


class OutcomeTest(unittest.TestCase):
    """Scraper._execute tells the pacer how a job went."""

    def _execute(self, name, page=None, job=None, scrape=None):
        from scraper import normalize_job

        db = _fresh_db(name)
        db.add_channels(["demo"])
        scraper = _make_scraper()
        if scrape:
            scraper._scrape = scrape
        else:
            scraper._browser = lambda: _Context(page)
        return scraper._execute("demo", normalize_job(job or {"mode": "quick"})), db

    def test_normal_scan_is_ok(self):
        outcome, db = self._execute("out-ok", _Page([_item_list(("9", 1, 1))]))
        self.assertEqual(outcome, pacing.OK)
        self.assertEqual(db.get_channel("demo")["status"], "done")

    def test_captcha_is_reported(self):
        class CaptchaPage(_Page):
            html = '<div id="captcha-container"></div>'

        outcome, _ = self._execute("out-captcha", CaptchaPage([]))
        self.assertEqual(outcome, pacing.CAPTCHA)

    def test_captcha_the_user_solved_does_not_slow_the_queue(self):
        page = _SolvablePage()
        outcome, db = self._execute("out-solved", page)
        self.assertEqual(outcome, pacing.OK)
        self.assertEqual(db.get_channel("demo")["status"], "done")
        self.assertEqual(page.moves, [True, False])   # the window was shown, solved and hidden again

    def test_captcha_left_unsolved_still_backs_off(self):
        page = _SolvablePage(solves=False)
        scraper = _make_scraper()
        scraper.CAPTCHA_WAIT_STEPS = 2
        _fresh_db("out-unsolved").add_channels(["demo"])
        self.assertFalse(scraper._wait_captcha_solved(page, "demo"))
        self.assertIn(pacing.CAPTCHA, scraper._flags)

    def test_solving_clears_no_earlier_flag_and_adds_none(self):
        scraper = _make_scraper()
        scraper._flags = {pacing.BLOCKED}
        _fresh_db("out-flags").add_channels(["demo"])
        self.assertTrue(scraper._wait_captcha_solved(_SolvablePage(), "demo"))
        self.assertEqual(scraper._flags, {pacing.BLOCKED})

    def test_empty_video_list_for_a_channel_with_videos_counts_as_blocked(self):
        outcome, db = self._execute("out-empty", _Page([]))
        self.assertEqual(outcome, pacing.BLOCKED)
        self.assertEqual(db.get_channel("demo")["video_count"], 2)

    def test_unreadable_page_counts_as_blocked(self):
        class Unreadable(_Page):
            def evaluate(self, script):
                return None

        outcome, db = self._execute("out-unreadable", Unreadable([]))
        self.assertEqual(outcome, pacing.BLOCKED)
        self.assertIn("Không đọc được", db.get_channel("demo")["message"])

    def test_tiktok_stopping_mid_scan_counts_as_blocked(self):
        page = _Page([_item_list(("9", 100, 1), has_more=True)])
        outcome, _ = self._execute("out-stop", page, {"mode": "scan"})
        self.assertEqual(outcome, pacing.BLOCKED)

    def test_missing_channel_is_neutral(self):
        class Gone(_Page):
            def evaluate(self, script):
                if "UNIVERSAL_DATA" in script:
                    return '{"__DEFAULT_SCOPE__":{"webapp.user-detail":{"statusCode":10221}}}'
                return None

        outcome, db = self._execute("out-gone", Gone([]))
        self.assertEqual(outcome, pacing.NEUTRAL)
        self.assertEqual(db.get_channel("demo")["status"], "error")

    def test_transient_error_that_keeps_failing_is_blocked_and_one_that_recovers_is_ok(self):
        def always(key, job):
            raise TimeoutError("page.goto: Timeout 60000ms exceeded")

        outcome, _ = self._execute("out-timeout", scrape=always)
        self.assertEqual(outcome, pacing.BLOCKED)

        calls = []

        def flaky(key, job):
            calls.append(key)
            if len(calls) == 1:
                raise TimeoutError("timeout")
            dbmod.set_status(key, "done", "")

        outcome, _ = self._execute("out-recover", scrape=flaky)
        self.assertEqual(outcome, pacing.OK)

    def test_permanent_error_is_neutral(self):
        def boom(key, job):
            raise ValueError("bad data")

        outcome, db = self._execute("out-permanent", scrape=boom)
        self.assertEqual(outcome, pacing.NEUTRAL)
        self.assertIn("bad data", db.get_channel("demo")["message"])

    def test_flags_do_not_leak_into_the_next_job(self):
        outcome, db = self._execute("out-leak", _Page([]))
        self.assertEqual(outcome, pacing.BLOCKED)
        from scraper import normalize_job

        scraper = _make_scraper()
        scraper._flags = {pacing.CAPTCHA}
        scraper._scrape = lambda key, job: dbmod.set_status(key, "done", "")
        self.assertEqual(scraper._execute("demo", normalize_job({"mode": "quick"})), pacing.OK)


class WorkerTest(unittest.TestCase):
    def test_worker_rests_after_trouble_and_speeds_up_after_success(self):
        db = _fresh_db("worker-rest")
        db.add_channels(["a", "b", "c"])
        scraper = _make_scraper()
        order = []

        def scrape(key, job):
            order.append(key)
            if key == "a":
                scraper._flags.add(pacing.BLOCKED)
                db.set_status(key, "error", "Không đọc được trang kênh")
            else:
                db.set_status(key, "done", "")

        scraper._scrape = scrape
        slept = []
        scraper.enqueue(["a", "b", "c"], {"mode": "quick"})
        with mock.patch("time.sleep", lambda seconds: slept.append(seconds)):
            threading.Thread(target=scraper._run, daemon=True).start()
            self.assertTrue(_wait_until(lambda: order == ["a", "b", "c"] and scraper.current is None))
        self.assertGreater(sum(slept), 45 * 0.85 - 1, "no long pause after the first channel failed")
        self.assertLess(sum(slept), 45 * 1.15 + 3 * 6.0 + 3, "pauses kept growing although the next jobs succeeded")
        self.assertEqual(scraper.pacer.streak, 0)

    def test_wait_turn_stops_when_the_user_skips(self):
        scraper = _make_scraper()
        scraper.pacer.after_job("quick", pacing.CAPTCHA)
        self.assertEqual(scraper.status()["pause"]["reason"], pacing.CAPTCHA)
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            if len(slept) == 3:
                scraper.skip_pause()

        with mock.patch("time.sleep", sleep):
            scraper._wait_turn()
        self.assertEqual(len(slept), 3)
        self.assertIsNone(scraper.status()["pause"])

    def test_wait_turn_does_not_sleep_without_a_pause(self):
        scraper = _make_scraper()
        with mock.patch("time.sleep", side_effect=AssertionError("slept")):
            scraper._wait_turn()


class ApiPaceTest(unittest.TestCase):
    def _client(self, name):
        import app as appmod
        from fastapi.testclient import TestClient

        db = _fresh_db(name)
        appmod.scraper = _make_scraper()
        return TestClient(appmod.app), db, appmod.scraper

    def test_pace_setting_defaults_to_normal_and_is_saved(self):
        client, db, _ = self._client("pace-setting")
        self.assertEqual(client.get("/api/settings").json()["scan_pace"], "normal")
        client.post("/api/settings", json={"scan_pace": "slow"})
        self.assertEqual(client.get("/api/settings").json()["scan_pace"], "slow")
        self.assertEqual(db.get_setting("scan_pace"), "slow")

    def test_resume_endpoint_skips_the_pause(self):
        client, _, scraper = self._client("pace-resume")
        scraper.pacer.after_job("quick", pacing.BLOCKED)
        self.assertEqual(client.get("/api/channels").json()["worker"]["pause"]["reason"], pacing.BLOCKED)
        res = client.post("/api/worker/resume", json={}).json()
        self.assertIsNone(res["worker"]["pause"])
        self.assertEqual(scraper.pacer.remaining(), 0.0)


if __name__ == "__main__":
    unittest.main()
