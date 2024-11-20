# app.py

from flask import Flask, render_template, request, jsonify
import json
import os
import subprocess
import time
import webbrowser
import threading
from datetime import datetime
import sys
import socket

browser_opened = False
last_ping_time = None
ping_timeout = 10  # seconds

# Add these constants at the top
STARTUP_MSG = """
╔════════════════════════════════════╗
║        Remind2Rest Configurator    ║
╚════════════════════════════════════╝
"""

app = Flask(__name__)

# Use XDG config path
CONFIG_PATH = os.path.expanduser("~/.config/Remind2Rest/reminder_config.json")
script_dir = os.path.dirname(os.path.realpath(__file__))
reminder_app_path = os.path.join(script_dir, "Remind2Rest.py")


def load_config():
    try:
        with open(CONFIG_PATH, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as file:
            json.dump(config, file, indent=2)
            print(f"💾 Configuration saved to {CONFIG_PATH}")
    except Exception as e:
        print(f"❌ Failed to save configuration: {e}")
        raise


def send_command_to_service(command):
    sock_path = os.path.expanduser("~/.Remind2Rest.sock")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(sock_path)
            sock.sendall(command.encode())
            return True
    except Exception as e:
        print(f"Error sending command: {e}")
        return False


def reload_service():
    return send_command_to_service("RELOAD")


@app.route("/")
def index():
    initial_save_status = {"show": False, "success": False, "message": ""}
    return render_template(
        "index.html", config=load_config(), saveStatus=initial_save_status
    )


@app.route("/save_config", methods=["POST"])
def save_configuration():
    try:
        new_config = request.json
        save_config(new_config)
        if reload_service():
            return jsonify(
                {
                    "status": "success",
                    "message": "Configuration saved and service reloaded successfully",
                }
            )
        return jsonify(
            {
                "status": "error",
                "message": "Configuration saved but failed to reload service",
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Failed to save configuration: {str(e)}",
                }
            ),
            500,
        )


@app.route("/toggle_service", methods=["POST"])
def toggle_service():
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "Remind2Rest"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            subprocess.run(["systemctl", "--user", "stop", "Remind2Rest"])
            status = "Stopped"
            running = False
        else:
            subprocess.run(["systemctl", "--user", "start", "Remind2Rest"])
            status = "Running"
            running = True
        return jsonify({"status": status, "running": running})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/toggle_autostart", methods=["POST"])
def toggle_autostart():
    autostart_file_path = os.path.expanduser("~/.config/autostart/Remind2Rest.desktop")
    if os.path.exists(autostart_file_path):
        os.remove(autostart_file_path)
        status = "Disabled"
    else:
        os.makedirs(os.path.dirname(autostart_file_path), exist_ok=True)
        with open(autostart_file_path, "w") as file:
            file.write(
                f"[Desktop Entry]\nType=Application\nExec=python3 {reminder_app_path}\n"
                "Hidden=false\nNoDisplay=false\nX-GNOME-Autostart-enabled=true\n"
                "Name[en_US]=Remind2Rest\nName=Remind2Rest\n"
                "Comment[en_US]=Start Remind2Rest on login\nComment=Start Remind2Rest on login\n"
            )
        status = "Enabled"
    return jsonify({"status": status})


@app.route("/autostart_status")
def autostart_status():
    status = (
        "Enabled"
        if os.path.exists(os.path.expanduser("~/.config/autostart/Remind2Rest.desktop"))
        else "Disabled"
    )
    return jsonify({"status": status})


@app.route("/create_desktop_entry", methods=["POST"])
def create_desktop_entry():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    desktop_file_path = os.path.expanduser(
        "~/.local/share/applications/Remind2Rest.desktop"
    )

    with open(desktop_file_path, "w") as desktop_file:
        desktop_file.write(
            f"""[Desktop Entry]
Name=Reminder App
Exec=/usr/bin/python3 {script_dir}/web_configurator.py
Icon={script_dir}/icon.png
Terminal=false
Type=Application
Categories=Utility;Application;
"""
        )

    os.chmod(desktop_file_path, 0o755)
    return jsonify({"status": "success"})


@app.route("/service_info")
def service_info():
    try:
        # Check if service is running
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "Remind2Rest"],
            capture_output=True,
            text=True,
        )
        is_running = result.returncode == 0

        # Check if service is enabled
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "Remind2Rest"],
            capture_output=True,
            text=True,
        )
        is_enabled = result.returncode == 0

        status = "Running" if is_running else "Stopped"

        return jsonify({"status": status, "running": is_running, "enabled": is_enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/toggle_service_enabled", methods=["POST"])
def toggle_service_enabled():
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "Remind2Rest"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            subprocess.run(["systemctl", "--user", "disable", "Remind2Rest"])
            enabled = False
        else:
            subprocess.run(["systemctl", "--user", "enable", "Remind2Rest"])
            enabled = True
        return jsonify({"enabled": enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/create_configurator_shortcut", methods=["POST"])
def create_configurator_shortcut():
    desktop_file_path = os.path.expanduser(
        "~/.local/share/applications/Remind2Rest-config.desktop"
    )
    script_dir = os.path.dirname(os.path.abspath(__file__))

    with open(desktop_file_path, "w") as f:
        f.write(
            f"""[Desktop Entry]
Name=Remind2Rest Configurator
Exec=/usr/bin/python3 {script_dir}/web_configurator.py
Icon={script_dir}/icon.png
Type=Application
Categories=Utility;
"""
        )
    os.chmod(desktop_file_path, 0o755)
    return jsonify({"status": "success"})


def shutdown_server():
    try:
        os._exit(0)
    except Exception as e:
        print(f"Error during shutdown: {e}")
        sys.exit(1)


@app.route("/stop_configurator", methods=["POST"])
def stop_configurator():
    # Schedule the shutdown after sending response
    threading.Timer(0.1, shutdown_server).start()
    return jsonify({"status": "success"})


def open_browser():
    global browser_opened
    if not browser_opened:
        try:
            webbrowser.open("http://localhost:5000", new=2)
            print("🌐 Web interface opened in browser")
            browser_opened = True
        except Exception as e:
            print(f"❌ Failed to open browser: {e}")


def check_connection_timeout():
    global last_ping_time
    print(STARTUP_MSG)
    print("🔄 Starting connection monitor...")
    while True:
        time.sleep(2)
        current_time = datetime.now()
        if last_ping_time:
            time_since_ping = (current_time - last_ping_time).seconds
            if time_since_ping > ping_timeout:
                print("\n❌ Client disconnected, shutting down server...")
                shutdown_server()
        else:
            print("⏳ Waiting for client connection...")
            time.sleep(
                5
            )  # Only check every 5 seconds when waiting for first connection


@app.route("/ping", methods=["POST"])
def ping():
    global last_ping_time
    if last_ping_time is None:
        print("✅ Client connected successfully")
    last_ping_time = datetime.now()
    return jsonify({"status": "pong"})


if __name__ == "__main__":
    threading.Thread(target=open_browser).start()
    threading.Thread(target=check_connection_timeout, daemon=True).start()
    app.run(debug=True, use_reloader=False)
