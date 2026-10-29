import os
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

import webview

from src.config import RATINGS_FILE_PATH, WATER_LOG_PATH
from src.library import LIBRARY

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def read_ratings(days):
    """Posture ratings of the last `days` days, oldest first."""
    since = datetime.now() - timedelta(days=days)
    ratings = []
    if not os.path.exists(RATINGS_FILE_PATH):
        return ratings
    with open(RATINGS_FILE_PATH, "r") as file:
        for line in file:
            try:
                time_str, rating_str = line.strip().split(" - Rating: ")
                timestamp = datetime.strptime(time_str, TIME_FORMAT)
                rating = int(rating_str)
            except ValueError:
                continue
            if timestamp >= since:
                ratings.append((timestamp, rating))
    ratings.sort()
    return [{"time": t.strftime(TIME_FORMAT), "rating": r} for t, r in ratings]


# Lines before the switch to amounts hold only a timestamp; they count as one 250 ml glass.
LEGACY_GLASS_ML = 250
MAX_WATER_ML = 2000


def water_today_ml():
    """Sum of the water logged today, in ml."""
    if not os.path.exists(WATER_LOG_PATH):
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0
    with open(WATER_LOG_PATH, "r") as file:
        for line in file:
            if not line.startswith(today):
                continue
            # "YYYY-MM-DD HH:MM:SS <ml>" or, in old logs, "YYYY-MM-DD HH:MM:SS"
            parts = line.split()
            if len(parts) == 2:
                total += LEGACY_GLASS_ML
            elif len(parts) == 3 and parts[2].isdigit():
                total += int(parts[2])
    return total


class OverlayApi:
    """Methods the reminder page calls as window.pywebview.api.<name>(); see reminders/README.md."""

    def __init__(self, module, settings):
        # Underscore names are not exposed to the page.
        self._module = module
        self._settings = settings
        self._window = None

    def get_context(self):
        return {"type": self._module, "settings": self._settings,
                "now": datetime.now().isoformat(timespec="seconds")}

    def close(self):
        self._window.destroy()

    def snooze(self, minutes):
        self._window.hide()
        timer = threading.Timer(float(minutes) * 60, self._window.show)
        timer.daemon = True
        timer.start()

    def save_rating(self, rating):
        rating = int(rating)
        if not 1 <= rating <= 5:
            raise ValueError(f"Rating must be 1-5, got {rating}")
        with open(RATINGS_FILE_PATH, "a") as file:
            file.write(f"{datetime.now().strftime(TIME_FORMAT)} - Rating: {rating}\n")

    def get_ratings(self, days):
        return read_ratings(float(days))

    def log_water(self, ml):
        if isinstance(ml, bool) or not isinstance(ml, (int, float, str)):
            raise ValueError(f"Amount must be a whole number of ml, got {ml!r}")
        try:
            amount = int(ml)
        except (ValueError, OverflowError):
            raise ValueError(f"Amount must be a whole number of ml, got {ml!r}") from None
        if amount != float(ml) or not 0 < amount <= MAX_WATER_ML:
            raise ValueError(f"Amount must be 1-{MAX_WATER_ML} ml, got {ml!r}")
        os.makedirs(os.path.dirname(WATER_LOG_PATH), exist_ok=True)
        with open(WATER_LOG_PATH, "a") as file:
            file.write(f"{datetime.now().strftime(TIME_FORMAT)} {amount}\n")
        return self.get_water_today()

    def get_water_today(self):
        return {"today_ml": water_today_ml(), "goal_ml": self._settings.get("daily_goal_ml", 2000)}


def show_reminder(module, settings):
    """Show reminders/<module>/reminder.html fullscreen until the page calls close()."""
    if os.name != "nt":
        # Lets GNOME match the window to Remind2Rest.desktop (StartupWMClass) for the dock icon.
        try:
            from gi.repository import GLib
            GLib.set_prgname("Remind2Rest")
            GLib.set_application_name("Remind2Rest")
        except ImportError:
            pass
    page = Path(script_dir, "reminders", module, "reminder.html")
    logging.info(f"Showing {module} reminder ({page})")
    api = OverlayApi(module, settings)
    api._window = webview.create_window(
        LIBRARY[module]["title"],
        url=page.as_uri(),
        js_api=api,
        fullscreen=True,
        frameless=True,
        on_top=True,
        focus=True,
        background_color="#000000",
    )
    webview.start()
