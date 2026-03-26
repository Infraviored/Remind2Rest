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

# Platform-specific paths and socket configuration
if os.name == 'nt':
    appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~/AppData/Local'))
    base_dir = os.path.join(appdata, 'Remind2Rest')
    CONFIG_PATH = os.path.join(base_dir, 'reminder_config.json')
    ADDR = ('127.0.0.1', 55555)
    SOCKET_FAMILY = socket.AF_INET
else:
    CONFIG_PATH = os.path.expanduser("~/.config/Remind2Rest/reminder_config.json")
    ADDR = os.path.expanduser("~/.Remind2Rest.sock")
    SOCKET_FAMILY = socket.AF_UNIX

script_dir = os.path.dirname(os.path.realpath(__file__))
reminder_app_path = os.path.join(script_dir, "Remind2Rest.py")

STARTUP_MSG = """
╔════════════════════════════════════╗
║        Remind2Rest Configurator    ║
╚════════════════════════════════════╝
"""

app = Flask(__name__)

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
    try:
        with socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM) as sock:
            sock.connect(ADDR)
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
                "status": "warning",
                "message": "Configuration saved but service is not running. Start it manually.",
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
    if os.name == 'nt':
        return jsonify({"error": "Service control not implemented for Windows yet. Please run Remind2Rest.py manually."}), 501
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
    if os.name == 'nt':
        return jsonify({"error": "Autostart control not implemented for Windows yet."}), 501
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
    if os.name == 'nt':
        return jsonify({"status": "Unknown (Windows)"})
    status = (
        "Enabled"
        if os.path.exists(os.path.expanduser("~/.config/autostart/Remind2Rest.desktop"))
        else "Disabled"
    )
    return jsonify({"status": status})


@app.route("/service_info")
def service_info():
    is_running = False
    # Check if we can connect to the socket
    try:
        with socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(ADDR)
            is_running = True
    except:
        pass

    if os.name == 'nt':
        return jsonify({"status": "Running" if is_running else "Stopped", "running": is_running, "enabled": False})

    try:
        # For Linux, also check systemd
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "Remind2Rest"],
            capture_output=True,
            text=True,
        )
        is_enabled = result.returncode == 0
        return jsonify({"status": "Running" if is_running else "Stopped", "running": is_running, "enabled": is_enabled})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def shutdown_server():
    try:
        os._exit(0)
    except Exception as e:
        print(f"Error during shutdown: {e}")
        sys.exit(1)


@app.route("/stop_configurator", methods=["POST"])
def stop_configurator():
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
    while True:
        time.sleep(2)
        current_time = datetime.now()
        if last_ping_time:
            time_since_ping = (current_time - last_ping_time).seconds
            if time_since_ping > ping_timeout:
                print("\n❌ Client disconnected, shutting down server...")
                shutdown_server()
        else:
            time.sleep(5)


@app.route("/ping", methods=["POST"])
def ping():
    global last_ping_time
    last_ping_time = datetime.now()
    return jsonify({"status": "pong"})


if __name__ == "__main__":
    threading.Thread(target=open_browser).start()
    threading.Thread(target=check_connection_timeout, daemon=True).start()
    app.run(debug=True, use_reloader=False)
