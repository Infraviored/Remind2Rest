#!/usr/bin/env python3

import mmap

# Constants for the stop command
CMD_STOP = b"STOP    "
COMMAND_FILE_PATH = "/tmp/reminderapp_cmd.mmap"

def send_stop_command():
    """Send the stop command to ReminderApp using the memory-mapped file."""
    with open(COMMAND_FILE_PATH, "r+b") as f:
        mmapped_file = mmap.mmap(f.fileno(), 8)
        mmapped_file.seek(0)
        mmapped_file.write(CMD_STOP)
        mmapped_file.close()

    print("Stop command sent to ReminderApp.")

if __name__ == "__main__":
    send_stop_command()
