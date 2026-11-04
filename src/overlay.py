import os
import sys
import json
import logging
import socket
import threading
from datetime import datetime
from pathlib import Path

import time
import webview

from src.config import ADDR, SOCKET_FAMILY, RATINGS_FILE_PATH, WATER_LOG_PATH
from src.logs import TIME_FORMAT, MAX_WATER_ML, read_ratings, water_today_ml
from src.library import LIBRARY
from src.session_lock import is_locked

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# On Windows the window is created hidden and shown once the page has built its first view
# (common.js calls ready()), so the user never sees a black or half-built screen. A page that never
# calls ready() is shown this many seconds after it was asked to load.
HIDE_UNTIL_READY = os.name == "nt"
REVEAL_FALLBACK = 4.0
BLANK_PAGE = "<html><body style='background:#000'></body></html>"


def page_uri(module):
    return Path(script_dir, "reminders", module, "reminder.html").as_uri()


def bring_to_front(window):
    """Windows only lets the foreground app hand out focus. A short Alt press counts as user input
    and lifts that lock for this process, so Escape and the page's keys work without a click."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        hwnd = window.native.Handle.ToInt64()
        VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        if not user32.SetForegroundWindow(hwnd):
            logging.warning("Could not bring the reminder window to the front")
    except Exception as e:
        logging.warning(f"Could not bring the reminder window to the front: {e}")


class OverlayApi:
    """Methods the reminder page calls as window.pywebview.api.<name>(); see reminders/README.md."""

    def __init__(self, module, settings, warm=False):
        # Underscore names are not exposed to the page.
        self._module = module
        self._settings = settings
        self._window = None
        self._closed = False
        self._revealed = False
        self._warm = warm
        self._requested_at = time.monotonic()
        self._shown_at = None

    def get_context(self):
        return {"type": self._module, "settings": self._settings,
                "now": datetime.now().isoformat(timespec="seconds")}

    def ready(self):
        """The page has built its first view (called by common.js)."""
        self._reveal("page ready")

    def _reveal(self, why):
        if self._revealed or self._closed or self._module is None:
            return
        self._revealed = True
        if HIDE_UNTIL_READY:
            self._window.show()
            bring_to_front(self._window)
        self._shown_at = time.monotonic()
        logging.info(f"{self._module} visible {self._shown_at - self._requested_at:.2f} s after the request "
                     f"({'warm' if self._warm else 'cold'} start, {why})")

    def _reveal_later(self):
        timer = threading.Timer(REVEAL_FALLBACK, self._reveal, args=("page never called ready()",))
        timer.daemon = True
        timer.start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._shown_at is not None:
            logging.info(f"{self._module} closed after {time.monotonic() - self._shown_at:.0f} s")
        if self._window:
            self._window.destroy()

    def snooze(self, minutes=None):
        """Later: the window closes and the daemon brings this reminder back halfway to its next
        regular time, or lets it drop out on a second Later (see scheduler.snooze), so other
        reminders are not held back meanwhile. Without a daemon the window hides and comes back
        after `minutes` (default 10) itself."""
        if self._module is not None and self._snooze_via_daemon():
            self.close()
            return
        self._snooze_here(10 if minutes is None else minutes)

    def _snooze_via_daemon(self):
        try:
            with socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                s.connect(ADDR)
                s.sendall(f"SNOOZE {self._module}".encode())
                reply = s.recv(64).decode(errors="replace")
        except OSError as e:
            logging.warning(f"Could not hand the snooze to the daemon ({e}); snoozing in this window")
            return False
        if not reply.startswith("OK"):
            logging.warning(f"Daemon refused the snooze ({reply}); snoozing in this window")
            return False
        logging.info(f"{self._module} snoozed by the daemon for {reply[3:]} min")
        return True

    def _snooze_here(self, minutes):
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float, str)):
            raise ValueError(f"Minutes must be a number, got {minutes!r}")
        try:
            mins = float(minutes)
        except (ValueError, OverflowError):
            raise ValueError(f"Minutes must be a number, got {minutes!r}") from None
        if not (0 < mins < 1440):
            raise ValueError(f"Minutes must be between 0 and 1440, got {minutes!r}")
        self._window.hide()
        logging.info(f"{self._module} snoozed for {mins:g} min")

        def show_again():
            logging.info(f"{self._module} back after snooze")
            self._window.show()
            bring_to_front(self._window)
            try:
                self._window.evaluate_js("window.dispatchEvent(new CustomEvent('remind2rest:resume'))")
            except Exception:
                pass

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
                    show_again()

            if is_locked():
                threading.Thread(target=wait_for_unlock, daemon=True).start()
            else:
                show_again()

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


def _set_gnome_app_name():
    if os.name != "nt":
        # Lets GNOME match the window to Remind2Rest.desktop (StartupWMClass) for the dock icon.
        try:
            from gi.repository import GLib
            GLib.set_prgname("Remind2Rest")
            GLib.set_application_name("Remind2Rest")
        except ImportError:
            pass


def _create_window(api, title, **page):
    return webview.create_window(
        title,
        js_api=api,
        fullscreen=True,
        frameless=True,
        on_top=True,
        focus=True,
        hidden=HIDE_UNTIL_READY,
        background_color="#000000",
        **page,
    )


def _exit_hard():
    # The window is gone, but the pywebview thread that answers the page's close() call can still
    # wait in evaluate_js for a main loop that has ended. It is not a daemon thread, so a normal exit
    # would wait for it forever, and the daemon would count this reminder as open. Exit hard instead.
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def show_reminder(module, settings):
    """Show reminders/<module>/reminder.html fullscreen until the page calls close()."""
    _set_gnome_app_name()
    logging.info(f"Opening {module} reminder (cold start)")
    api = OverlayApi(module, settings)
    api._window = _create_window(api, LIBRARY[module]["title"], url=page_uri(module))
    webview.start(api._reveal_later)
    _exit_hard()


def standby():
    """A hidden overlay with WebView2 already running, started by the daemon shortly before a reminder
    is due. It waits for one line on stdin, {"module": ..., "settings": {...}}, then loads that page and
    shows it like show_reminder. An empty line or a closed stdin (the daemon is gone) ends it unused."""
    _set_gnome_app_name()
    api = OverlayApi(None, {}, warm=True)
    api._window = _create_window(api, "Remind2Rest", html=BLANK_PAGE)

    def end_unused():
        api._closed = True
        # Destroying the window while WebView2 still initialises makes it throw (E_ABORT).
        api._window.events.loaded.wait(15)
        api._window.destroy()

    def wait_for_request():
        line = sys.stdin.readline()
        if not line.strip():
            logging.info("Warm overlay ended unused")
            end_unused()
            return
        try:
            request = json.loads(line)
            module = request["module"]
            title = LIBRARY[module]["title"]
        except (ValueError, KeyError, TypeError) as e:
            logging.error(f"Warm overlay got a bad request {line.strip()!r}: {e}")
            end_unused()
            return
        api._module = module
        api._settings = request.get("settings") or {}
        api._requested_at = time.monotonic()
        logging.info(f"Opening {module} reminder (warm start)")
        api._window.events.loaded.wait(15)
        api._window.set_title(title)
        api._window.load_url(page_uri(module))
        api._reveal_later()

    webview.start(wait_for_request)
    _exit_hard()
