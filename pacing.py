"""Scan pacing: a random gap between channels and a growing pause while TikTok pushes back.

TikTok throttles a client that scans many channels in a burst: it first returns empty video lists or
unreadable pages, then captchas, and keeps refusing for several minutes. Fixed, machine-regular timing
makes that worse, so the gap between jobs is random and every consecutive trouble doubles the pause.
All time handling is injected (`now`, `rng`) so the policy is testable without sleeping.
"""
import random
import threading
import time

OK, NEUTRAL, BLOCKED, CAPTCHA = "ok", "neutral", "blocked", "captcha"

# Gap between two jobs in seconds, as (low, high), by the setting `scan_pace`.
# "off" keeps the old fixed pause and never backs off.
GAPS = {
    "normal": {"quick": (2.5, 6.0), "heavy": (4.0, 10.0)},
    "slow": {"quick": (6.0, 14.0), "heavy": (10.0, 24.0)},
}
OFF_GAP = 1.5
BACKOFF_BASE = {BLOCKED: 45.0, CAPTCHA: 120.0}
BACKOFF_CAP = 900.0   # TikTok has been seen refusing for ~9 minutes; 15 minutes is the longest wait, at every pace
STREAK_MEMORY = 1800.0   # troubles further apart than this are separate incidents, not one growing streak
MAX_DOUBLINGS = 10       # 45 s * 2**10 is far above the cap; the limit only keeps the arithmetic small
SCROLL_MS = (900, 1700)
PAGE_MS = (400, 1300)
VALID_PACES = ("off", "normal", "slow")


class Pacer:
    def __init__(self, pace=lambda: "normal", now=time.time, rng=None):
        self._pace = pace
        self._now = now
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self.streak = 0            # consecutive jobs that met resistance
        self.last_trouble = 0.0    # when the latest of them ended
        self.resume_at = 0.0       # no job starts before this moment
        self.reason = None         # why we are waiting: "gap" (routine) or BLOCKED / CAPTCHA (backing off)

    def mode(self):
        pace = self._pace()
        return pace if pace in VALID_PACES else "normal"

    def _scaled(self, low_high):
        return self._rng.uniform(*low_high)

    def after_job(self, job_mode, outcome):
        """Record how a job ended and schedule the earliest start of the next one."""
        pace = self.mode()
        with self._lock:
            if pace == "off":
                self.streak, self.reason = 0, None
                self.resume_at = self._now() + OFF_GAP
                return 0.0
            if outcome == OK:
                self.streak = 0
            gap = self._scaled(GAPS[pace]["quick" if job_mode == "quick" else "heavy"])
            backoff = 0.0
            if outcome in BACKOFF_BASE:
                now = self._now()
                if now - self.last_trouble > STREAK_MEMORY:
                    self.streak = 0
                self.streak += 1
                self.last_trouble = now
                backoff = BACKOFF_BASE[outcome] * 2 ** min(self.streak - 1, MAX_DOUBLINGS)
                if pace == "slow":
                    backoff *= 1.5
                # Jitter first, cap last: the promised longest pause holds for every pace and stays random near it.
                backoff = min(BACKOFF_CAP, min(backoff, BACKOFF_CAP) * self._rng.uniform(0.85, 1.15))
            self.reason = outcome if backoff > gap else "gap"
            wait = max(gap, backoff)
            self.resume_at = self._now() + wait
            return wait

    def remaining(self):
        with self._lock:
            return max(0.0, self.resume_at - self._now())

    def backing_off(self):
        """{"seconds", "reason", "streak"} while a trouble pause is running, else None; routine gaps are not reported."""
        with self._lock:
            left = self.resume_at - self._now()
            if self.reason in (BLOCKED, CAPTCHA) and left > 0:
                return {"seconds": int(left) + 1, "reason": self.reason, "streak": self.streak}
        return None

    def skip(self):
        """The user wants to go on now: drop the wait. The streak stays, so a further failure backs off again."""
        with self._lock:
            self.resume_at = 0.0
            self.reason = None

    def scroll_ms(self):
        return self._rng.randint(*SCROLL_MS) if self.mode() != "off" else 1200

    def page_ms(self):
        return self._rng.randint(*PAGE_MS) if self.mode() != "off" else 0
