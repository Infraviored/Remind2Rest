import os
import sys
import json
import time
import socket
import logging
import subprocess
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from logging.handlers import RotatingFileHandler

from src.config import CONFIG_PATH, LOG_PATH, SOCKET_FAMILY, ADDR, load_config
from src.ipc import create_server_socket, cleanup_socket
from src.scheduler import schedule_reminders, get_current_status

# Determine root script directory
script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1024 * 1024,  # 1MB per file
        backupCount=3,  # Keep 3 backup files
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)

def main():
    setup_logging()
    logging.info("Remind2Rest daemon starting up...")

    scheduler = BackgroundScheduler()
    scheduler._logger = logging.getLogger("apscheduler")
    scheduler._logger.setLevel(logging.WARNING)
    scheduler.start()

    try:
        s = create_server_socket()
    except Exception as e:
        logging.error(f"Failed to create server socket: {e}. Exiting.")
        scheduler.shutdown()
        return

    try:
        config = load_config()
        if config is None:
            logging.error("Error loading configuration. Exiting.")
            s.close()
            cleanup_socket()
            return

        logging.info("Remind2Rest daemon started successfully")
        schedule_reminders(scheduler, config)

        notifications_script = os.path.join(script_dir, "notifications.py")

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
                                    notifications_script,
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
                            conn.sendall(json.dumps(get_current_status()).encode())
                    except Exception as e:
                        logging.error(f"Error handling connection: {e}")
            except BlockingIOError:
                pass
            except Exception as e:
                logging.error(f"Error in main loop: {str(e)}")

            time.sleep(0.1)
    finally:
        scheduler.shutdown()
        s.close()
        cleanup_socket()

if __name__ == "__main__":
    main()
