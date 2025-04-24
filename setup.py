#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from shutil import copy2

# Define standard XDG paths
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))

# App-specific paths
APP_CONFIG_DIR = os.path.join(XDG_CONFIG_HOME, "Remind2Rest")
APP_DATA_DIR = os.path.join(XDG_DATA_HOME, "Remind2Rest")
APP_ICONS_DIR = os.path.join(APP_DATA_DIR, "icons")
APP_VENV_DIR = os.path.join(APP_DATA_DIR, "venv")
SERVICE_PATH = os.path.expanduser("~/.config/systemd/user/Remind2Rest.service")


def get_input(prompt):
    return input(prompt).strip().lower()


def is_installed():
    return os.path.exists(SERVICE_PATH)


def create_service_file(app_path, config_path):
    python_executable = os.path.join(APP_VENV_DIR, "bin", "python")
    display = os.environ.get("DISPLAY", ":0")
    xauthority = os.environ.get("XAUTHORITY", f"/home/{os.getenv('USER')}/.Xauthority")
    service_content = f"""[Unit]
Description=Remind2Rest Application
After=network.target graphical-session.target

[Service]
Type=simple
ExecStart={python_executable} {app_path}
Environment="REMINDER_CONFIG={config_path}"
Environment="DISPLAY={display}"
Environment="XAUTHORITY={xauthority}"
Restart=always

[Install]
WantedBy=default.target
"""
    os.makedirs(os.path.dirname(SERVICE_PATH), exist_ok=True)
    with open(SERVICE_PATH, "w") as f:
        f.write(service_content)


def copy_resources(current_dir):
    """Copy all necessary resources to appropriate locations"""
    # Create directories if they don't exist
    os.makedirs(APP_CONFIG_DIR, exist_ok=True)
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    os.makedirs(APP_ICONS_DIR, exist_ok=True)

    # Copy icon
    icon_src = os.path.join(current_dir, "Remind2Rest.png")
    icon_dst = os.path.join(APP_ICONS_DIR, "Remind2Rest.png")
    if os.path.exists(icon_src):
        copy2(icon_src, icon_dst)
        print(f"Icon copied to: {icon_dst}")
    else:
        print("Warning: Remind2Rest.png not found!")
        return None

    # Copy config file
    config_src = os.path.join(current_dir, "reminder_config.json")
    config_dst = os.path.join(APP_CONFIG_DIR, "reminder_config.json")

    if os.path.exists(config_dst):
        if (
            get_input(
                f"\nConfig file already exists at {config_dst}. Replace it? (y/n): "
            )
            != "y"
        ):
            print("Keeping existing config file.")
            return config_dst, icon_dst

    if os.path.exists(config_src):
        copy2(config_src, config_dst)
        print(f"Config file copied to: {config_dst}")
    else:
        print(
            "Warning: reminder_config.json not found. You'll need to create it manually."
        )

    return config_dst, icon_dst


def create_virtual_environment():
    """Create a virtual environment for the application"""
    if not os.path.exists(APP_VENV_DIR):
        print(f"\nCreating virtual environment at {APP_VENV_DIR}...")
        venv.create(APP_VENV_DIR, with_pip=True)
    else:
        print(f"\nUsing existing virtual environment at {APP_VENV_DIR}")
    
    # Return path to python and pip executables in the virtual environment
    if sys.platform.startswith('win'):
        python_path = os.path.join(APP_VENV_DIR, 'Scripts', 'python')
        pip_path = os.path.join(APP_VENV_DIR, 'Scripts', 'pip')
    else:
        python_path = os.path.join(APP_VENV_DIR, 'bin', 'python')
        pip_path = os.path.join(APP_VENV_DIR, 'bin', 'pip')
    
    return python_path, pip_path


def uninstall():
    print("\nUninstalling Remind2Rest...")
    # Stop and disable service
    subprocess.run(["systemctl", "--user", "stop", "Remind2Rest"])
    subprocess.run(["systemctl", "--user", "disable", "Remind2Rest"])

    # Remove service file
    if os.path.exists(SERVICE_PATH):
        os.remove(SERVICE_PATH)

    # Remove desktop shortcut
    desktop_file_path = os.path.expanduser(
        "~/.local/share/applications/Remind2Rest.desktop"
    )
    if os.path.exists(desktop_file_path):
        try:
            os.remove(desktop_file_path)
            print(f"Removed desktop shortcut: {desktop_file_path}")
        except Exception as e:
            print(f"Error removing desktop shortcut: {e}")

    # Reload systemd
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "reset-failed"])

    # Ask about config removal
    if (
        get_input("\nDo you want to remove all configuration files and data? (y/n): ")
        == "y"
    ):
        for directory in [APP_CONFIG_DIR, APP_DATA_DIR]:
            if os.path.exists(directory):
                try:
                    shutil.rmtree(directory)
                    print(f"Removed: {directory}")
                except Exception as e:
                    print(f"Error removing {directory}: {e}")
    else:
        print("Configuration and data files preserved.")

    print("Uninstallation completed!")


