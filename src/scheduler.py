import os
import sys
import json
import logging
import subprocess
import threading
from datetime import datetime, timedelta
from apscheduler.triggers.interval import IntervalTrigger

from src.config import LOG_PATH
from src.conference import detector as conference
from src.gate import ReminderGate
from src.library import LIBRARY, page_settings
from src.logs import water_today_ml
from src.session_lock import is_locked

# Determine root script directory
script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

current_status = {}
current_config = None
paused_until = None


def get_current_status():
    status = dict(current_status)
    if is_paused():
        status["paused_until"] = paused_until.isoformat(timespec="seconds")
    config = current_config or {}
    # Enabled types, so the top bar can offer "<title> now" for each without knowing the library.
    conf = conference.state()
    status["conference"] = {"active": conf["active"], "reasons": conf["reasons"]}
    status["types"] = [{"key": key, "title": entry["title"]}
                       for key, entry in LIBRARY.items() if config.get(key, {}).get("enabled")]
    water = config.get("water", {})
    if water.get("enabled"):
        status["water_today_ml"] = water_today_ml()
        status["water_goal_ml"] = page_settings("water", water).get("daily_goal_ml", 2000)
    return status


def pause(minutes):
    global paused_until
    paused_until = datetime.now() + timedelta(minutes=minutes)
    logging.info(f"Reminders paused until {paused_until:%H:%M}")


def resume():
    global paused_until
    paused_until = None
    logging.info("Reminders resumed")


def is_paused() -> bool:
    return paused_until is not None and datetime.now() < paused_until


# "Later" on a reminder page: the window closes and the daemon brings the reminder back halfway to
# the type's next regular time, so a type that comes every 2 h waits an hour and one that comes every
# 40 min waits 20. A second Later in a row (or a first one with the next regular time under
# SKIP_BELOW minutes away) lets the reminder drop out: the next regular time is the next one shown.
# Other reminders go on meanwhile. A type with no regular time (triggered by hand) comes back once
# after NO_SCHEDULE_SNOOZE minutes.
SKIP_BELOW = 10  # min
NO_SCHEDULE_SNOOZE = 10  # min
_snoozes = {}  # module -> {"count": Laters in a row, "due": datetime the reminder comes back, or None}
_snooze_lock = threading.Lock()


def minutes_to_next_regular(module, now=None):
    """Minutes from now until <module>'s next scheduled time, or None if it has none."""
    config = current_config or {}
    entry = config.get(module) or {}
    reminders = [r for r in entry.get("reminders", []) if isinstance(r, (int, float))]
    interval = config.get("global_interval")
    if not entry.get("enabled") or not reminders or not interval:
        return None
    now = now or datetime.now()
    elapsed = ((now.hour * 60 + now.minute) % interval) * 60 + now.second
    period = interval * 60
    # A time due this very second counts as the next period's.
    return min((r * 60 - elapsed) % period or period for r in reminders) / 60


def snooze(module, now=None):
    """Later was pressed on <module>; returns the minutes until it is shown again: its snooze, or
    its next regular time when it drops out (0 if it has none)."""
    if module not in LIBRARY:
        raise ValueError(f"Unknown reminder module: {module}")
    now = now or datetime.now()
    if not (current_config or {}).get(module, {}).get("enabled"):
        # A demo of a turned-off type (settings window): Later just closes it.
        logging.info(f"{module} is off; Later on its demo snoozes nothing")
        return 0
    gap = minutes_to_next_regular(module, now)
    with _snooze_lock:
        count = _snoozes.get(module, {}).get("count", 0) + 1
        if gap is None:
            minutes = NO_SCHEDULE_SNOOZE if count == 1 else None
        elif count == 1 and gap >= SKIP_BELOW:
            minutes = gap / 2
        else:
            minutes = None
        due = now + timedelta(minutes=minutes) if minutes is not None else None
        _snoozes[module] = {"count": count, "due": due}
    if minutes is not None:
        logging.info(f"{module} snoozed for {minutes:.0f} min (Later #{count} in a row)")
        return minutes
    if gap is None:
        logging.info(f"{module} dropped out after Later #{count}; it has no regular time")
        return 0
    logging.info(f"{module} dropped out after Later #{count}; next regular time in {gap:.0f} min")
    return gap


def snoozed(module):
    """Whether <module> waits for its snooze to end."""
    with _snooze_lock:
        return (_snoozes.get(module) or {}).get("due") is not None


def due_snoozes(now=None):
    """Modules whose snooze has ended; they are marked as back (the Later count stays)."""
    now = now or datetime.now()
    with _snooze_lock:
        due = [m for m, s in _snoozes.items() if s.get("due") is not None and s["due"] <= now]
        for m in due:
            _snoozes[m]["due"] = None
    return due


