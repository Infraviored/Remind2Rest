"""Run: python -m unittest tests.test_gate   (not `discover`: tests/test_1..4.py open GTK windows on import)."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gate import ReminderGate, UNLOCK_DELAY, AFTER_CLOSE_DELAY, LOCK_POLL, CONFERENCE_END_DELAY


class FakeProc:
    def __init__(self):
        self.running = True

    def poll(self):
        return None if self.running else 0


class Harness:
    def __init__(self):
        self.now = 1_000_000.0
        self.locked = False
        self.lock_checks = 0
        self.spawned = []  # (module, settings, proc)
        self.skip = None
        self.missed = None
        self.conference = False
        self.gate = ReminderGate(self.spawn, is_locked=self.is_locked, clock=lambda: self.now,
                                 find_missed=lambda since, until: self.missed, skip_reason=lambda: self.skip,
                                 in_conference=lambda: self.conference)

    def spawn(self, module, settings):
        proc = FakeProc()
        self.spawned.append((module, settings, proc))
        return proc

    def is_locked(self):
        self.lock_checks += 1
        return self.locked

    def run(self, seconds):
        """Advance the clock second by second, ticking like the scheduler does."""
        for _ in range(int(seconds)):
            self.now += 1
            self.gate.tick()

    def shown(self):
        return [m for m, _, _ in self.spawned]

    def close_last(self):
        self.spawned[-1][2].running = False


class GateTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.gate.tick()

    def test_shows_at_once_when_free(self):
        self.assertEqual(self.h.gate.request("posture", {}), "shown")
        self.assertEqual(self.h.shown(), ["posture"])

    def test_locked_defers_one_and_shows_after_unlock_delay(self):
        h = self.h
        h.locked = True
        h.run(LOCK_POLL)
        with self.assertLogs(level="INFO") as logs:
            self.assertEqual(h.gate.request("posture", {}), "deferred")
            self.assertEqual(h.gate.request("eye_relax", {}), "deferred")
            self.assertEqual(h.gate.request("posture", {"x": 1}), "deferred")
        self.assertIn("Deferred posture: screen locked", "\n".join(logs.output))
        h.run(600)
        self.assertEqual(h.shown(), [])
        h.locked = False
        h.run(LOCK_POLL)  # the unlock is noticed at the next lock check
        h.run(UNLOCK_DELAY - 2)
        self.assertEqual(h.shown(), [])
        with self.assertLogs(level="INFO") as logs:
            h.run(2)
        self.assertEqual(h.spawned[0][:2], ("posture", {"x": 1}))  # only the latest one
        self.assertIn("Showing deferred posture after unlock", "\n".join(logs.output))
        h.close_last()
        h.run(3600)
        self.assertEqual(len(h.spawned), 1)

    def test_lock_is_polled_not_every_second(self):
        checks = self.h.lock_checks
        self.h.run(60)
        self.assertLessEqual(self.h.lock_checks - checks, 60 // LOCK_POLL + 1)

    def test_open_window_defers_until_closed_plus_delay(self):
        h = self.h
        h.gate.request("posture", {})
        h.run(10)
        self.assertEqual(h.gate.request("eye_relax", {}), "deferred")
        h.run(300)  # posture still waits for input
        self.assertEqual(h.shown(), ["posture"])
        h.close_last()
        h.run(AFTER_CLOSE_DELAY - 1)
        self.assertEqual(h.shown(), ["posture"])
        h.run(2)
        self.assertEqual(h.shown(), ["posture", "eye_relax"])

    def test_same_type_as_open_window_is_dropped(self):
        h = self.h
        h.gate.request("posture", {})
        self.assertEqual(h.gate.request("posture", {}), "dropped")
        h.close_last()
        h.run(600)
        self.assertEqual(h.shown(), ["posture"])

    def test_manual_trigger_queues_behind_open_window_but_skips_close_delay(self):
        h = self.h
        h.gate.request("eye_relax", {})
        self.assertEqual(h.gate.request("water", {}, manual=True), "deferred")
        h.close_last()
        h.run(1)
        # Right after a close: a due reminder waits, a manual one does not.
        self.assertEqual(h.gate.request("stretch", {}, manual=True), "shown")
        self.assertEqual(h.gate.pending, "water")  # still queued, now behind stretch
        h.close_last()
        h.run(AFTER_CLOSE_DELAY + 1)
        self.assertEqual(h.shown(), ["eye_relax", "stretch", "water"])

    def test_suspend_defers_latest_missed_only(self):
        h = self.h
        h.missed = ("water", {"daily_goal_ml": 2000})
        h.now += 3 * 3600  # suspended for three hours
        h.locked = True  # and locked on resume
        h.gate.tick()
        self.assertEqual(h.gate.pending, "water")
        h.run(UNLOCK_DELAY + 30)
        self.assertEqual(h.shown(), [])
        h.locked = False
        h.run(LOCK_POLL + UNLOCK_DELAY + 1)
        self.assertEqual(h.shown(), ["water"])

    def test_deferred_dropped_when_paused_meanwhile(self):
        h = self.h
        h.gate.request("posture", {})
        h.gate.request("eye_relax", {})
        h.skip = "paused"
        h.close_last()
        h.run(AFTER_CLOSE_DELAY + 1)
        self.assertEqual(h.shown(), ["posture"])
        self.assertIsNone(h.gate.pending)

    def test_lock_check_failure_counts_as_unlocked(self):
        h = Harness()
        gate = ReminderGate(h.spawn, is_locked=lambda: 1 / 0, clock=lambda: h.now)
        self.assertEqual(gate.request("posture", {}), "shown")
        gate = ReminderGate(h.spawn, is_locked=lambda: None, clock=lambda: h.now)
        self.assertEqual(gate.request("eye_relax", {}), "shown")

    def test_request_on_unlock_triggers_unlock_delay(self):
        h = self.h
        h.locked = True
        h.run(LOCK_POLL)
        self.assertEqual(h.gate.request("posture", {}), "deferred")
        h.run(600)
        # Screen unlocked, advance clock so lock poll is due, and request() is called BEFORE tick() runs
        h.locked = False
        h.now += LOCK_POLL
        self.assertEqual(h.gate.request("eye_relax", {}), "deferred")
        h.run(UNLOCK_DELAY - 2)
        self.assertEqual(h.shown(), [])
        h.run(2)
        self.assertEqual(h.shown(), ["eye_relax"])

    def test_request_immediately_after_close_waits_close_delay(self):
        h = self.h
        h.gate.request("posture", {})
        self.assertEqual(h.shown(), ["posture"])
        # Window closed, and request() is called BEFORE tick() runs
        h.close_last()
        self.assertEqual(h.gate.request("eye_relax", {}), "deferred")
        h.run(AFTER_CLOSE_DELAY - 1)
        self.assertEqual(h.shown(), ["posture"])
        h.run(2)
        self.assertEqual(h.shown(), ["posture", "eye_relax"])

    def test_conference_defers_newest_and_shows_after_end_delay(self):
        h = self.h
        h.conference = True
        h.run(1)
        with self.assertLogs(level="INFO") as logs:
            self.assertEqual(h.gate.request("posture", {}), "deferred")
            self.assertEqual(h.gate.request("eye_relax", {"x": 1}), "deferred")
        self.assertIn("Deferred posture: video conference", "\n".join(logs.output))
        h.run(3600)
        self.assertEqual(h.shown(), [])
        h.conference = False
        h.run(CONFERENCE_END_DELAY - 1)
        self.assertEqual(h.shown(), [])
        with self.assertLogs(level="INFO") as logs:
            h.run(2)
        self.assertEqual(h.spawned[0][:2], ("eye_relax", {"x": 1}))  # newest wins
        self.assertIn("after the conference ended", "\n".join(logs.output))
        self.assertEqual(len(h.spawned), 1)

    def test_manual_trigger_shows_during_conference(self):
        h = self.h
        h.conference = True
        h.run(1)
        self.assertEqual(h.gate.request("water", {}, manual=True), "shown")
        self.assertEqual(h.shown(), ["water"])

    def test_conference_end_while_locked_waits_for_unlock(self):
        h = self.h
        h.conference = True
        h.run(1)
        h.gate.request("posture", {})
        h.locked = True
        h.run(LOCK_POLL)
        h.conference = False
        h.run(CONFERENCE_END_DELAY + 10)
        self.assertEqual(h.shown(), [])
        h.locked = False
        h.run(LOCK_POLL + UNLOCK_DELAY + 1)
        self.assertEqual(h.shown(), ["posture"])

    def test_paused_during_conference_still_drops(self):
        h = self.h
        h.conference = True
        h.run(1)
        h.gate.request("posture", {})
        h.skip = "paused"
        h.conference = False
        h.run(CONFERENCE_END_DELAY + 1)
        self.assertEqual(h.shown(), [])
        self.assertIsNone(h.gate.pending)

    def test_conference_check_failure_counts_as_no_conference(self):
        h = Harness()
        gate = ReminderGate(h.spawn, clock=lambda: h.now, in_conference=lambda: 1 / 0)
        self.assertEqual(gate.request("posture", {}), "shown")


from unittest.mock import patch
import src.session_lock as session_lock


class SessionLockTest(unittest.TestCase):
    def test_locked_if_any_probe_says_locked(self):
        with patch.object(session_lock, "Gio", True), \
             patch.object(session_lock, "_logind_locked", return_value=True), \
             patch.object(session_lock, "_screensaver_active", return_value=False):
            self.assertTrue(session_lock.is_locked())

        with patch.object(session_lock, "Gio", True), \
             patch.object(session_lock, "_logind_locked", return_value=False), \
             patch.object(session_lock, "_screensaver_active", return_value=True):
            self.assertTrue(session_lock.is_locked())

        with patch.object(session_lock, "Gio", True), \
             patch.object(session_lock, "_logind_locked", return_value=False), \
             patch.object(session_lock, "_screensaver_active", return_value=False):
            self.assertFalse(session_lock.is_locked())

        with patch.object(session_lock, "Gio", True), \
             patch.object(session_lock, "_logind_locked", return_value=False), \
             patch.object(session_lock, "_screensaver_active", side_effect=RuntimeError("no screensaver")):
            self.assertFalse(session_lock.is_locked())

        with patch.object(session_lock, "Gio", True), \
             patch.object(session_lock, "_logind_locked", side_effect=RuntimeError("no logind")), \
             patch.object(session_lock, "_screensaver_active", return_value=True):
            self.assertTrue(session_lock.is_locked())

        with patch.object(session_lock, "Gio", True), \
             patch.object(session_lock, "_logind_locked", side_effect=RuntimeError("fail")), \
             patch.object(session_lock, "_screensaver_active", side_effect=RuntimeError("fail")):
            self.assertIsNone(session_lock.is_locked())

        with patch.object(session_lock, "Gio", None):
            self.assertIsNone(session_lock.is_locked())


class LibraryTest(unittest.TestCase):
    def test_old_posture_wait_duration_is_removed(self):
        from src.library import fill_defaults, page_settings
        config = fill_defaults({"global_interval": 60, "posture": {"enabled": True, "reminders": [0], "wait_duration": 3.0}})
        self.assertNotIn("wait_duration", config["posture"])
        self.assertEqual(page_settings("posture", {"wait_duration": 3}).get("wait_duration"), 3)  # harmless if passed


try:
    import src.scheduler as scheduler
except ImportError:  # apscheduler missing: run with the app's venv
    scheduler = None


@unittest.skipIf(scheduler is None, "needs apscheduler (use the venv python)")
class FindMissedTest(unittest.TestCase):
    def setUp(self):
        scheduler.current_config = {
            "global_interval": 60,
            "posture": {"enabled": True, "reminders": [10, 30, 50]},
            "eye_relax": {"enabled": True, "reminders": [0, 20, 40]},
            "water": {"enabled": False, "reminders": [45]},
        }

    def ts(self, h, m, s=0):
        return datetime(2026, 10, 29, h, m, s).timestamp()

    def test_latest_due_in_gap(self):
        self.assertEqual(scheduler.find_missed(self.ts(8, 5), self.ts(11, 35))[0], "posture")   # 11:30
        self.assertEqual(scheduler.find_missed(self.ts(8, 5), self.ts(11, 45))[0], "eye_relax")  # 11:40, water off

    def test_nothing_due_in_short_gap(self):
        self.assertIsNone(scheduler.find_missed(self.ts(11, 41), self.ts(11, 49, 30)))


if __name__ == "__main__":
    unittest.main()
