import os
import sys
import json
import socket
import subprocess
from pathlib import Path

import threading
import time
import webview

from src.conference import post_webhook, redact, format_error
from src.config import ADDR, SOCKET_FAMILY, load_config, save_config
from src.library import LIBRARY
from src.scheduler import spawn_reminder

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
reminder_app_path = os.path.join(script_dir, "Remind2Rest.py")
# pywebview's Windows backend only takes an .ico for the window icon (a PNG crashes it at start).
icon_path = os.path.join(script_dir, "Remind2Rest.ico" if os.name == "nt" else "Remind2Rest.png")
index_path = os.path.join(script_dir, "templates", "index.html")

IS_WINDOWS = os.name == "nt"
SERVICE = "Remind2Rest"


def send_command_to_service(command, timeout=5.0):
    try:
        sock = socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM)
    except Exception as e:
        print(f"Error creating socket: {e}")
        return None

    with sock:
        sock.settimeout(timeout)
        try:
            sock.connect(ADDR)
        except (ConnectionRefusedError, FileNotFoundError):
            return None
        except OSError as e:
            print(f"Service unreachable: {e}")
            return None

        try:
            sock.sendall(command.encode())
            reply = sock.recv(64)
            return reply.startswith(b"OK")
        except socket.timeout:
            print(f"Timeout waiting for reply to {command}")
            return True
        except Exception as e:
            print(f"Error communicating with service: {e}")
            return False


def is_service_running():
    try:
        with socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(ADDR)
            return True
    except Exception:
        return False


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args, SERVICE], capture_output=True, text=True)


def windows_startup_path():
    return os.path.join(os.environ["APPDATA"], "Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Remind2Rest.lnk")


def gui_python():
    """pythonw.exe next to the running interpreter on Windows (no console window), else sys.executable."""
    if IS_WINDOWS:
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return sys.executable


def start_windows_service():
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([gui_python(), reminder_app_path], cwd=script_dir, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_service(running, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_service_running() == running:
            return True
        time.sleep(0.2)
    return False


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


class Api:
    """Methods the page calls as window.pywebview.api.<name>(); each returns JSON-able data."""

    def get_library(self):
        return [{"key": key, **entry} for key, entry in LIBRARY.items()]

    def get_config(self):
        return load_config()

    def get_platform(self):
        """'windows' or 'linux'; the page marks conference signals Windows cannot detect."""
        return "windows" if IS_WINDOWS else "linux"

    def save_config(self, config):
        save_config(config)
        if send_command_to_service("RELOAD"):
            return {"status": "success", "message": "Configuration saved and service reloaded"}
        return {"status": "warning", "message": "Configuration saved but service is not running"}

    def _spawn_fallback(self, module, settings):
        proc = spawn_reminder(module, settings)
        threading.Thread(target=proc.wait, daemon=True).start()
        return proc

    def test_reminder(self, module, settings):
        settings = settings or (load_config() or {}).get(module, {})
        # Through the service, so the test waits like any reminder while another one is open.
        if send_command_to_service(f"TRIGGER {module} {json.dumps(settings)}") is None:
            self._spawn_fallback(module, settings)
        return {"status": "success"}

    def test_webhook(self, url):
        """POSTs state "test" to the conference webhook once, so the user sees whether it arrives."""
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"status": "error", "message": "Enter an http:// or https:// URL first"}
        try:
            code = post_webhook(url, "test", [])
            return {"status": "success", "code": code, "message": f"Test sent to {redact(url)} (HTTP {code})"}
        except Exception as e:
            return {"status": "error", "message": f"Test failed: {format_error(e)}"}

    def service_info(self):
        running = is_service_running()
        if IS_WINDOWS:
            enabled = os.path.exists(windows_startup_path())
        else:
            enabled = systemctl("is-enabled").returncode == 0
        return {"status": "Running" if running else "Stopped", "running": running, "enabled": enabled}

    def toggle_service(self):
        if IS_WINDOWS:
            if is_service_running():
                send_command_to_service("QUIT")
                if not wait_for_service(False):
                    raise RuntimeError("Remind2Rest did not stop within 5 s")
                return {"status": "Stopped", "running": False}
            start_windows_service()
            if not wait_for_service(True):
                raise RuntimeError("Remind2Rest did not start; see Remind2Rest.log in %LOCALAPPDATA%\\Remind2Rest")
            return {"status": "Running", "running": True}
        if systemctl("is-active").returncode == 0:
            systemctl("stop")
            return {"status": "Stopped", "running": False}
        systemctl("start")
        return {"status": "Running", "running": True}

    def toggle_service_enabled(self):
        if IS_WINDOWS:
            startup_path = windows_startup_path()
            if os.path.exists(startup_path):
                os.remove(startup_path)
                return {"enabled": False}
            arguments = '"' + reminder_app_path + '"'
            ps_cmd = (
                f"$WshShell = New-Object -ComObject WScript.Shell; "
                f"$Shortcut = $WshShell.CreateShortcut({ps_quote(startup_path)}); "
                f"$Shortcut.TargetPath = {ps_quote(gui_python())}; "
                f"$Shortcut.Arguments = {ps_quote(arguments)}; "
                f"$Shortcut.WorkingDirectory = {ps_quote(script_dir)}; "
                f"$Shortcut.IconLocation = {ps_quote(os.path.join(script_dir, 'Remind2Rest.ico'))}; "
                f"$Shortcut.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return {"enabled": True}
        if systemctl("is-enabled").returncode == 0:
            systemctl("disable")
            return {"enabled": False}
        systemctl("enable")
        return {"enabled": True}


# Height the settings page needs without scrolling; capped to the screen below.
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 860


def window_height():
    """WINDOW_HEIGHT, or the primary screen height minus room for panels and the title bar if smaller."""
    try:
        screen_height = webview.screens[0].height
    except Exception:
        return WINDOW_HEIGHT
    avail = screen_height - 80
    if avail <= 0:
        return WINDOW_HEIGHT
    return min(WINDOW_HEIGHT, avail)


def main():
    if not IS_WINDOWS:
        # Lets GNOME match the window to Remind2Rest.desktop (StartupWMClass) for the dock icon.
        try:
            from gi.repository import GLib
            GLib.set_prgname(SERVICE)
            GLib.set_application_name(SERVICE)
        except ImportError:
            pass
    # Warm up an overlay now, so the test buttons open their reminder without the cold start.
    threading.Thread(target=send_command_to_service, args=("PREWARM",), daemon=True).start()
    height = window_height()
    webview.create_window(
        "Remind2Rest",
        url=Path(index_path).as_uri(),
        js_api=Api(),
        width=WINDOW_WIDTH,
        height=height,
        min_size=(760, min(560, height)),
        background_color="#121316",
    )
    webview.start(icon=icon_path)


if __name__ == "__main__":
    main()