def scheduled_reminder_due(module):
    """The type's own scheduled time came. Returns False to leave it out while it is snoozed;
    otherwise the Later count starts again."""
    with _snooze_lock:
        s = _snoozes.get(module)
        if s and s.get("due") is not None:
            return False
        _snoozes.pop(module, None)
        return True

def update_status(status):
    global current_status
    if (
        not current_status
        or current_status.get("next_reminder") != status["next_reminder"]
    ):
        minutes_to_next = int(status["time_to_next"].split(":")[0])
        logging.info(
            f"Next {status['next_reminder']} reminder in {minutes_to_next} minutes"
        )
    current_status = status

def trigger_reminder(module, settings):
    # During a video conference the gate defers the reminder until the conference has ended.
    if is_paused():
        logging.info(f"Skipping {module} reminder while paused")
        return

    logging.info(f"Triggering {module} reminder")
    current_time = datetime.now()
    trigger_key = (current_time.hour, current_time.minute)

    if not hasattr(trigger_reminder, "last_triggers"):
        trigger_reminder.last_triggers = {}

    if trigger_reminder.last_triggers.get(module) == trigger_key:
        logging.debug(f"Skipping duplicate {module} reminder")
        return

    trigger_reminder.last_triggers[module] = trigger_key

    gate.request(module, settings)


# Windows: a hidden overlay process is started this many seconds before a reminder is due (and on
# PREWARM), so the reminder opens without the ~1.3 s cold start of Python, .NET and WebView2. Idle it
# holds about 200 MB, so it is not kept around all the time.
WARM_OVERLAY = os.name == "nt"
PREWARM_LEAD = 30
_standby = None
_standby_lock = threading.Lock()


def _overlay_command(*args):
    return [sys.executable, os.path.join(script_dir, "notifications.py"), *args]


def _overlay_io():
    """Popen arguments for an overlay: no console window, and native crash output (a .NET exception
    from pywebview's WinForms backend is printed by the runtime, not by Python) kept in a log file."""
    kwargs = {"stdout": subprocess.DEVNULL}
    try:
        kwargs["stderr"] = open(os.path.join(os.path.dirname(LOG_PATH), "overlay-errors.log"), "ab")
    except OSError:
        kwargs["stderr"] = subprocess.DEVNULL
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def prewarm():
    """Start the hidden standby overlay unless one is ready already (Windows only)."""
    global _standby
    if not WARM_OVERLAY:
        return
    with _standby_lock:
        if _standby is not None and _standby.poll() is None:
            return
        io = _overlay_io()
        try:
            _standby = subprocess.Popen(_overlay_command("standby"), stdin=subprocess.PIPE, **io)
            logging.info(f"Warming up an overlay for the next reminder (pid {_standby.pid})")
        except OSError as e:
            _standby = None
            logging.error(f"Could not start a warm overlay: {e}")
        finally:
            if hasattr(io.get("stderr"), "close"):
                io["stderr"].close()


def spawn_reminder(module, settings):
    """Start the overlay for one reminder in its own process; returns the process. Uses the warm
    standby overlay when there is one."""
    global _standby
    if module not in LIBRARY:
        raise ValueError(f"Unknown reminder module: {module}")
    page = page_settings(module, settings)
    with _standby_lock:
        proc, _standby = _standby, None
    if proc is not None and proc.poll() is None:
        try:
            proc.stdin.write((json.dumps({"module": module, "settings": page}) + "\n").encode())
            proc.stdin.flush()
            logging.info(f"Opening {module} in the warm overlay (pid {proc.pid})")
            return proc
        except OSError as e:
            logging.warning(f"Warm overlay did not take {module} ({e}); starting a new one")
    io = _overlay_io()
    try:
        proc = subprocess.Popen(_overlay_command("show", module, "--settings", json.dumps(page)), **io)
        logging.info(f"Opening {module} with a cold start (pid {proc.pid})")
        return proc
    finally:
        if hasattr(io.get("stderr"), "close"):
            io["stderr"].close()


def launch_reminder(module, settings):
    """Show a reminder on request (TRIGGER, the settings window's test button). Waits like a due
    one while the screen is locked or another reminder is open. Returns "shown", "deferred" or "dropped"."""
    if module not in LIBRARY:
        raise ValueError(f"Unknown reminder module: {module}")
    with _snooze_lock:
        # Shown fresh by hand: a Later on it is a first Later again, and a pending snooze is moot.
        _snoozes.pop(module, None)
    return gate.request(module, settings, manual=True)


