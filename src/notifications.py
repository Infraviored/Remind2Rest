import sys
import argparse
import os
import logging
from logging.handlers import RotatingFileHandler
from src.eye_relax import eye_relax_reminder
from src.posture import posture_reminder
from src.custom_reminder import show_custom_reminder

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
    
    eye_p = subparsers.add_parser("eye_relax")
    eye_p.add_argument("--freq", type=float, default=2.0)
    eye_p.add_argument("--duration", type=int, default=20)
    
    post_p = subparsers.add_parser("posture")
    post_p.add_argument("--wait", type=float, default=3.0)
    post_p.add_argument("--timeout", type=int, default=10)
    
    cust_p = subparsers.add_parser("custom")
    cust_p.add_argument("--message", type=str, required=True)
    cust_p.add_argument("--flashing", action="store_true")
    cust_p.add_argument("--duration", type=int, default=0)
    cust_p.add_argument("--cancel-key", type=str, default="Escape")
    cust_p.add_argument("--freq", type=int, default=2)
    cust_p.add_argument("--color", type=str, default="black")
    cust_p.add_argument("--fontsize", type=int, default=60)
    
    args = parser.parse_args()
    if args.command == "eye_relax":
        eye_relax_reminder(args.freq, args.duration)
    elif args.command == "posture":
        posture_reminder(args.wait, args.timeout)
    elif args.command == "custom":
        show_custom_reminder(args.message, args.flashing, args.duration, args.cancel_key, args.freq, args.color, args.fontsize)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
