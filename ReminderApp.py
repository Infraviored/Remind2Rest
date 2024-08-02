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

# Use user-specific paths
SOCKET_PATH = os.path.expanduser('~/.reminderapp.sock')
CONFIG_PATH = os.path.expanduser('~/.config/reminderapp/reminder_config.json')
LOG_PATH = os.path.expanduser('~/.local/share/reminderapp/reminderapp.log')

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

current_status = {}

def load_config():
    try:
        with open(CONFIG_PATH, 'r') as file:
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
    if 'global_interval' not in config:
        raise ValueError("Missing 'global_interval' in config")
    for module in ['eye_relax', 'posture']:
        if module not in config:
            raise ValueError(f"Missing '{module}' in config")
        if 'enabled' not in config[module]:
            raise ValueError(f"Missing 'enabled' for module {module}")
        if 'reminders' not in config[module]:
            raise ValueError(f"Missing 'reminders' for module {module}")

def update_status(status):
    global current_status
    current_status = status
    logging.info(f"Status updated: {status}")

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
        status = {
            "running": True,
            "next_reminder": next_reminder_type,
            "time_to_next": f"{minutes_to_next:02d}:{seconds_to_next:02d}",
            "total_interval": f"{interval_minutes:02d}"
        }
        update_status(status)

    scheduler.add_job(check_and_trigger_reminders, IntervalTrigger(seconds=1))

def trigger_reminder(module, settings):
    logging.info(f"Triggering {module} reminder")
    if module == 'eye_relax':
        threading.Thread(target=eye_relax_reminder, 
                         args=(settings['flash_frequency'],
                               settings['relax_duration'])).start()
    elif module == 'posture':
        threading.Thread(target=posture_reminder, 
                         args=(settings['wait_duration'],)).start()

def main():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.bind(SOCKET_PATH)
        s.listen()
        s.setblocking(False)

        config = load_config()
        if config is None:
            logging.error("Error loading configuration. Exiting.")
            return

        logging.info("ReminderApp started successfully.")
        
        scheduler = BackgroundScheduler()
        scheduler.start()
        schedule_reminders(scheduler, config)
        
        while True:
            try:
                conn, addr = s.accept()
                with conn:
                    conn.sendall(json.dumps(current_status).encode())
            except BlockingIOError:
                # No connection available, continue
                pass
            except Exception as e:
                logging.error(f"Error in main loop: {str(e)}")

            # Check for STOP or RELOAD commands
            try:
                conn, addr = s.accept()
                with conn:
                    data = conn.recv(1024)
                    if data == b'STOP':
                        break
                    elif data == b'RELOAD':
                        new_config = load_config()
                        if new_config is not None:
                            config = new_config
                            schedule_reminders(scheduler, config)
                            logging.info("Configuration reloaded.")
            except BlockingIOError:
                # No connection available, continue
                pass
            except Exception as e:
                logging.error(f"Error checking for commands: {str(e)}")

            time.sleep(0.1)  # Short sleep to prevent CPU hogging

    scheduler.shutdown()
    os.remove(SOCKET_PATH)

if __name__ == "__main__":
    main()