def install_service(app_path):
    print("\nInstalling Remind2Rest...")

    # Copy all necessary files
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_dst, icon_dst = copy_resources(current_dir)
    
    # Create and setup virtual environment
    python_path, pip_path = create_virtual_environment()
    
    # Install Python requirements in the virtual environment
    if get_input("\nDo you want to install Python requirements? (y/n): ") == "y":
        requirements_path = os.path.join(current_dir, "requirements.txt")
        if os.path.exists(requirements_path):
            print(f"Installing Python packages in virtual environment...")
            subprocess.run([pip_path, "install", "-r", requirements_path])
        else:
            print("Warning: requirements.txt not found!")

    if (
        icon_dst
        and get_input("\nCreate desktop shortcut for Remind2Rest? (y/n): ") == "y"
    ):
        create_desktop_shortcut(current_dir, icon_dst, python_path)

    # Prompt for systemd service
    install_service_choice = get_input("\nInstall and enable systemd user service? (y/n): ")
    if install_service_choice == "y":
        # Create service file
        create_service_file(app_path, config_dst)
        # Reload systemd and start service
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        subprocess.run(["systemctl", "--user", "enable", "Remind2Rest"])
        subprocess.run(["systemctl", "--user", "start", "Remind2Rest"])
        print("\nSystemd user service installed and started.")
    else:
        print("\nSkipping systemd service installation.")

    # Launch web configurator and wait for it to finish
    print("\nLaunching web configurator...")
    subprocess.run(
        [python_path, os.path.join(current_dir, "web_configurator.py")], check=True
    )

    print("\nInstallation completed!")
    print(f"Remind2Rest installed at: {app_path}")
    print(f"Config directory: {APP_CONFIG_DIR}")
    print(f"Data directory: {APP_DATA_DIR}")
    print(f"Virtual environment: {APP_VENV_DIR}")

    # Show current service status if installed
    if install_service_choice == "y":
        print("\nService Status:")
        try:
            subprocess.run(["systemctl", "--user", "status", "Remind2Rest"], timeout=5)
        except subprocess.TimeoutExpired:
            print("Service is running (status command timed out)")

        # Show log viewing command and execute it
        print("\nViewing initial application logs:")
        log_file = os.path.join(APP_DATA_DIR, "Remind2Rest.log")
        print("\nTo monitor logs in the future, use:")
        print(f"tail -f {log_file}")

        # Execute tail command to show initial logs
        try:
            subprocess.run(["tail", "-n", "10", log_file])
        except subprocess.CalledProcessError as e:
            print(f"Error viewing logs: {e}")
    else:
        print("Systemd service not installed; skipping service status and logs.")


def create_desktop_shortcut(current_dir, icon_dst, python_path):
    """Create desktop shortcut for the configurator"""
    desktop_file_path = os.path.expanduser(
        "~/.local/share/applications/Remind2Rest.desktop"
    )
    web_configurator_path = os.path.join(current_dir, "web_configurator.py")

    desktop_entry = f"""[Desktop Entry]
Name=Remind2Rest
Comment=Name=Remind2Rest Web Configurator
Exec={python_path} {web_configurator_path}
Icon={icon_dst}
Terminal=false
Type=Application
Categories=Utility;
"""

    os.makedirs(os.path.dirname(desktop_file_path), exist_ok=True)
    with open(desktop_file_path, "w") as f:
        f.write(desktop_entry)
    os.chmod(desktop_file_path, 0o755)
    print(f"Desktop shortcut created at: {desktop_file_path}")


def main():
    print("Remind2Rest Setup")
    print("================")

    if is_installed():
        print("\nRemind2Rest is already installed.")
        choice = (
            input("Do you want to (R)einstall or (U)ninstall? [R/U]: ").strip().upper()
        )

        if choice == "U":
            uninstall()
            return
        elif choice == "R":
            uninstall()
            print("\nProceeding with reinstallation...")
        else:
            print("Invalid choice. Exiting.")
            return
    else:
        choice = (
            input("\nRemind2Rest is not installed. Install it? [Y/N]: ").strip().upper()
        )
        if choice != "Y":
            print("Installation cancelled.")
            return

    # Install system dependencies
    print("\nInstalling system dependencies...")
    subprocess.run(
        ["sudo", "apt-get", "install", "-y", "python3-tk", "python3-pil.imagetk"]
    )

    # Get the current directory and check for Remind2Rest.py
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(current_dir, "Remind2Rest.py")

    if os.path.exists(app_path):
        install_service(app_path)
    else:
        print(f"Error: {app_path} not found!")
        return


if __name__ == "__main__":
    main()
