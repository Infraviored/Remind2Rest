import unittest
from datetime import datetime, timedelta

from src import scheduler


class SnoozeTest(unittest.TestCase):
    def setUp(self):
        scheduler._snoozes.clear()
        self._config = scheduler.current_config
        scheduler.current_config = {"water": {"enabled": True, "snooze_minutes": 30},
                                    "airing": {"enabled": True}}

    def tearDown(self):
        scheduler._snoozes.clear()
        scheduler.current_config = self._config

    def test_each_later_in_a_row_doubles_up_to_the_maximum(self):
        now = datetime(2026, 11, 4, 10, 0)
        self.assertEqual([scheduler.snooze("water", now) for _ in range(5)], [30, 60, 120, 240, 240])

    def test_type_default_and_unknown_type(self):
        # airing has no value in the config: the library default (30) applies.
        self.assertEqual(scheduler.snooze("airing"), 30)
        with self.assertRaises(ValueError):
            scheduler.snooze("nope")

    def test_scheduled_time_is_left_out_while_snoozed_and_comes_back_once(self):
        now = datetime(2026, 11, 4, 10, 0)
        scheduler.snooze("water", now)
        self.assertTrue(scheduler.snoozed("water"))
        self.assertFalse(scheduler.scheduled_reminder_due("water"))
        self.assertEqual(scheduler.due_snoozes(now + timedelta(minutes=29)), [])
        self.assertEqual(scheduler.due_snoozes(now + timedelta(minutes=30)), ["water"])
        self.assertEqual(scheduler.due_snoozes(now + timedelta(minutes=31)), [])
        self.assertFalse(scheduler.snoozed("water"))
        # Later again on the reminder that came back: the next step.
        self.assertEqual(scheduler.snooze("water", now + timedelta(minutes=30)), 60)

    def test_count_starts_again_at_the_next_scheduled_reminder(self):
        now = datetime(2026, 11, 4, 10, 0)
        scheduler.snooze("water", now)
        scheduler.due_snoozes(now + timedelta(minutes=30))
        self.assertTrue(scheduler.scheduled_reminder_due("water"))
        self.assertEqual(scheduler.snooze("water", now + timedelta(minutes=40)), 30)

    def test_other_types_are_not_affected(self):
        scheduler.snooze("water")
        self.assertTrue(scheduler.scheduled_reminder_due("eye_relax"))
        self.assertFalse(scheduler.snoozed("airing"))


if __name__ == "__main__":
    unittest.main()
