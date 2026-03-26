#!/usr/bin/env python3

import json
import time
import os
import socket
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import threading
import subprocess
import sys
from logging.handlers import RotatingFileHandler

script_dir = os.path.dirname(os.path.realpath(__file__))

# Platform-specific paths and socket configuration
if os.name == 'nt':
    appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~/AppData/Local'))
    base_dir = os.path.join(appdata, 'Remind2Rest')
    os.makedirs(base_dir, exist_ok=True)
    CONFIG_PATH = os.path.join(base_dir, 'reminder_config.json')
    LOG_PATH = os.path.join(base_dir, 'Remind2Rest.log')
    # Use AF_INET for Windows IPC as it's more universally supported than AF_UNIX
    ADDR = ('127.0.0.1', 55555)
    SOCKET_FAMILY = socket.AF_INET
else:
    CONFIG_PATH = os.path.expanduser("~/.config/Remind2Rest/reminder_config.json")
    LOG_PATH = os.path.expanduser("~/.local/share/Remind2Rest/Remind2Rest.log")
    ADDR = os.path.expanduser("~/.Remind2Rest.sock")
    SOCKET_FAMILY = socket.AF_UNIX

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Setup rotating file handler
handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=1024 * 1024,  # 1MB per file
    backupCount=3,  # Keep 3 backup files
    encoding="utf-8",
)
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

# Configure logging
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(handler)

# Add startup message
logging.info("Remind2Rest starting up...")

current_status = {}


def load_config():
    try:
        if not os.path.exists(CONFIG_PATH):
            # Create a default config if not exists
            default_config = {
                "global_interval": 60,
                "eye_relax": {"enabled": True, "reminders": [20, 40], "flash_frequency": 2.0, "relax_duration": 20},
                "posture": {"enabled": True, "reminders": [0, 30], "wait_duration": 3.0}
            }
            save_config(default_config)
            return default_config
        with open(CONFIG_PATH, "r") as file:
            config = json.load(file)
        validate_config(config)
        return config
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
    return None

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as file:
            json.dump(config, file, indent=2)
    except Exception as e:
        logging.error(f"Error saving default configuration: {e}")

def validate_config(config):
    if "global_interval" not in config:
        raise ValueError("Missing 'global_interval' in config")
    for module in ["eye_relax", "posture"]:
        if module not in config:
            raise ValueError(f"Missing '{module}' in config")
        if "enabled" not in config[module]:
            raise ValueError(f"Missing 'enabled' for module {module}")
        if "reminders" not in config[module]:
            raise ValueError(f"Missing 'reminders' for module {module}")


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


def schedule_reminders(scheduler, config):
    if not config or not isinstance(config, dict):
        logging.error("schedule_reminders called with invalid config; skipping schedule")
        return

    scheduler.remove_all_jobs()
    interval_minutes = config["global_interval"]
    logging.info(f"Scheduling reminders with {interval_minutes} minute intervals")

    current_time = datetime.now()
    elapsed_minutes = (current_time.hour * 60 + current_time.minute) % interval_minutes

    next_times = []
    for module in ["eye_relax", "posture"]:
        if config[module]["enabled"]:
            for reminder in config[module]["reminders"]:
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
        elapsed_minutes = (
            current_time.hour * 60 + current_time.minute
        ) % interval_minutes
        elapsed_seconds = current_time.second

        next_reminder = None
        next_reminder_type = None
        time_to_next = float("inf")

        for module in ["eye_relax", "posture"]:
            if config[module]["enabled"]:
                for reminder in config[module]["reminders"]:
                    time_to_reminder = (
                        (reminder - elapsed_minutes) % interval_minutes
                    ) * 60 - elapsed_seconds
                    if 0 <= time_to_reminder < time_to_next:
                        time_to_next = time_to_reminder
                        next_reminder = reminder
                        next_reminder_type = module

                    if elapsed_minutes == reminder and elapsed_seconds < 1:
                        trigger_reminder(module, config[module])

        if time_to_next == float("inf"):
            minutes_to_next, seconds_to_next = 0, 0
        else:
            minutes_to_next, seconds_to_next = divmod(int(time_to_next), 60)
        status = {
            "running": True,
            "next_reminder": next_reminder_type,
            "time_to_next": f"{minutes_to_next:02d}:{seconds_to_next:02d}",
            "total_interval": f"{interval_minutes:02d}",
        }
        update_status(status)

    scheduler.add_job(check_and_trigger_reminders, IntervalTrigger(seconds=1))


