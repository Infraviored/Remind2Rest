"""Webhook events beyond conference and drink. Nothing here reaches the live daemon socket or a URL:
send_event and the socket helpers are patched."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, PropertyMock, patch

sys.modules.setdefault("webview", MagicMock())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import overlay, scheduler
from src.activity import ActivityTracker, SnapshotSender
from src.gate import ReminderGate, UNLOCK_DELAY, AFTER_CLOSE_DELAY


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class ActivityTest(unittest.TestCase):
    def run_for(self, tracker, clock, seconds):
        for _ in range(seconds):
            clock.advance(1)
            tracker.tick()

    def test_counts_unlocked_time_only(self):
        c = Clock(datetime(2026, 11, 12, 10, 0, 0))
        t = ActivityTracker(c)
        self.run_for(t, c, 120)
        t.set_locked(True)
        self.run_for(t, c, 300)
        t.set_locked(False)
        self.run_for(t, c, 60)
        self.assertEqual(t.minutes, 3)

    def test_starts_locked(self):
        c = Clock(datetime(2026, 11, 12, 10, 0, 0))
        t = ActivityTracker(c, locked=True)
        self.run_for(t, c, 120)
        self.assertEqual(t.minutes, 0)

    def test_suspend_gap_is_excluded(self):
        c = Clock(datetime(2026, 11, 12, 10, 0, 0))
        t = ActivityTracker(c)
        self.run_for(t, c, 60)
        c.advance(3600)  # suspended
        t.tick()
        self.run_for(t, c, 60)
        self.assertEqual(t.minutes, 2)

    def test_midnight_splits_and_resets(self):
        c = Clock(datetime(2026, 11, 12, 23, 59, 0))
        t = ActivityTracker(c)
        self.run_for(t, c, 30)
        self.assertEqual(t.minutes, 0)
        self.run_for(t, c, 30 + 90)  # now 00:01:30
        self.assertEqual(t.minutes, 1)  # 90 s of the new day

    def test_midnight_split_in_one_tick(self):
        c = Clock(datetime(2026, 11, 12, 23, 59, 50))
        t = ActivityTracker(c)
        c.advance(40)  # one tick across midnight: 30 s count for the new day
        t.tick()
        self.assertEqual(t._seconds, 30)

    def test_suspend_across_midnight_is_excluded(self):
        c = Clock(datetime(2026, 11, 12, 23, 0, 0))
        t = ActivityTracker(c)
        c.advance(3630)  # suspended until 00:00:30 on the new day
        t.tick()
        self.assertEqual(t.minutes, 0)
        self.assertEqual(t._seconds, 0)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.t = 1000.0
        self.snap = {"paused_until": None, "conference": "off", "today_ml": 0, "coffee_ml": 0, "x": 1}
        self.sent = []
        self.sender = SnapshotSender(lambda: dict(self.snap), self.sent.append, clock=lambda: self.t)

    def run_for(self, seconds):
        for _ in range(seconds):
            self.t += 1
            self.sender.tick()

    def test_first_tick_sends_then_every_15_min(self):
        self.sender.tick()
        self.assertEqual(len(self.sent), 1)
        self.snap["x"] = 2  # not watched
        self.run_for(899)
        self.assertEqual(len(self.sent), 1)
        self.run_for(2)
        self.assertEqual(len(self.sent), 2)

    def test_change_sends_but_at_most_once_a_minute(self):
        self.sender.tick()
        self.run_for(10)
        self.snap["conference"] = "on"
        self.run_for(10)
        self.assertEqual(len(self.sent), 1)  # too soon
        self.run_for(45)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1]["conference"], "on")
        self.snap["today_ml"] = 300
        self.run_for(30)
        self.assertEqual(len(self.sent), 2)
        self.run_for(40)
        self.assertEqual(len(self.sent), 3)
        self.run_for(300)  # nothing changed
        self.assertEqual(len(self.sent), 3)

    def test_send_failure_is_swallowed(self):
        def boom(_):
            raise RuntimeError("x")
        SnapshotSender(dict, boom, clock=lambda: 0).tick()

    def test_send_failure_leaves_unsent_for_retry(self):
        calls = []
        def send_fn(s):
            calls.append(s)
            if len(calls) == 1:
                raise RuntimeError("transient")
        sender = SnapshotSender(dict, send_fn, clock=lambda: 1000)
        self.assertFalse(sender.tick())
        sender._checked_at = None
        self.assertTrue(sender.tick())
        self.assertEqual(len(calls), 2)


class GateEventTest(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000.0
        self.locked = False
        self.events = []
        self.skip = None
        self.missed = None
        self.procs = []
        self.gate = ReminderGate(self.spawn, is_locked=lambda: self.locked, clock=lambda: self.now,
                                 find_missed=lambda a, b: self.missed, skip_reason=lambda: self.skip,
                                 on_event=lambda t, **f: self.events.append((t, f)))
        self.gate.tick()

    def spawn(self, module, settings):
        p = MagicMock()
        p.poll.return_value = None
        self.procs.append(p)
        return p

    def run_s(self, seconds):
        for _ in range(seconds):
            self.now += 1
            self.gate.tick()

    def types(self):
        return [t for t, _ in self.events]

    def test_shown_scheduled_and_closed(self):
        self.gate.request("water", {})
        self.assertEqual(self.events[-1], ("reminder_shown", {"module": "water", "trigger": "scheduled"}))
        self.run_s(40)
        self.procs[0].poll.return_value = 0
        self.run_s(1)
        self.assertEqual(self.events[-1], ("reminder_closed", {"module": "water", "duration_s": 41}))

    def test_manual_is_now_and_snooze_trigger_passes(self):
        self.gate.request("water", {}, manual=True)
        self.assertEqual(self.events[-1][1]["trigger"], "now")
        self.procs[0].poll.return_value = 0
        self.run_s(1)
        self.gate.request("posture", {}, manual=True, trigger="after_snooze")
        self.assertEqual(self.events[-1][1]["trigger"], "after_snooze")

    def test_deferred_trigger_and_lock_events(self):
        self.locked = True
        self.run_s(6)
        self.assertEqual(self.events[-1], ("screen", {"state": "locked"}))
        self.gate.request("water", {})
        self.assertNotIn("reminder_shown", self.types())
        self.locked = False
        self.run_s(UNLOCK_DELAY + 10)
        self.assertIn(("screen", {"state": "unlocked"}), self.events)
        self.assertEqual(self.events[-1], ("reminder_shown", {"module": "water", "trigger": "deferred"}))

    def test_deferred_replaced_emits_skipped(self):
        self.locked = True
        self.run_s(6)
        self.gate.request("water", {})
        self.assertEqual(self.gate.pending, "water")
        self.gate.request("posture", {})
        self.assertEqual(self.gate.pending, "posture")
        self.assertIn(("reminder_skipped", {"module": "water", "reason": "dropped"}), self.events)

    def test_deferred_dropped_while_paused(self):
        self.locked = True
        self.run_s(6)
        self.gate.request("water", {})
        self.locked = False
        self.skip = "paused"
        self.run_s(UNLOCK_DELAY + 10)
        self.assertEqual(self.events[-1], ("reminder_skipped", {"module": "water", "reason": "paused"}))

    def test_same_reminder_open_is_dropped(self):
        self.gate.request("water", {})
        self.gate.request("water", {})
        self.assertEqual(self.events[-1], ("reminder_skipped", {"module": "water", "reason": "dropped"}))

    def test_suspend_event(self):
        self.now += 500
        self.gate.tick()
        self.assertIn(("suspend", {"gap_s": 500}), self.events)

    def test_failing_sink_does_not_break_gate(self):
        def boom(*a, **k):
            raise RuntimeError("x")
        g = ReminderGate(self.spawn, clock=lambda: self.now, on_event=boom)
        self.assertEqual(g.request("water", {}), "shown")


class SchedulerEventTest(unittest.TestCase):
    def setUp(self):
        p = patch.object(scheduler.conference, "send_event")
        self.send = p.start()
        self.addCleanup(p.stop)
        self.addCleanup(setattr, scheduler, "paused_until", scheduler.paused_until)
        self.addCleanup(setattr, scheduler, "current_config", scheduler.current_config)
        scheduler._snoozes.clear()
        self.addCleanup(scheduler._snoozes.clear)

    def events(self):
        return [(c.args[0], c.kwargs) for c in self.send.call_args_list]

    def test_pause_and_resume(self):
        scheduler.pause(10)
        name, fields = self.events()[-1]
        self.assertEqual(name, "pause")
        self.assertRegex(fields["paused_until"], r"\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        scheduler.resume()
        self.assertEqual(self.events()[-1], ("pause", {"paused_until": None}))

    def test_snooze_and_dropout(self):
        scheduler.current_config = {"global_interval": 60, "water": {"enabled": True, "reminders": [0]}}
        now = datetime(2026, 11, 12, 10, 0, 0)
        scheduler.snooze("water", now)
        self.assertEqual(self.events()[-1], ("reminder_snoozed", {"module": "water", "minutes": 30, "count": 1}))
        scheduler.snooze("water", now)
        self.assertEqual(self.events()[-1], ("reminder_skipped", {"module": "water", "reason": "dropped"}))

    def test_paused_skip(self):
        scheduler.paused_until = datetime.now() + timedelta(minutes=5)
        scheduler.trigger_reminder("water", {})
        self.assertEqual(self.events()[-1], ("reminder_skipped", {"module": "water", "reason": "paused"}))

    def test_goal_skip(self):
        scheduler.log_goal_skipped("water", {}, today=3000)
        self.assertEqual(self.events()[-1], ("reminder_skipped", {"module": "water", "reason": "goal_reached"}))

    def test_rating(self):
        scheduler.report_rating(4)
        self.assertEqual(self.events()[-1], ("posture_rating", {"rating": 4}))
        for bad in (0, 6, "3", True):
            with self.assertRaises(ValueError):
                scheduler.report_rating(bad)

    def test_send_failure_never_raises(self):
        self.send.side_effect = RuntimeError("x")
        scheduler.resume()

    def test_gate_screen_event_feeds_activity_and_webhook(self):
        with patch.object(scheduler.activity, "set_locked") as set_locked:
            scheduler._gate_event("screen", state="locked")
        set_locked.assert_called_once_with(True)
        self.assertEqual(self.events()[-1], ("screen", {"state": "locked"}))

    def test_start_activity_starts_clean_when_locked(self):
        with patch.object(scheduler, "is_locked", return_value=True):
            scheduler.start_activity()
        self.assertTrue(scheduler.activity._locked)
        self.assertEqual(scheduler.activity._seconds, 0.0)

    def test_snapshot_fields(self):
        scheduler.current_config = {"global_interval": 60, "water": {"enabled": True, "reminders": [30]},
                                    "posture": {"enabled": False, "reminders": [0]}}
        scheduler.paused_until = None
        with patch.object(scheduler, "drinks_today_ml", return_value={"water": 500, "coffee": 200}), \
             patch.object(scheduler, "water_today_ml", return_value=700), \
             patch.object(ActivityTracker, "minutes", new_callable=PropertyMock, return_value=42):
            snap = scheduler.build_snapshot()
        self.assertEqual((snap["today_ml"], snap["coffee_ml"], snap["conference"]), (700, 200, "off"))
        self.assertIsNone(snap["paused_until"])
        self.assertEqual(list(snap["next"]), ["water"])
        self.assertEqual(snap["active_min_today"], 42)


class RatingOverlayTest(unittest.TestCase):
    def test_save_rating_tells_daemon(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(overlay, "RATINGS_FILE_PATH", os.path.join(d, "r.txt")), \
             patch.object(overlay.OverlayApi, "_tell_daemon") as tell:
            api = overlay.OverlayApi.__new__(overlay.OverlayApi)
            api.save_rating(4)
        tell.assert_called_once_with("RATING 4", "rating")

    def test_invalid_rating_is_not_sent(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(overlay, "RATINGS_FILE_PATH", os.path.join(d, "r.txt")), \
             patch.object(overlay.OverlayApi, "_tell_daemon") as tell:
            api = overlay.OverlayApi.__new__(overlay.OverlayApi)
            with self.assertRaises(ValueError):
                api.save_rating(9)
        tell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
