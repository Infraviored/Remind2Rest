import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.modules.setdefault("webview", MagicMock())

from src import logs, overlay, scheduler


class DrinksLogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "water_log.txt")
        for target in (logs, overlay):
            p = patch.object(target, "WATER_LOG_PATH", self.path)
            p.start()
            self.addCleanup(p.stop)
        # log_water tells the live daemon; the tests must not reach it.
        p = patch.object(overlay.OverlayApi, "_tell_daemon_drink")
        self.tell = p.start()
        self.addCleanup(p.stop)
        logs._water_cache.update(mtime_ns=None, size=None, day=None, totals=None)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, *lines):
        with open(self.path, "w") as f:
            f.write("".join(line + "\n" for line in lines))

    def test_counts_water_and_coffee_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.write(f"{today} 08:00:00", f"{today} 09:00:00 300", f"{today} 10:00:00 200 coffee",
                   f"{today} 11:00:00 100 tea", "2000-01-01 10:00:00 500 coffee")
        self.assertEqual(logs.drinks_today_ml(), {"water": 550, "coffee": 200})
        self.assertEqual(logs.water_today_ml(), 750)

    def test_log_water_writes_kind_and_returns_totals(self):
        api = overlay.OverlayApi.__new__(overlay.OverlayApi)
        api._settings = {"daily_goal_ml": 1500, "cup_sizes": []}
        api.log_water(300)
        state = api.log_water(200, "coffee")
        with open(self.path) as f:
            lines = f.read().splitlines()
        self.assertTrue(lines[0].endswith(" 300"))
        self.assertTrue(lines[1].endswith(" 200 coffee"))
        self.assertEqual(state["today_ml"], 500)
        self.assertEqual(state["coffee_ml"], 200)
        self.assertEqual(state["goal_ml"], 1500)
        self.assertEqual(state["glasses"], [200, 300, 500])
        self.assertEqual(state["cups"], [])
        self.assertEqual([c.args for c in self.tell.call_args_list], [("water", 300), ("coffee", 200)])
        with self.assertRaises(ValueError):
            api.log_water(200, "beer")

    def test_report_drink_sends_totals(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.write(f"{today} 09:00:00 300", f"{today} 10:00:00 200 coffee")
        with patch.object(scheduler, "current_config", {"water": {"daily_goal_ml": 1800}}), \
             patch.object(scheduler.conference, "send_event") as send:
            scheduler.report_drink("coffee", 200)
            with self.assertRaises(ValueError):
                scheduler.report_drink("beer", 200)
            with self.assertRaises(ValueError):
                scheduler.report_drink("water", 0)
            with self.assertRaises(ValueError):
                scheduler.report_drink("water", -1)
            with self.assertRaises(ValueError):
                scheduler.report_drink("water", 2001)
        send.assert_called_once_with("drink", kind="coffee", ml=200, today_ml=500, coffee_ml=200, goal_ml=1800)

    def test_drink_sizes(self):
        self.assertEqual(overlay.drink_sizes(None, [1, 2]), [1, 2])
        self.assertEqual(overlay.drink_sizes(["250", 0, True, "x", 5000, 330, 100, 150, 200], []), [250, 330, 100, 150])


if __name__ == "__main__":
    unittest.main()
