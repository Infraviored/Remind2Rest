#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys

def get_input(prompt):
    return input(prompt).strip().lower()

def create_service_file(app_path, config_path):
    service_content = f"""[Unit]
Description=Health Reminder Application
After=network.target

[Service]
ExecStart=/usr/bin/python3 {app_path}
Environment="REMINDER_CONFIG={config_path}"
Restart=always

[Install]
WantedBy=default.target
"""
    os.makedirs(os.path.expanduser('~/.config/systemd/user/'), exist_ok=True)
    with open(os.path.expanduser('~/.config/systemd/user/reminderapp.service'), 'w') as f:
        f.write(service_content)

def remove_existing_service():
    print("Removing existing ReminderApp service...")
    subprocess.run(['systemctl', '--user', 'stop', 'reminderapp'])
    subprocess.run(['systemctl', '--user', 'disable', 'reminderapp'])
    service_path = os.path.expanduser('~/.config/systemd/user/reminderapp.service')
    if os.path.exists(service_path):
        os.remove(service_path)
    subprocess.run(['systemctl', '--user', 'daemon-reload'])
    subprocess.run(['systemctl', '--user', 'reset-failed'])
    print("Existing service removed.")

def install_service(app_path):
    print("Installing ReminderApp service...")
    
    # Create config directory
    config_dir = os.path.expanduser('~/.config/reminderapp')
    os.makedirs(config_dir, exist_ok=True)

    # Copy config file if it exists
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_src = os.path.join(current_dir, 'reminder_config.json')
    config_dst = os.path.join(config_dir, 'reminder_config.json')
    if os.path.exists(config_src):
        shutil.copy2(config_src, config_dst)
        print(f"Config file copied to: {config_dst}")
    else:
        print("Warning: reminder_config.json not found. You'll need to create it manually.")

    # Create service file
    create_service_file(app_path, config_dst)

    # Reload systemd
    subprocess.run(['systemctl', '--user', 'daemon-reload'])

    # Enable and start the service
    subprocess.run(['systemctl', '--user', 'enable', 'reminderapp'])
    subprocess.run(['systemctl', '--user', 'start', 'reminderapp'])

    print("\nInstallation completed!")
    print(f"ReminderApp installed at: {app_path}")
    print(f"Config directory: {config_dir}")
    print("The service has been enabled and started.")
    print("\nYou can check the status with: systemctl --user status reminderapp")
    print("View logs with: journalctl --user -u reminderapp")

def main():
    print("ReminderApp Setup")
    print("=================")

    service_path = os.path.expanduser('~/.config/systemd/user/reminderapp.service')
    if os.path.exists(service_path):
        print("An existing ReminderApp service was detected.")
        action = get_input("Do you want to remove the existing service? (y/n): ")
        if action == 'y':
            remove_existing_service()
        else:
            print("Existing service will be kept. Exiting setup.")
            return

    install = get_input("Do you want to install the ReminderApp? (y/n): ")
    if install != 'y':
        print("Installation cancelled.")
        return

    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(current_dir, 'ReminderApp.py')

    if not os.path.exists(app_path):
        print(f"Error: ReminderApp.py not found in {current_dir}")
        return

    install_service(app_path)

if __name__ == "__main__":
    main()