def trigger_reminder(module, settings):
    logging.info(f"Triggering {module} reminder")
    current_time = datetime.now()
    trigger_key = f"{module}_{current_time.minute}"

    if (
        hasattr(trigger_reminder, "last_trigger")
        and trigger_reminder.last_trigger == trigger_key
    ):
        logging.debug(f"Skipping duplicate {module} reminder")
        return

    trigger_reminder.last_trigger = trigger_key

    if module == "eye_relax":
        subprocess.Popen([
            sys.executable,
            os.path.join(script_dir, "notifications.py"),
            "eye_relax",
            "--freq", str(settings.get("flash_frequency", 2.0)),
            "--duration", str(settings.get("relax_duration", 20))
        ])
    elif module == "posture":
        subprocess.Popen([
            sys.executable,
            os.path.join(script_dir, "notifications.py"),
            "posture",
            "--wait", str(settings.get("wait_duration", 3.0))
        ])


def main():
    if SOCKET_FAMILY == socket.AF_UNIX and os.path.exists(ADDR):
        os.remove(ADDR)

    scheduler = BackgroundScheduler()
    scheduler._logger = logging.getLogger("apscheduler")
    scheduler._logger.setLevel(logging.WARNING)
    scheduler.start()

    try:
        with socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM) as s:
            if SOCKET_FAMILY == socket.AF_INET:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(ADDR)
            s.listen()
            s.setblocking(False)

            config = load_config()
            if config is None:
                logging.error("Error loading configuration. Exiting.")
                return

            logging.info("Remind2Rest started successfully")
            schedule_reminders(scheduler, config)

            while True:
                try:
                    conn, _ = s.accept()
                    with conn:
                        data = conn.recv(4096)
                        if not data:
                            continue
                        try:
                            command = data.decode()
                            # Try to parse as JSON for custom reminders
                            try:
                                cmd_obj = json.loads(command)
                                if isinstance(cmd_obj, dict) and cmd_obj.get("action") == "custom_reminder":
                                    message = cmd_obj.get("message", "Reminder!")
                                    flashing = bool(cmd_obj.get("flashing", False))
                                    duration = int(cmd_obj.get("duration", 0))
                                    cancel_key = cmd_obj.get("cancel_key", "Escape")
                                    flashing_freq = int(cmd_obj.get("flashing_freq", 2))
                                    initial_color = cmd_obj.get("initial_color", "black")
                                    fontsize = int(cmd_obj.get("fontsize", 60))
                                    cmd = [
                                        sys.executable,
                                        os.path.join(script_dir, "notifications.py"),
                                        "custom",
                                        "--message", message,
                                        "--duration", str(duration),
                                        "--cancel-key", cancel_key,
                                        "--freq", str(flashing_freq),
                                        "--color", initial_color,
                                        "--fontsize", str(fontsize)
                                    ]
                                    if flashing:
                                        cmd.append("--flashing")
                                    subprocess.Popen(cmd)
                                    conn.sendall(b"OK")
                                    continue
                            except Exception:
                                pass
                            if command == "RELOAD":
                                config = load_config()
                                schedule_reminders(scheduler, config)
                                conn.sendall(b"OK")
                            elif command == "STATUS":
                                conn.sendall(json.dumps(current_status).encode())
                        except Exception as e:
                            logging.error(f"Error handling connection: {e}")
                except BlockingIOError:
                    pass
                except Exception as e:
                    logging.error(f"Error in main loop: {str(e)}")

                time.sleep(0.1)
    finally:
        scheduler.shutdown()
        if SOCKET_FAMILY == socket.AF_UNIX and os.path.exists(ADDR):
            os.remove(ADDR)


if __name__ == "__main__":
    main()