def find_missed(since, until):
    """(module, settings) of the latest reminder due after `since` and up to `until` (epoch seconds)."""
    config = current_config
    if not config:
        return None
    interval = config["global_interval"]
    until_minute = datetime.fromtimestamp(until).replace(second=0, microsecond=0)
    elapsed = (until_minute.hour * 60 + until_minute.minute) % interval
    latest = None
    for module in LIBRARY:
        if config.get(module, {}).get("enabled"):
            for reminder in config[module].get("reminders", []):
                due = until_minute - timedelta(minutes=(elapsed - reminder) % interval)
                if due.timestamp() > since and (latest is None or due > latest[0]):
                    latest = (due, module)
    return (latest[1], config[latest[1]]) if latest else None


def skip_reason():
    if is_paused():
        return "paused"
    return None


gate = ReminderGate(spawn_reminder, is_locked=is_locked, find_missed=find_missed, skip_reason=skip_reason,
                    in_conference=lambda: conference.active)

def schedule_reminders(scheduler, config):
    if not config or not isinstance(config, dict):
        logging.error("schedule_reminders called with invalid config; skipping schedule")
        return

    global current_config
    current_config = config
    conference.configure(config.get("conference"))
    conference.start()
    scheduler.remove_all_jobs()
    interval_minutes = config["global_interval"]
    logging.info(f"Scheduling reminders with {interval_minutes} minute intervals")

    # Normalise reminder offsets modulo global_interval to keep them consistent
    for module in LIBRARY:
        if config.get(module, {}).get("enabled"):
            raw_reminders = config[module].get("reminders", [])
            normalised = sorted(set(int(r) % interval_minutes for r in raw_reminders if isinstance(r, (int, float))))
            if normalised != raw_reminders:
                logging.info(f"Normalised {module} reminders to interval {interval_minutes}m: {normalised}")
                config[module]["reminders"] = normalised

    current_time = datetime.now()
    elapsed_minutes = (current_time.hour * 60 + current_time.minute) % interval_minutes

    next_times = []
    for module in LIBRARY:
        if config.get(module, {}).get("enabled"):
            for reminder in config[module].get("reminders", []):
                minutes_until = (reminder - elapsed_minutes) % interval_minutes
                next_times.append((minutes_until, module))

    if next_times:
        next_reminder = min(next_times, key=lambda x: x[0])
        logging.info(
            f"First {next_reminder[1]} reminder will trigger in {next_reminder[0]} minutes"
        )
    else:
        logging.info("No enabled reminders found; waiting for configuration reload")

    def check_and_trigger_reminders():
        current_time = datetime.now()
        gate.tick()
        elapsed_minutes = (
            current_time.hour * 60 + current_time.minute
        ) % interval_minutes
        elapsed_seconds = current_time.second

        next_reminder = None
        next_reminder_type = None
        time_to_next = float("inf")

        for module in LIBRARY:
            if config.get(module, {}).get("enabled"):
                for reminder in config[module].get("reminders", []):
                    time_to_reminder = (
                        (reminder - elapsed_minutes) % interval_minutes
                    ) * 60 - elapsed_seconds
                    if time_to_reminder < 0:
                        time_to_reminder += interval_minutes * 60

                    if 0 <= time_to_reminder < time_to_next:
                        time_to_next = time_to_reminder
                        next_reminder = reminder
                        next_reminder_type = module

                    if elapsed_minutes == (reminder % interval_minutes) and elapsed_seconds < 1:
                        if scheduled_reminder_due(module):
                            trigger_reminder(module, config[module])
                        else:
                            logging.info(f"Skipping scheduled {module} reminder: it is snoozed")

        for module in due_snoozes():
            if config.get(module, {}).get("enabled") and not is_paused():
                logging.info(f"{module} back after snooze")
                gate.request(module, config[module])

        # Not at 0: that is the tick the reminder fires in, which just used the warm overlay.
        if (0 < time_to_next <= PREWARM_LEAD or (gate.pending and not gate.blocked_by_lock_or_conference)) and not is_paused():
            prewarm()

        if time_to_next == float("inf"):
            minutes_to_next, seconds_to_next = 0, 0
        else:
            minutes_to_next, seconds_to_next = divmod(int(time_to_next), 60)
        entry = LIBRARY.get(next_reminder_type, {})
        status = {
            "running": True,
            "next_reminder": next_reminder_type,
            "next_title": entry.get("title"),
            "next_icon": entry.get("symbolic_icon"),
            "time_to_next": f"{minutes_to_next:02d}:{seconds_to_next:02d}",
            "total_interval": f"{interval_minutes:02d}",
        }
        update_status(status)

    # First run now, so STATUS names the next reminder right after start or reload.
    scheduler.add_job(check_and_trigger_reminders, IntervalTrigger(seconds=1), next_run_time=datetime.now())
