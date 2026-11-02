"""Tray icon for Windows, running inside the daemon (GNOME has the top bar extension instead).

The icon shows the minutes until the next reminder in that reminder's colour, the tooltip names it,
and the menu offers what the top bar extension offers: show a reminder now, pause, resume, settings
and quit."""
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime

import pystray
from PIL import Image, ImageDraw, ImageFont

from src import scheduler

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LOGO_PATH = os.path.join(script_dir, "Remind2Rest.png")
UPDATE_EVERY = 2  # s
PAUSE_CHOICES = (15, 30, 60, 120)
SIZE = 64
BADGE_HEIGHT = 26
BADGE_PAD = 8
BADGE_FONT = 21
BADGE_FILL = "#0b0f14"
BADGE_RING = "#ffffff"
BADGE_TEXT = "#ffffff"
FONT_FILES = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")


def minutes_left(status):
    """Whole minutes until the next reminder, rounded up (09:19 -> 10), or None."""
    if not status.get("next_reminder"):
        return None
    try:
        mins, secs = (int(x) for x in status.get("time_to_next", "").split(":"))
    except ValueError:
        return None
    return max(1, mins + (1 if secs else 0))


def headline(status, now=None):
    """First menu line and tooltip: what happens next."""
    now = now or datetime.now()
    paused = status.get("paused_until")
    if paused:
        try:
            return f"Paused until {datetime.fromisoformat(paused):%H:%M}"
        except ValueError:
            return "Paused"
    mins = minutes_left(status)
    if mins is None:
        return "No reminders enabled"
    title = status.get("next_title") or status["next_reminder"]
    if (status.get("conference") or {}).get("active"):
        return f"In a call: {title} waits until it ends"
    return f"{title} in {mins} min"


def water_line(status):
    if "water_today_ml" not in status:
        return None
    return f"Water today: {status['water_today_ml']} / {status.get('water_goal_ml', 2000)} ml"


def _font(px):
    for name in FONT_FILES:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def badge_text(mins):
    if mins < 100:
        return str(mins)
    return f"{round(mins / 60)}h"


def render_icon(status, logo):
    """The tray picture: the logo, with a small badge in the bottom right corner that holds the
    minutes until the next reminder (pause bars while paused). No badge when nothing is scheduled."""
    paused = bool(status.get("paused_until"))
    mins = minutes_left(status)
    if not paused and mins is None:
        return logo
    img = logo.copy()
    d = ImageDraw.Draw(img)
    text = "" if paused else badge_text(mins)
    # Big enough to read at 16-24 px tray size: the badge covers the lower right part of the logo.
    font = _font(BADGE_FONT)
    w = BADGE_HEIGHT if len(text) <= 1 else d.textbbox((0, 0), text, font=font)[2] + BADGE_PAD
    w = min(max(w, BADGE_HEIGHT), SIZE)
    left, top = SIZE - w, SIZE - BADGE_HEIGHT
    d.rounded_rectangle((left, top, SIZE - 1, SIZE - 1), radius=BADGE_HEIGHT // 2,
                        fill=BADGE_FILL, outline=BADGE_RING, width=2)
    cx, cy = left + w / 2, top + BADGE_HEIGHT / 2
    if paused:
        bar_w, gap, bar_h = 4, 4, BADGE_HEIGHT // 2
        x0 = cx - bar_w - gap / 2
        d.rectangle((x0, cy - bar_h / 2, x0 + bar_w, cy + bar_h / 2), fill=BADGE_TEXT)
        d.rectangle((x0 + bar_w + gap, cy - bar_h / 2, x0 + 2 * bar_w + gap, cy + bar_h / 2), fill=BADGE_TEXT)
    else:
        d.text((cx, cy), text, font=font, fill=BADGE_TEXT, anchor="mm")
    return img


