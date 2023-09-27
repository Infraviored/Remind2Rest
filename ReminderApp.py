#!/usr/bin/env python3

import json
import time
import os
import fcntl
import mmap

from notifications import eye_relax_reminder, posture_reminder

# Constants for our simple protocol
CMD_STOP = b"STOP    "
CMD_RELOAD = b"RELOAD  "
STATUS_RUNNING = b"RUNNING"
STATUS_STOPPED = b"STOPPED"

LOCK_FILE_PATH = "/tmp/reminderapp.lock"
COMMAND_FILE_PATH = "/tmp/reminderapp_cmd.mmap"
STATE_FILE_PATH = "/tmp/reminderapp_state.mmap"

# Determine the directory of the current script
script_dir = os.path.dirname(os.path.realpath(__file__))

# Construct the full path to reminder_config.json based on the script's directory
config_path = os.path.join(script_dir, 'reminder_config.json')

def init_mmap_file(file_path):
    """Ensure the memory-mapped file exists and has the correct size."""
    with open(file_path, "a+b") as f:
        if f.tell() < 8:
            f.write(b'\0' * (8 - f.tell()))
        f.flush()

def clear_mmap_command_file():
    """Clear the command memory-mapped file to its initial state."""
    with open(COMMAND_FILE_PATH, "r+b") as f:
        mmapped_file = mmap.mmap(f.fileno(), 8)
        mmapped_file.seek(0)
        mmapped_file.write(b'\0' * 8)
        mmapped_file.close()

def set_mmap(file_path, status):
    """Set the memory-mapped file status."""
    with open(file_path, "r+b") as f:
        mmapped_file = mmap.mmap(f.fileno(), 8)
        mmapped_file.seek(0)
        mmapped_file.write(status)
        mmapped_file.close()

def display_current_config(config):
    """Display the current configuration settings."""
    print("Current Configuration:")
    print("======================")
    print(f"Eye Relax Reminder Enabled: {config['eye_relax_enabled']}")
    print(f"Eye Relax Interval: {config['eye_relax_interval']} minutes")
    print(f"Relax Duration: {config['relax_duration']} seconds")
    print(f"Flash Frequency: {config['flash_frequency']} Hz")
    print(f"Posture Reminder Enabled: {config['posture_enabled']}")
    print(f"Posture Reminder Interval: {config['posture_interval']} minutes")
    print(f"Wait Duration: {config['wait_duration']} seconds")
    print(f"Offset: {config['offset']} minutes")
    print("======================\n")

def init_timestamps(config):
    current_time = time.time()
    eye_relax_next_timestamp = current_time + config['eye_relax_interval'] * 60 if config['eye_relax_enabled'] else None
    posture_next_timestamp = current_time + config['posture_interval'] * 60 + config['offset'] * 60 if config['posture_enabled'] else None
    return eye_relax_next_timestamp, posture_next_timestamp

def main():

    # Initialize the memory-mapped files
    init_mmap_file(COMMAND_FILE_PATH)
    init_mmap_file(STATE_FILE_PATH)

    # Acquire a lock to ensure single instance
    lock_file = open(LOCK_FILE_PATH, 'a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Another instance of ReminderApp is already running.")
        return

    clear_mmap_command_file()

    # Set the state to RUNNING
    set_mmap(STATE_FILE_PATH, STATUS_RUNNING)

    # Load configurations
    with open(config_path, 'r') as file:
        config = json.load(file)

    display_current_config(config)

    eye_relax_next_timestamp, posture_next_timestamp = init_timestamps(config)

    while True:
        current_time = time.time()
        
        with open(COMMAND_FILE_PATH, "r+b") as f:
            mmapped_file = mmap.mmap(f.fileno(), 8)
            mmapped_file.seek(0)
            command = mmapped_file.read(8)

        if command == CMD_STOP:
            print("Stopping ReminderApp...")
            set_mmap(STATE_FILE_PATH, STATUS_STOPPED)
            clear_mmap_command_file()
            break

        if command == CMD_RELOAD:
            with open(config_path, 'r') as file:
                config = json.load(file)
            eye_relax_next_timestamp, posture_next_timestamp = init_timestamps(config)
            clear_mmap_command_file()

        eye_relax_time_str = str(int(eye_relax_next_timestamp - current_time)) if eye_relax_next_timestamp else 'N/A'
        posture_time_str = str(int(posture_next_timestamp - current_time)) if posture_next_timestamp else 'N/A'
        
        print(f"Time to next eye relax: {eye_relax_time_str:>5} s | Time to next posture: {posture_time_str:>5} s", end='\r')

        if eye_relax_next_timestamp is not None and current_time >= eye_relax_next_timestamp:
            print("\nCalling eye relax reminder.")
            eye_relax_reminder(config['flash_frequency'], config['relax_duration'])
            eye_relax_next_timestamp = current_time + config['eye_relax_interval'] * 60

        if posture_next_timestamp is not None and current_time >= posture_next_timestamp:
            print("\nCalling posture reminder.")
            posture_reminder(config['wait_duration'])
            posture_next_timestamp = current_time + config['posture_interval'] * 60 + config['offset'] * 60

        time.sleep(0.1)

    fcntl.flock(lock_file, fcntl.LOCK_UN)
    if os.path.exists(LOCK_FILE_PATH):
        os.remove(LOCK_FILE_PATH)
    if os.path.exists(COMMAND_FILE_PATH):
        os.remove(COMMAND_FILE_PATH)
    if os.path.exists(STATE_FILE_PATH):
        os.remove(STATE_FILE_PATH)


if __name__ == "__main__":
    main()
