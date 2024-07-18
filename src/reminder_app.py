import time
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from config_manager import ConfigManager
from notifications import send_notification

logging.basicConfig(filename='reminderapp.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

config_manager = ConfigManager()

def schedule_reminders(scheduler, config):
    scheduler.remove_all_jobs()
    interval_minutes = config['global_interval']
    
    def check_and_trigger_reminders():
        current_time = time.localtime()
        elapsed_minutes = (current_time.tm_hour * 60 + current_time.tm_min) % interval_minutes
        elapsed_seconds = current_time.tm_sec

        for module in ['eye_relax', 'posture']:
            if config[module]['enabled']:
                for reminder in config[module]['reminders']:
                    if elapsed_minutes == reminder and elapsed_seconds < 1:
                        trigger_reminder(module, config[module])

    scheduler.add_job(check_and_trigger_reminders, IntervalTrigger(seconds=1))

def trigger_reminder(module, settings):
    logging.info(f"Triggering {module} reminder")
    if module == 'eye_relax':
        send_notification("Eye Relax Reminder", "Time to rest your eyes!")
    elif module == 'posture':
        send_notification("Posture Reminder", "Check your posture!")

def main():
    config = config_manager.load_config()
    
    if config is None:
        logging.error("Error loading configuration. Exiting.")
        return

    logging.info("ReminderApp started successfully.")
    logging.info(f"Loaded configuration: {config}")
    
    scheduler = BackgroundScheduler()
    scheduler.start()
    schedule_reminders(scheduler, config)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping ReminderApp...")
    finally:
        scheduler.shutdown()

if __name__ == "__main__":
    main()