class Tray:
    def __init__(self, on_quit):
        self._on_quit = on_quit
        self._logo = Image.open(LOGO_PATH).convert("RGBA").resize((SIZE, SIZE)) if os.path.exists(LOGO_PATH) \
            else Image.new("RGBA", (SIZE, SIZE), "#2dd4bf")
        self._lock = threading.Lock()
        self._status = {}
        self._shown = None  # (icon key, headline, water line, types) last pushed to the shell
        self._stopped = threading.Event()
        self.icon = pystray.Icon("Remind2Rest", self._logo, "Remind2Rest", menu=self._menu())

    def _status_snapshot(self):
        with self._lock:
            return dict(self._status)

    # Menu -----------------------------------------------------------------

    def _menu(self):
        M, I = pystray.Menu, pystray.MenuItem
        return M(
            I(lambda item: headline(self._status_snapshot()), None, enabled=False),
            I(lambda item: water_line(self._status_snapshot()) or "", None, enabled=False,
              visible=lambda item: water_line(self._status_snapshot()) is not None),
            M.SEPARATOR,
            I("Show now", M(self._show_now_items), visible=lambda item: bool(self._status_snapshot().get("types"))),
            I("Pause", M(*[I(self._pause_label(m), self._pauser(m)) for m in PAUSE_CHOICES]),
              visible=lambda item: not self._status_snapshot().get("paused_until")),
            I("Resume reminders", self._resume, visible=lambda item: bool(self._status_snapshot().get("paused_until"))),
            M.SEPARATOR,
            I("Settings…", self._open_settings, default=True),
            I("Quit Remind2Rest", self._quit),
        )

    def _show_now_items(self):
        return [pystray.MenuItem(t["title"], self._shower(t["key"])) for t in self._status_snapshot().get("types", [])]

    @staticmethod
    def _pause_label(minutes):
        return f"{minutes} minutes" if minutes < 60 else f"{minutes // 60} hour{'s' if minutes > 60 else ''}"

    def _shower(self, module):
        def show(icon, item):
            settings = (scheduler.current_config or {}).get(module, {})
            # Off the tray thread: the gate may take a moment, the menu should close at once.
            threading.Thread(target=self._launch, args=(module, settings), daemon=True).start()
        return show

    @staticmethod
    def _launch(module, settings):
        try:
            result = scheduler.launch_reminder(module, settings)
            logging.info(f"Tray: {module} now -> {result}")
        except Exception as e:
            logging.error(f"Tray: could not show {module}: {e}")

    def _pauser(self, minutes):
        def pause(icon, item):
            scheduler.pause(minutes)
            self.refresh()
        return pause

    def _resume(self, icon, item):
        scheduler.resume()
        self.refresh()

    def _open_settings(self, icon, item):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen([sys.executable, os.path.join(script_dir, "configurator.py")], creationflags=flags)
        except OSError as e:
            logging.error(f"Tray: could not open the settings: {e}")

    def _quit(self, icon, item):
        logging.info("Tray: quit")
        self.stop()
        self._on_quit()

    # Updates --------------------------------------------------------------

    def refresh(self):
        try:
            status = scheduler.get_current_status()
        except Exception as e:
            logging.debug(f"Tray: no status yet: {e}")
            return
        line = headline(status)
        mins = minutes_left(status)
        key = ("paused" if status.get("paused_until") else
               (status.get("next_reminder"), mins) if mins is not None else "logo")
        shown = (key, line, water_line(status), tuple(t["key"] for t in status.get("types", [])))
        with self._lock:
            if shown == self._shown:
                return
            need_icon = self._shown is None or key != self._shown[0]
            self._status = status
            self._shown = shown
        if need_icon:
            self.icon.icon = render_icon(status, self._logo)
        self.icon.title = f"Remind2Rest\n{line}"[:127]
        self.icon.update_menu()

    def _update_loop(self):
        while not self._stopped.wait(UPDATE_EVERY):
            try:
                self.refresh()
            except Exception as e:
                logging.error(f"Tray: update failed: {e}")

    def _setup(self, icon):
        icon.visible = True
        self.refresh()
        threading.Thread(target=self._update_loop, name="tray-update", daemon=True).start()

    def run(self):
        try:
            self.icon.run(setup=self._setup)
        except Exception as e:
            logging.error(f"Tray icon stopped: {e}")

    def stop(self):
        self._stopped.set()
        try:
            self.icon.stop()
        except Exception:
            pass


def start_tray(on_quit):
    """Run the tray icon on its own thread (pystray's Windows backend keeps its own message loop
    there). Returns the Tray; call stop() before the daemon exits."""
    tray = Tray(on_quit)
    threading.Thread(target=tray.run, name="tray", daemon=True).start()
    logging.info("Tray icon started")
    return tray
