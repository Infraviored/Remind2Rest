import unittest
from datetime import datetime, timedelta
from unittest import mock

from src import scheduler
from src.library import fill_defaults


class SnoozeTest(unittest.TestCase):
    def setUp(self):
        scheduler._snoozes.clear()
        self._config = scheduler.current_config
        # A 120 min cycle: water every 40 min, airing once (at :60 of the cycle).
        scheduler.current_config = {"global_interval": 120,
                                    "water": {"enabled": True, "reminders": [0, 40, 80]},
                                    "airing": {"enabled": True, "reminders": [60]},
                                    "posture": {"enabled": True, "reminders": []},
                                    "eye_relax": {"enabled": False, "reminders": [10]}}

    def tearDown(self):
        scheduler._snoozes.clear()
        scheduler.current_config = self._config

    def test_first_later_comes_back_halfway_to_the_next_regular_time(self):
        # 10:05; water's next regular time is 10:40 (35 min), airing's 11:00 (55 min).
        now = datetime(2026, 11, 4, 10, 5)
        self.assertEqual(scheduler.snooze("water", now), 17.5)
        self.assertEqual(scheduler.snooze("airing", now), 27.5)
        self.assertTrue(scheduler.snoozed("water"))

    def test_a_time_due_this_second_counts_as_the_next_periods(self):
        now = datetime(2026, 11, 4, 11, 0)  # airing is due right now; the next one is 13:00
        self.assertEqual(scheduler.minutes_to_next_regular("airing", now), 120)

    def test_snoozed_reminder_comes_back_once(self):
        now = datetime(2026, 11, 4, 10, 5)
        scheduler.snooze("water", now)
        self.assertFalse(scheduler.scheduled_reminder_due("water"))
        self.assertEqual(scheduler.due_snoozes(now + timedelta(minutes=17)), [])
        self.assertEqual(scheduler.due_snoozes(now + timedelta(minutes=17.5)), ["water"])
        self.assertEqual(scheduler.due_snoozes(now + timedelta(minutes=18)), [])
        self.assertFalse(scheduler.snoozed("water"))

    def test_second_later_drops_it_until_the_next_regular_time(self):
        now = datetime(2026, 11, 4, 10, 5)
        scheduler.snooze("water", now)
        back = now + timedelta(minutes=17.5)
        scheduler.due_snoozes(back)
        self.assertEqual(scheduler.snooze("water", back), 17.5)  # 10:22:30 -> 10:40
        self.assertFalse(scheduler.snoozed("water"))
        self.assertEqual(scheduler.due_snoozes(back + timedelta(hours=1)), [])
        # The regular time shows it, and a Later there is a first Later again.
        self.assertTrue(scheduler.scheduled_reminder_due("water"))
        self.assertEqual(scheduler.snooze("water", datetime(2026, 11, 4, 10, 40)), 20)

    def test_later_shortly_before_the_next_regular_time_drops_it_at_once(self):
        now = datetime(2026, 11, 4, 10, 32)  # 8 min before 10:40
        self.assertEqual(scheduler.snooze("water", now), 8)
        self.assertFalse(scheduler.snoozed("water"))

    def test_type_without_regular_time_comes_back_once_after_ten_minutes(self):
        now = datetime(2026, 11, 4, 10, 5)
        self.assertEqual(scheduler.snooze("posture", now), 10)  # on, but no times: shown by hand
        scheduler.due_snoozes(now + timedelta(minutes=10))
        self.assertEqual(scheduler.snooze("posture", now + timedelta(minutes=10)), 0)
        self.assertFalse(scheduler.snoozed("posture"))
        # Shown by hand again later: a first Later again.
        with mock.patch.object(scheduler.gate, "request", return_value="shown"):
            scheduler.launch_reminder("posture", {})
        self.assertEqual(scheduler.snooze("posture", now + timedelta(hours=2)), 10)

    def test_later_on_a_demo_of_a_turned_off_type_snoozes_nothing(self):
        self.assertEqual(scheduler.snooze("eye_relax", datetime(2026, 11, 4, 10, 5)), 0)
        self.assertFalse(scheduler.snoozed("eye_relax"))
        self.assertNotIn("eye_relax", scheduler._snoozes)

    def test_unknown_type_and_other_types_are_not_affected(self):
        with self.assertRaises(ValueError):
            scheduler.snooze("nope")
        scheduler.snooze("water", datetime(2026, 11, 4, 10, 5))
        self.assertTrue(scheduler.scheduled_reminder_due("eye_relax"))
        self.assertFalse(scheduler.snoozed("airing"))

    def test_old_snooze_minutes_setting_is_removed(self):
        config = fill_defaults({"water": {"snooze_minutes": 30}, "airing": {"snooze_minutes": 30}})
        self.assertNotIn("snooze_minutes", config["water"])
        self.assertNotIn("snooze_minutes", config["airing"])


if __name__ == "__main__":
    unittest.main()
