"""Text and picture of the Windows tray icon (no icon is shown: only the pure helpers run)."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import src.tray_win as tray
except ImportError:  # pystray or apscheduler missing: run with the app's venv on Windows
    tray = None


def status(**kw):
    base = {"running": True, "next_reminder": "posture", "next_title": "Posture", "time_to_next": "09:19",
            "conference": {"active": False, "reasons": []}, "types": [{"key": "posture", "title": "Posture"}]}
    base.update(kw)
    return base


@unittest.skipIf(tray is None, "needs pystray (Windows venv)")
class TrayTextTest(unittest.TestCase):
    def test_minutes_round_up(self):
        self.assertEqual(tray.minutes_left(status(time_to_next="09:19")), 10)
        self.assertEqual(tray.minutes_left(status(time_to_next="10:00")), 10)
        self.assertEqual(tray.minutes_left(status(time_to_next="00:00")), 1)
        self.assertIsNone(tray.minutes_left(status(next_reminder=None)))
        self.assertIsNone(tray.minutes_left(status(time_to_next="garbage")))

    def test_headline(self):
        self.assertEqual(tray.headline(status()), "Posture in 10 min")
        self.assertEqual(tray.headline(status(next_reminder=None)), "No reminders enabled")
        self.assertEqual(tray.headline(status(paused_until="2026-11-02T14:30:00")), "Paused until 14:30")
        self.assertEqual(tray.headline(status(conference={"active": True, "reasons": ["camera"]})),
                         "In a call: Posture waits until it ends")

    def test_water_line(self):
        self.assertIsNone(tray.water_line(status()))
        self.assertEqual(tray.water_line(status(water_today_ml=1200, water_goal_ml=2000)),
                         "Water today: 1200 / 2000 ml")

    def test_badge_text(self):
        self.assertEqual(tray.badge_text(9), "9")
        self.assertEqual(tray.badge_text(99), "99")
        self.assertEqual(tray.badge_text(150), "2h")

    def test_icons(self):
        from PIL import Image
        logo = Image.new("RGBA", (tray.SIZE, tray.SIZE), (10, 200, 10, 255))
        self.assertIs(tray.render_icon(status(next_reminder=None), logo), logo)
        for s in (status(), status(time_to_next="59:00"), status(paused_until="2026-11-02T14:30:00")):
            img = tray.render_icon(s, logo)
            self.assertEqual(img.size, (tray.SIZE, tray.SIZE))
            self.assertEqual(img.mode, "RGBA")
            # The logo stays untouched except for the small badge in the bottom right corner.
            self.assertEqual(img.getpixel((5, 5)), (10, 200, 10, 255))
            self.assertNotEqual(img.getpixel((tray.SIZE - 6, tray.SIZE - tray.BADGE_HEIGHT // 2)), (10, 200, 10, 255))
        self.assertEqual(logo.getpixel((tray.SIZE - 6, tray.SIZE - 6)), (10, 200, 10, 255))  # not drawn on


if __name__ == "__main__":
    unittest.main()
