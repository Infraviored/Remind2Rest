#!/usr/bin/env python3

import json
import time
import os
import fcntl
import mmap
import threading
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from notifications import eye_relax_reminder, posture_reminder

# Constants for our simple protocol
CMD_STOP = b"STOP    "
CMD_RELOAD = b"RELOAD  "
STATUS_RUNNING = b"RUNNING "
STATUS_STOPPED = b"STOPPED "

LOCK_FILE_PATH = "/tmp/reminderapp.lock"
COMMAND_FILE_PATH = "/tmp/reminderapp_cmd.mmap"
STATE_FILE_PATH = "/tmp/reminderapp_state.mmap"

script_dir = os.path.dirname(os.path.realpath(__file__))
config_path = os.path.join(script_dir, 'reminder_config.json')

logging.basicConfig(filename='reminderapp.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def init_mmap_file(file_path):
    with open(file_path, "a+b") as f:
        if f.tell() < 8:
            f.write(b'\0' * (8 - f.tell()))
        f.flush()

def clear_mmap_command_file():
    try:
        with open(COMMAND_FILE_PATH, "r+b") as f:
            mmapped_file = mmap.mmap(f.fileno(), 8)
            mmapped_file.seek(0)
            mmapped_file.write(b'\0' * 8)
            mmapped_file.close()
    except FileNotFoundError:
        pass

def set_mmap(file_path, status):
    try:
        with open(file_path, "r+b") as f:
            mmapped_file = mmap.mmap(f.fileno(), 8)
            mmapped_file.seek(0)
            mmapped_file.write(status)
            mmapped_file.close()
    except FileNotFoundError:
        pass

def load_config():
    try:
        with open(config_path, 'r') as file:
            config = json.load(file)
        validate_config(config)
        return config
    except json.JSONDecodeError:
        logging.error(f"Error: Invalid JSON in {config_path}")
    except FileNotFoundError:
        logging.error(f"Error: Config file not found at {config_path}")
    except ValueError as e:
        logging.error(f"Error: Invalid configuration - {str(e)}")
    return None

def validate_config(config):
    if 'global_interval' not in config:
        raise ValueError("Missing 'global_interval' in config")
    for module in ['eye_relax', 'posture']:
        if module not in config:
            raise ValueError(f"Missing '{module}' in config")
        if 'enabled' not in config[module]:
            raise ValueError(f"Missing 'enabled' for module {module}")
        if 'reminders' not in config[module]:
            raise ValueError(f"Missing 'reminders' for module {module}")

def print_config_summary(config):
    print(f"Reminder Interval: {config['global_interval']}min")
    print(f"Eye Relax Reminders: {', '.join(map(str, config['eye_relax']['reminders'])) if config['eye_relax']['enabled'] else 'Not set'}")
    print(f"Posture Reminders: {', '.join(map(str, config['posture']['reminders'])) if config['posture']['enabled'] else 'Not set'}")
    print()

def schedule_reminders(scheduler, config):
    scheduler.remove_all_jobs()
    interval_minutes = config['global_interval']
    
    def check_and_trigger_reminders():
        current_time = datetime.now()
        elapsed_minutes = (current_time.hour * 60 + current_time.minute) % interval_minutes
        elapsed_seconds = current_time.second

        next_reminder = None
        next_reminder_type = None
        time_to_next = float('inf')

        for module in ['eye_relax', 'posture']:
            if config[module]['enabled']:
                for reminder in config[module]['reminders']:
                    time_to_reminder = ((reminder - elapsed_minutes) % interval_minutes) * 60 - elapsed_seconds
                    if 0 <= time_to_reminder < time_to_next:
                        time_to_next = time_to_reminder
                        next_reminder = reminder
                        next_reminder_type = module

                    if elapsed_minutes == reminder and elapsed_seconds < 1:
                        trigger_reminder(module, config[module])

        minutes_to_next, seconds_to_next = divmod(int(time_to_next), 60)
        print(f"\rAt {elapsed_minutes:02d}min, {elapsed_seconds:02d}s of Interval | Next Reminder: {next_reminder_type.replace('_', ' ').title() if next_reminder_type else 'None'} in {minutes_to_next:02d}min, {seconds_to_next:02d}s", end='', flush=True)

    scheduler.add_job(check_and_trigger_reminders, IntervalTrigger(seconds=1))

def trigger_reminder(module, settings):
    print(f"\nTriggering {module} reminder")
    logging.info(f"Triggering {module} reminder")
    if module == 'eye_relax':
        threading.Thread(target=eye_relax_reminder, 
                         args=(settings['flash_frequency'],
                               settings['relax_duration'])).start()
    elif module == 'posture':
        threading.Thread(target=posture_reminder, 
                         args=(settings['wait_duration'],)).start()

def main():
    init_mmap_file(COMMAND_FILE_PATH)
    init_mmap_file(STATE_FILE_PATH)

    lock_file = open(LOCK_FILE_PATH, 'a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logging.error("Another instance of ReminderApp is already running.")
        return

    clear_mmap_command_file()
    set_mmap(STATE_FILE_PATH, STATUS_RUNNING)
    config = load_config()
    
    if config is None:
        logging.error("Error loading configuration. Exiting.")
        return

    logging.info("ReminderApp started successfully.")
    logging.info(f"Loaded configuration: {json.dumps(config, indent=2)}")
    
    print("ReminderApp started successfully.")
    print_config_summary(config)
    
    scheduler = BackgroundScheduler()
    scheduler.start()
    schedule_reminders(scheduler, config)
    
    try:
        while True:
            try:
                with open(COMMAND_FILE_PATH, "r+b") as f:
                    mmapped_file = mmap.mmap(f.fileno(), 8)
                    mmapped_file.seek(0)
                    command = mmapped_file.read(8)

                if command == CMD_STOP:
                    print("\nStopping ReminderApp...")
                    logging.info("Stopping ReminderApp...")
                    break
                elif command == CMD_RELOAD:
                    print("\nReloading configuration...")
                    logging.info("Reloading configuration...")
                    new_config = load_config()
                    if new_config is not None:
                        config = new_config
                        schedule_reminders(scheduler, config)
                        print_config_summary(config)
                        logging.info(f"Reloaded configuration: {json.dumps(config, indent=2)}")
                    else:
                        print("Error reloading configuration. Continuing with previous config.")
                        logging.error("Error reloading configuration. Continuing with previous config.")
                    clear_mmap_command_file()
            except FileNotFoundError:
                print("\nCommand file deleted. Stopping ReminderApp...")
                logging.info("Command file deleted. Stopping ReminderApp...")
                break

            time.sleep(1)
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        logging.error(f"An error occurred: {str(e)}")
    finally:
        scheduler.shutdown()
        set_mmap(STATE_FILE_PATH, STATUS_STOPPED)
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        for file_path in [LOCK_FILE_PATH, COMMAND_FILE_PATH, STATE_FILE_PATH]:
            try:
                os.remove(file_path)
            except FileNotFoundError:
                pass

if __name__ == "__main__":
    main()