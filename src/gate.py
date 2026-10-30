"""Decides when a due reminder may open its window. Free of GTK and D-Bus, so the tests drive it with
a fake clock, a fake lock state and a fake process (tests/test_gate.py)."""
import logging
import threading
import time

UNLOCK_DELAY = 45       # s after unlock or wake-up before a deferred reminder shows
AFTER_CLOSE_DELAY = 30  # s after a reminder window closed before the next one shows
LOCK_POLL = 5           # s between two lock checks
WAKE_JUMP = 60          # s of wall clock between two ticks that count as a suspend


class ReminderGate:
    """At most one reminder window at a time, and none while the session is locked or a video
    conference runs (a reminder asked for by hand, manual=True, still shows during a conference).

    A reminder that cannot open now becomes the one pending reminder (a newer one replaces it) and
    opens a little after the way is clear: UNLOCK_DELAY after unlock or wake-up, AFTER_CLOSE_DELAY
    after the open window closed, right after the conference ended. A snoozed window
    keeps its process alive, so it still counts as open and holds back everything else until it is
    closed.

    spawn(module, settings) starts the window and returns its process (anything with poll()).
    is_locked() returns True, False or None (unknown, counts as unlocked); it is asked at most every
    LOCK_POLL seconds. in_conference() returns whether a conference runs (cheap, read every tick).
    find_missed(since, until) returns the (module, settings) of the latest reminder
    due between two wall-clock times, for a suspend. skip_reason() returns why a deferred reminder
    should be dropped instead of shown (paused) or None.
    """

    def __init__(self, spawn, is_locked=lambda: None, clock=time.time,
                 find_missed=lambda since, until: None, skip_reason=lambda: None,
                 in_conference=lambda: False):
        self._spawn = spawn
        self._is_locked = is_locked
        self._in_conference = in_conference
        self._clock = clock
        self._find_missed = find_missed
        self._skip_reason = skip_reason
        self._mutex = threading.Lock()
        self._proc = None
        self._open_module = None
        self._pending = None  # (module, settings)
        self._ready_at = 0.0
        self._hold_reason = ""
        self._locked = False
        self._conference = False
        self._lock_checked_at = None
        self._last_tick = None

    def request(self, module, settings, manual=False):
        """A reminder is due (or asked for by TRIGGER/test, manual=True: no wait after a close).
        Returns "shown", "deferred" or "dropped"."""
        with self._mutex:
            now = self._clock()
            self._check_edges(now)
            if self._window_open() and module == self._open_module:
                logging.info(f"Dropped {module}: the same reminder is still open")
                return "dropped"
            reason = self._blocked(now, manual)
            if reason:
                self._defer(module, settings, reason)
                return "deferred"
            self._launch(module, settings)
            return "shown"

    def tick(self):
        """Called every second by the scheduler."""
        with self._mutex:
            now = self._clock()
            if self._last_tick is not None and now - self._last_tick > WAKE_JUMP:
                self._woke(self._last_tick, now)
            self._last_tick = now

            self._check_edges(now)

            if self._pending and not self._blocked(now, manual=False):
                module, settings = self._pending
                self._pending = None
                skip = self._skip_reason()
                if skip:
                    logging.info(f"Dropped deferred {module}: {skip}")
                else:
                    logging.info(f"Showing deferred {module} after {self._hold_reason}")
                    self._launch(module, settings)

    def _check_edges(self, now):
        was_locked = self._locked
        self._poll_lock(now)
        if was_locked and not self._locked:
            logging.info("Screen unlocked")
            self._hold(now, UNLOCK_DELAY, "unlock")

        was_conference = self._conference
        self._conference = bool(self._in_conference())
        if was_conference and not self._conference:
            self._hold_reason = "the conference ended"  # no wait: the detector's end grace was it

        if self._proc is not None and self._proc.poll() is not None:
            self._proc = None
            self._open_module = None
            self._hold(now, AFTER_CLOSE_DELAY, "the last reminder closed")

    @property
    def pending(self):
        return self._pending[0] if self._pending else None

    def _window_open(self):
        return self._proc is not None and self._proc.poll() is None

    def _blocked(self, now, manual):
        if self._locked:
            return "screen locked"
        if self._window_open():
            return f"{self._open_module} is still open"
        if not manual and self._conference:
            return "video conference"
        if not manual and now < self._ready_at:
            return f"waiting after {self._hold_reason}"
        return None

    def _defer(self, module, settings, reason):
        replaced = f", replaces deferred {self._pending[0]}" if self._pending else ""
        logging.info(f"Deferred {module}: {reason}{replaced}")
        self._pending = (module, settings)

    def _launch(self, module, settings):
        self._proc = self._spawn(module, settings)
        self._open_module = module

    def _hold(self, now, delay, reason):
        self._ready_at = max(self._ready_at, now + delay)
        self._hold_reason = reason

    def _poll_lock(self, now):
        if self._lock_checked_at is not None and now - self._lock_checked_at < LOCK_POLL:
            return
        self._lock_checked_at = now
        try:
            locked = bool(self._is_locked())
        except Exception as e:
            logging.debug(f"Lock check failed: {e}")
            locked = False
        if locked and not self._locked:
            logging.info("Screen locked; reminders wait until unlock")
        self._locked = locked

    def _woke(self, since, now):
        logging.info(f"Clock jumped {int(now - since)} s (suspend?); missed reminders are not repeated")
        self._lock_checked_at = None  # the session is usually locked after a resume: check right away
        self._hold(now, UNLOCK_DELAY, "waking up")
        missed = self._find_missed(since, now)
        if missed:
            self._defer(missed[0], missed[1], "missed during suspend")
