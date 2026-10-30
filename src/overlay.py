import os
import sys
import logging
import threading
from datetime import datetime
from pathlib import Path

import time
import webview

from src.config import RATINGS_FILE_PATH, WATER_LOG_PATH
from src.logs import TIME_FORMAT, MAX_WATER_ML, read_ratings, water_today_ml
from src.library import LIBRARY
from src.session_lock import is_locked

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class OverlayApi:
    """Methods the reminder page calls as window.pywebview.api.<name>(); see reminders/README.md."""

    def __init__(self, module, settings):
        # Underscore names are not exposed to the page.
        self._module = module
        self._settings = settings
        self._window = None
        self._closed = False

    def get_context(self):
        return {"type": self._module, "settings": self._settings,
                "now": datetime.now().isoformat(timespec="seconds")}

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._window:
            self._window.destroy()

    def snooze(self, minutes):
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float, str)):
            raise ValueError(f"Minutes must be a number, got {minutes!r}")
        try:
            mins = float(minutes)
        except (ValueError, OverflowError):
            raise ValueError(f"Minutes must be a number, got {minutes!r}") from None
        if not (0 < mins < 1440):
            raise ValueError(f"Minutes must be between 0 and 1440, got {minutes!r}")
        self._window.hide()

        def wake():
            def wait_for_unlock():
                while not self._closed and is_locked():
                    time.sleep(5)
                if self._closed:
                    return
                time.sleep(45)
                if is_locked():
                    wait_for_unlock()
                    return
                if not self._closed:
                    self._window.show()
                    try:
                        self._window.evaluate_js("window.dispatchEvent(new CustomEvent('remind2rest:resume'))")
                    except Exception:
                        pass

            if is_locked():
                threading.Thread(target=wait_for_unlock, daemon=True).start()
            else:
                self._window.show()
                try:
                    self._window.evaluate_js("window.dispatchEvent(new CustomEvent('remind2rest:resume'))")
                except Exception:
                    pass

        timer = threading.Timer(mins * 60, wake)
        timer.daemon = True
        timer.start()

    def save_rating(self, rating):
        if isinstance(rating, bool) or not isinstance(rating, (int, float, str)):
            raise ValueError(f"Rating must be 1-5, got {rating!r}")
        try:
            r = int(rating)
        except (ValueError, OverflowError):
            raise ValueError(f"Rating must be 1-5, got {rating!r}") from None
        if r != float(rating) or not 1 <= r <= 5:
            raise ValueError(f"Rating must be 1-5, got {rating!r}")
        os.makedirs(os.path.dirname(RATINGS_FILE_PATH), exist_ok=True)
        with open(RATINGS_FILE_PATH, "a") as file:
            file.write(f"{datetime.now().strftime(TIME_FORMAT)} - Rating: {r}\n")

    def get_ratings(self, days):
        if isinstance(days, bool) or not isinstance(days, (int, float, str)):
            raise ValueError(f"Days must be a number, got {days!r}")
        try:
            d = float(days)
        except (ValueError, OverflowError):
            raise ValueError(f"Days must be a number, got {days!r}") from None
        if d <= 0 or d > 3650:
            return []
        return read_ratings(d)

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
    # The window is gone, but the pywebview thread that answers the page's close() call can still
    # wait in evaluate_js for a main loop that has ended. It is not a daemon thread, so a normal exit
    # would wait for it forever, and the daemon would count this reminder as open. Exit hard instead.
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
