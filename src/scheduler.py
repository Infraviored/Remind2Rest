import os
import sys
import logging
import subprocess
from datetime import datetime
from apscheduler.triggers.interval import IntervalTrigger

# Determine root script directory
script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

current_status = {}

def get_current_status():
    return current_status

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

    # We call the notifications.py wrapper located in the root script directory
    notifications_script = os.path.join(script_dir, "notifications.py")

    if module == "eye_relax":
        subprocess.Popen([
            sys.executable,
            notifications_script,
            "eye_relax",
            "--freq", str(settings.get("flash_frequency", 2.0)),
            "--duration", str(settings.get("relax_duration", 20))
        ])
    elif module == "posture":
        subprocess.Popen([
            sys.executable,
            notifications_script,
            "posture",
            "--wait", str(settings.get("wait_duration", 3.0))
        ])

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
