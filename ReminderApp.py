#!/usr/bin/env python3

import json
import time
import subprocess
import os


def get_next_interval(current_time, interval):
    """Return the next time the event should be triggered."""
    return current_time + interval * 60  # Convert minutes to seconds


def main():
    # Determine the directory of the current script
    script_dir = os.path.dirname(os.path.realpath(__file__))

    # Construct the full path to reminder_config.json based on the script's directory
    config_path = os.path.join(script_dir, 'reminder_config.json')

    # Load configurations
    with open(config_path, 'r') as file:
        config = json.load(file)

    # Display the current configuration settings
    print("Current Configuration:")
    print("======================")
    print(f"Eye Relax Reminder Enabled: {config['eye_relax_enabled']}")
    print(f"Eye Relax Interval: {config['eye_relax_interval']} minutes")
    print(f"Posture Reminder Enabled: {config['posture_enabled']}")
    print(f"Posture Reminder Interval: {config['posture_interval']} minutes")
    print("======================\n")

    notifier_path = os.path.join(script_dir, 'notifier.py')

    # Initialize the first intervals if enabled
    eye_relax_next = get_next_interval(time.time(), config['eye_relax_interval']) if config['eye_relax_enabled'] else None
    posture_next = get_next_interval(time.time(), config['posture_interval'] + config['offset']) if config['posture_enabled'] else None

    while True:
        current_time = time.time()

        # Decide which event to trigger next
        if eye_relax_next is not None and (posture_next is None or eye_relax_next <= posture_next):
            sleep_time = eye_relax_next - current_time
            event = "eye_relax"
            eye_relax_next = get_next_interval(eye_relax_next, config['eye_relax_interval'])
        elif posture_next is not None:
            sleep_time = posture_next - current_time
            event = "posture"
            posture_next = get_next_interval(posture_next, config['posture_interval'])
        else:
            # If no reminders are enabled, break out of the loop
            break

        # Sleep until the next event
        time.sleep(max(0, sleep_time))  # Ensure non-negative

        # Trigger the event
        subprocess.Popen(["python3", notifier_path, event])

if __name__ == "__main__":
    main()
