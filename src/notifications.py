import sys
import json
import argparse
import os
import logging
import threading
from logging.handlers import RotatingFileHandler
from src.custom_reminder import show_custom_reminder
from src.library import LIBRARY
from src.overlay import show_reminder, standby

from src.config import LOG_PATH

# Same folder as the daemon's log, own file: two processes rotating one file break on Windows.
log_path = os.path.join(os.path.dirname(LOG_PATH), "notifications.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
handler = RotatingFileHandler(
    log_path,
    maxBytes=1024 * 1024,  # 1MB per file
    backupCount=3,  # Keep 3 backup files
    encoding="utf-8",
)
handler.setFormatter(logging.Formatter("%(asctime)s - %(process)d - %(levelname)s - %(message)s"))
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(handler)
# pywebview logs every bridge call at INFO; keep its warnings and errors only.
logging.getLogger("pywebview").setLevel(logging.WARNING)


def _log_uncaught(kind, value, tb):
    logging.critical("Reminder window crashed", exc_info=(kind, value, tb))


sys.excepthook = _log_uncaught
threading.excepthook = lambda args: _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)

def main():
    parser = argparse.ArgumentParser(description="Remind2Rest Notifications")
    subparsers = parser.add_subparsers(dest="command")
    
    show_p = subparsers.add_parser("show")
    show_p.add_argument("type", choices=list(LIBRARY))
    show_p.add_argument("--settings", type=json.loads, default={})
    
    subparsers.add_parser("standby", help="hidden overlay that waits for its reminder on stdin")

    cust_p = subparsers.add_parser("custom")
    cust_p.add_argument("--message", type=str, required=True)
    cust_p.add_argument("--flashing", action="store_true")
    cust_p.add_argument("--duration", type=int, default=0)
    cust_p.add_argument("--cancel-key", type=str, default="Escape")
    cust_p.add_argument("--freq", type=int, default=2)
    cust_p.add_argument("--color", type=str, default="black")
    cust_p.add_argument("--fontsize", type=int, default=60)
    
    args = parser.parse_args()
    if args.command == "show":
        show_reminder(args.type, args.settings)
    elif args.command == "standby":
        standby()
    elif args.command == "custom":
        show_custom_reminder(args.message, args.flashing, args.duration, args.cancel_key, args.freq, args.color, args.fontsize)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
