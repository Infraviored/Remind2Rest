import sys
import json
import argparse
import os
import logging
from logging.handlers import RotatingFileHandler
from src.custom_reminder import show_custom_reminder
from src.library import LIBRARY
from src.overlay import show_reminder

# Determine root script directory
script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Set up logging
log_path = os.path.join(script_dir, 'notifications.log')
handler = RotatingFileHandler(
    log_path,
    maxBytes=1024 * 1024,  # 1MB per file
    backupCount=3,  # Keep 3 backup files
    encoding="utf-8",
)
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(handler)

def main():
    parser = argparse.ArgumentParser(description="Remind2Rest Notifications")
    subparsers = parser.add_subparsers(dest="command")
    
    show_p = subparsers.add_parser("show")
    show_p.add_argument("type", choices=list(LIBRARY))
    show_p.add_argument("--settings", type=json.loads, default={})
    
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
    elif args.command == "custom":
        show_custom_reminder(args.message, args.flashing, args.duration, args.cancel_key, args.freq, args.color, args.fontsize)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
