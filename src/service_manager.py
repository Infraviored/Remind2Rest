import platform
import os
import subprocess

class ServiceManager:
    def __init__(self):
        self.system = platform.system()
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.reminder_app_path = os.path.join(self.script_dir, 'reminder_app.py')

    def install(self):
        if self.system == "Windows":
            self._install_windows()
        elif self.system == "Linux":
            self._install_linux()
        elif self.system == "Darwin":  # macOS
            self._install_macos()

    def start(self):
        if self.system == "Windows":
            subprocess.run(["sc", "start", "ReminderApp"])
        elif self.system in ["Linux", "Darwin"]:
            subprocess.run(["supervisorctl", "start", "reminderapp"])

    def stop(self):
        if self.system == "Windows":
            subprocess.run(["sc", "stop", "ReminderApp"])
        elif self.system in ["Linux", "Darwin"]:
            subprocess.run(["supervisorctl", "stop", "reminderapp"])

    def reload(self):
        if self.system == "Windows":
            self.stop()
            self.start()
        elif self.system in ["Linux", "Darwin"]:
            subprocess.run(["supervisorctl", "restart", "reminderapp"])

    def is_running(self):
        if self.system == "Windows":
            result = subprocess.run(["sc", "query", "ReminderApp"], capture_output=True, text=True)
            return "RUNNING" in result.stdout
        elif self.system in ["Linux", "Darwin"]:
            result = subprocess.run(["supervisorctl", "status", "reminderapp"], capture_output=True, text=True)
            return "RUNNING" in result.stdout

    def is_installed(self):
        if self.system == "Windows":
            result = subprocess.run(["sc", "query", "ReminderApp"], capture_output=True, text=True)
            return result.returncode == 0
        elif self.system in ["Linux", "Darwin"]:
            return os.path.exists("/etc/supervisor/conf.d/reminderapp.conf")

    def enable_autostart(self):
        if self.system == "Windows":
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.SetValueEx(key, "ReminderApp", 0, winreg.REG_SZ, f"pythonw {self.reminder_app_path}")
            except WindowsError:
                raise

        elif self.system == "Linux":
            autostart_dir = os.path.expanduser("~/.config/autostart")
            os.makedirs(autostart_dir, exist_ok=True)
            desktop_entry = f"""[Desktop Entry]
Type=Application
Exec=python3 {self.reminder_app_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name[en_US]=ReminderApp
Name=ReminderApp
Comment[en_US]=Start ReminderApp on login
Comment=Start ReminderApp on login
"""
            with open(os.path.join(autostart_dir, "reminderapp.desktop"), "w") as f:
                f.write(desktop_entry)

        elif self.system == "Darwin":
            plist_path = os.path.expanduser("~/Library/LaunchAgents/com.reminderapp.plist")
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.reminderapp</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{self.reminder_app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
            with open(plist_path, "w") as f:
                f.write(plist_content)
            subprocess.run(["launchctl", "load", plist_path])

    def disable_autostart(self):
        if self.system == "Windows":
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.DeleteValue(key, "ReminderApp")
            except WindowsError:
                pass

        elif self.system == "Linux":
            autostart_file = os.path.expanduser("~/.config/autostart/reminderapp.desktop")
            if os.path.exists(autostart_file):
                os.remove(autostart_file)

        elif self.system == "Darwin":
            plist_path = os.path.expanduser("~/Library/LaunchAgents/com.reminderapp.plist")
            if os.path.exists(plist_path):
                subprocess.run(["launchctl", "unload", plist_path])
                os.remove(plist_path)

    def is_autostart_enabled(self):
        if self.system == "Windows":
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
                winreg.QueryValueEx(key, "ReminderApp")
                return True
            except WindowsError:
                return False

        elif self.system == "Linux":
            return os.path.exists(os.path.expanduser("~/.config/autostart/reminderapp.desktop"))

        elif self.system == "Darwin":
            return os.path.exists(os.path.expanduser("~/Library/LaunchAgents/com.reminderapp.plist"))

    def create_desktop_entry(self):
        if self.system == "Windows":
            import winshell
            from win32com.client import Dispatch
            desktop = winshell.desktop()
            path = os.path.join(desktop, "ReminderApp.lnk")
            target = self.reminder_app_path
            wDir = self.script_dir
            icon = os.path.join(self.script_dir, "icon.ico")
            
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(path)
            shortcut.Targetpath = target
            shortcut.WorkingDirectory = wDir
            shortcut.IconLocation = icon
            shortcut.save()

        elif self.system == "Linux":
            desktop_file_path = os.path.expanduser("~/.local/share/applications/reminderapp.desktop")
            with open(desktop_file_path, 'w') as desktop_file:
                desktop_file.write(f"""[Desktop Entry]
Name=Reminder App
Exec=python3 {self.reminder_app_path}
Icon={os.path.join(self.script_dir, "icon.png")}
Terminal=false
Type=Application
Categories=Utility;Application;
""")
            os.chmod(desktop_file_path, 0o755)

        elif self.system == "Darwin":
            # For macOS, creating a proper .app bundle is complex and beyond the scope of this example
            # For simplicity, we'll create an AppleScript that launches the Python script
            script_path = os.path.expanduser("~/Desktop/ReminderApp.scpt")
            apple_script = f"""
            tell application "Terminal"
                do script "python3 {self.reminder_app_path}"
            end tell
            """
            with open(script_path, 'w') as script_file:
                script_file.write(apple_script)
            os.chmod(script_path, 0o755)

    def _install_windows(self):
        # This is a simplified version. In reality, you'd use pywin32 to create a proper Windows service
        subprocess.run(["sc", "create", "ReminderApp", "binPath=", f"python {self.reminder_app_path}"])

    def _install_linux(self):
        supervisor_conf = f"""[program:reminderapp]
command=python3 {self.reminder_app_path}
autostart=true
autorestart=true
stderr_logfile=/var/log/reminderapp.err.log
stdout_logfile=/var/log/reminderapp.out.log
"""
        with open("/etc/supervisor/conf.d/reminderapp.conf", "w") as f:
            f.write(supervisor_conf)
        subprocess.run(["supervisorctl", "reread"])
        subprocess.run(["supervisorctl", "update"])

    def _install_macos(self):
        # For macOS, we'll use the same approach as Linux with Supervisor
        self._install_linux()