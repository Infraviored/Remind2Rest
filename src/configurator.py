import os
import sys
import json
import socket
import subprocess
from pathlib import Path

import threading
import webview

from src.conference import post_webhook, redact
from src.config import ADDR, SOCKET_FAMILY, load_config, save_config
from src.library import LIBRARY
from src.scheduler import spawn_reminder

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
reminder_app_path = os.path.join(script_dir, "Remind2Rest.py")
icon_path = os.path.join(script_dir, "Remind2Rest.png")
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


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


class Api:
    """Methods the page calls as window.pywebview.api.<name>(); each returns JSON-able data."""

    def get_library(self):
        return [{"key": key, **entry} for key, entry in LIBRARY.items()]

    def get_config(self):
        return load_config()

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
            return {"status": "success", "message": f"Test sent to {redact(url)} (HTTP {code})"}
        except Exception as e:
            return {"status": "error", "message": f"Test failed: {str(e).replace(url, redact(url))}"}

    def service_info(self):
        running = is_service_running()
        if IS_WINDOWS:
            enabled = os.path.exists(windows_startup_path())
        else:
            enabled = systemctl("is-enabled").returncode == 0
        return {"status": "Running" if running else "Stopped", "running": running, "enabled": enabled}

    def toggle_service(self):
        if IS_WINDOWS:
            raise RuntimeError("Service control is not implemented on Windows. Run Remind2Rest.py manually.")
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
                f"$Shortcut.TargetPath = {ps_quote(sys.executable)}; "
                f"$Shortcut.Arguments = {ps_quote(arguments)}; "
                f"$Shortcut.Save()"
            )
            subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            return {"enabled": True}
        if systemctl("is-enabled").returncode == 0:
            systemctl("disable")
            return {"enabled": False}
        systemctl("enable")
        return {"enabled": True}


def main():
    if not IS_WINDOWS:
        # Lets GNOME match the window to Remind2Rest.desktop (StartupWMClass) for the dock icon.
        try:
            from gi.repository import GLib
            GLib.set_prgname(SERVICE)
            GLib.set_application_name(SERVICE)
        except ImportError:
            pass
    webview.create_window(
        "Remind2Rest",
        url=Path(index_path).as_uri(),
        js_api=Api(),
        width=1000,
        height=500,
        min_size=(760, 460),
        background_color="#121316",
    )
    webview.start(icon=icon_path)


if __name__ == "__main__":
    main()
