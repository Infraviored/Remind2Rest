# app.py

from flask import Flask, render_template, request, jsonify
import json
import os
import subprocess
import mmap
import time
import webbrowser
import threading

browser_opened = False


app = Flask(__name__)

CMD_STOP = b"STOP    "
CMD_RELOAD = b"RELOAD  "
STATUS_RUNNING = b"RUNNING "
STATUS_STOPPED = b"STOPPED "

COMMAND_FILE_PATH = "/tmp/reminderapp_cmd.mmap"
STATE_FILE_PATH = "/tmp/reminderapp_state.mmap"

script_dir = os.path.dirname(os.path.realpath(__file__))
config_path = os.path.join(script_dir, "reminder_config.json")
reminder_app_path = os.path.join(script_dir, "ReminderApp.py")


def load_config():
    try:
        with open(config_path, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config):
    with open(config_path, "w") as file:
        json.dump(config, file, indent=2)


def check_service_status():
    try:
        with open(STATE_FILE_PATH, "r+b") as f:
            return mmap.mmap(f.fileno(), 8).read(8)
    except FileNotFoundError:
        return STATUS_STOPPED


def reload_service():
    try:
        with open(COMMAND_FILE_PATH, "r+b") as f:
            mmapped_file = mmap.mmap(f.fileno(), 8)
            mmapped_file.seek(0)
            mmapped_file.write(CMD_RELOAD)
    except FileNotFoundError:
        # If the file doesn't exist, the service isn't running
        pass


@app.route("/")
def index():
    return render_template("index.html", config=load_config())


@app.route("/save_config", methods=["POST"])
def save_configuration():
    new_config = request.json
    save_config(new_config)
    reload_service()  # Reload the running ReminderApp
    return jsonify({"status": "success"})


@app.route("/toggle_service", methods=["POST"])
def toggle_service():
    status = check_service_status()
    if status == STATUS_RUNNING:
        with open(COMMAND_FILE_PATH, "r+b") as f:
            mmap.mmap(f.fileno(), 8).write(CMD_STOP)
        time.sleep(0.2)
        if check_service_status() == STATUS_RUNNING:
            os.remove(COMMAND_FILE_PATH)
            os.remove(STATE_FILE_PATH)
        return jsonify({"status": "off"})
    else:
        subprocess.Popen(["python3", reminder_app_path])
        return jsonify({"status": "on"})


@app.route("/service_status")
def service_status():
    return jsonify(
        {"status": "on" if check_service_status() == STATUS_RUNNING else "off"}
    )


@app.route("/toggle_autostart", methods=["POST"])
def toggle_autostart():
    autostart_file_path = os.path.expanduser(
        "~/.config/autostart/HealthNotifier.desktop"
    )
    if os.path.exists(autostart_file_path):
        os.remove(autostart_file_path)
        status = "Disabled"
    else:
        os.makedirs(os.path.dirname(autostart_file_path), exist_ok=True)
        with open(autostart_file_path, "w") as file:
            file.write(
                f"[Desktop Entry]\nType=Application\nExec=python3 {reminder_app_path}\n"
                "Hidden=false\nNoDisplay=false\nX-GNOME-Autostart-enabled=true\n"
                "Name[en_US]=HealthNotifier\nName=HealthNotifier\n"
                "Comment[en_US]=Start HealthNotifier on login\nComment=Start HealthNotifier on login\n"
            )
        status = "Enabled"
    return jsonify({"status": status})


@app.route("/autostart_status")
def autostart_status():
    status = (
        "Enabled"
        if os.path.exists(
            os.path.expanduser("~/.config/autostart/HealthNotifier.desktop")
        )
        else "Disabled"
    )
    return jsonify({"status": status})


@app.route("/create_desktop_entry", methods=["POST"])
def create_desktop_entry():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    desktop_file_path = os.path.expanduser(
        "~/.local/share/applications/reminderapp.desktop"
    )

    with open(desktop_file_path, "w") as desktop_file:
        desktop_file.write(
            f"""[Desktop Entry]
Name=Reminder App
Exec=/usr/bin/python3 {script_dir}/flask_server.py
Icon={script_dir}/icon.png
Terminal=false
Type=Application
Categories=Utility;Application;
"""
        )

    os.chmod(desktop_file_path, 0o755)
    return jsonify({"status": "success"})


def open_browser():
    global browser_opened
    if not browser_opened:
        try:
            webbrowser.open("http://localhost:5000", new=2)
            print("Browser opened successfully")
            browser_opened = True
        except Exception as e:
            print(f"Error opening browser: {e}")


if __name__ == "__main__":
    threading.Thread(target=open_browser).start()
    app.run(debug=True, use_reloader=False)
