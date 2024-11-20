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
from notifications import eye_relax_reminder, posture_reminder
from logging.handlers import RotatingFileHandler

# Use user-specific paths
SOCKET_PATH = os.path.expanduser("~/.Remind2Rest.sock")
CONFIG_PATH = os.path.expanduser("~/.config/Remind2Rest/reminder_config.json")
LOG_PATH = os.path.expanduser("~/.local/share/Remind2Rest/Remind2Rest.log")

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
        with open(CONFIG_PATH, "r") as file:
            config = json.load(file)
        validate_config(config)
        return config
    except json.JSONDecodeError:
        logging.error(f"Error: Invalid JSON in {CONFIG_PATH}")
    except FileNotFoundError:
        logging.error(f"Error: Config file not found at {CONFIG_PATH}")
    except ValueError as e:
        logging.error(f"Error: Invalid configuration - {str(e)}")
    return None


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

    next_reminder = min(next_times, key=lambda x: x[0])
    logging.info(
        f"First {next_reminder[1]} reminder will trigger in {next_reminder[0]} minutes"
    )

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
        threading.Thread(
            target=eye_relax_reminder,
            args=(settings["flash_frequency"], settings["relax_duration"]),
        ).start()
    elif module == "posture":
        threading.Thread(
            target=posture_reminder, args=(settings["wait_duration"],)
        ).start()


def main():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    scheduler = BackgroundScheduler()
    scheduler._logger = logging.getLogger("apscheduler")
    scheduler._logger.setLevel(logging.WARNING)
    scheduler.start()

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.bind(SOCKET_PATH)
            s.listen()
            s.setblocking(False)

            config = load_config()
            if config is None:
                logging.error("Error loading configuration. Exiting.")
                return

            logging.info("Remind2Rest started successfully with configuration:")
            for module in ["eye_relax", "posture"]:
                if config[module]["enabled"]:
                    logging.info(
                        f"- {module} reminders at minutes: {config[module]['reminders']}"
                    )

            schedule_reminders(scheduler, config)

            while True:
                try:
                    conn, addr = s.accept()
                    with conn:
                        try:
                            data = conn.recv(1024)
                            if data == b"STOP":
                                logging.info("Received STOP command")
                                break
                            elif data == b"RELOAD":
                                logging.info("Received RELOAD command")
                                new_config = load_config()
                                if new_config is not None:
                                    config = new_config
                                    schedule_reminders(scheduler, config)
                                    logging.info("Configuration reloaded successfully")
                            else:
                                # Send status response
                                conn.sendall(json.dumps(current_status).encode())
                        except Exception as e:
                            logging.error(f"Error handling connection: {e}")
                except BlockingIOError:
                    # No connection available, continue
                    pass
                except Exception as e:
                    logging.error(f"Error in main loop: {str(e)}")

                time.sleep(0.1)  # Short sleep to prevent CPU hogging
    finally:
        scheduler.shutdown()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)


if __name__ == "__main__":
    main()
