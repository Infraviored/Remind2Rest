#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import subprocess
import mmap
import time


class ConfigGUI:
    # Constants for our simple protocol
    CMD_STOP = b"STOP    "
    CMD_RELOAD = b"RELOAD  "
    STATUS_RUNNING = b"RUNNING"
    STATUS_STOPPED = b"STOPPED"
    
    COMMAND_FILE_PATH = "/tmp/reminderapp_cmd.mmap"
    STATE_FILE_PATH = "/tmp/reminderapp_state.mmap"
    def __init__(self, root):
        # Determine the directory of the current script
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.reminder_app_path = os.path.join(self.script_dir, 'ReminderApp.py')
        # Construct the full path to reminder_config.json based on the script's directory
        self.config_path = os.path.join(self.script_dir, 'reminder_config.json')

        self.header_fontsize = 20
        self.content_fontsize = 12
        self.button_width = 40

        # Styles
        self.style = ttk.Style()
        self.style.theme_use('classic')
        self.style.configure('TFrame', background='#2e2e2e')
        self.style.configure('TLabel', background='#2e2e2e', foreground='#ffffff', font=('Arial', self.content_fontsize))
        self.style.configure('TCheckbutton', background='#2e2e2e', foreground='#ffffff', font=('Arial', self.content_fontsize), indicatorsize=40)
        self.style.configure('TButton', background='#4e4e4e', foreground='#ffffff', bordercolor='#4e4e4e',  font=('Arial', self.content_fontsize))
        self.style.configure('TEntry', font=('Arial', self.content_fontsize))

        self.style.map('TButton', background=[('active', '#3e3e3e')])



        self.root = root
        root.title('Screen Reminder Configuration')
        root.geometry('1400x1400')
        root.configure(bg='#2e2e2e')

        # Load existing configurations
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as file:
                self.config_data = json.load(file)
        else:
            self.config_data = {}

        frame = ttk.Frame(root)
        frame.pack(pady=75, padx=75)

        # Separate sections for configuration
        self.create_eye_relax_section(frame)
        self.create_posture_section(frame)
        self.create_offset_section(frame)
        self.create_buttons_section(frame)

    def create_eye_relax_section(self, parent_frame):
        # Eye Relax Reminder Configurations
        ttk.Label(parent_frame, text="Eye Relax Configuration", font=("Arial", self.header_fontsize)).grid(row=0, columnspan=2, pady=5, sticky=tk.W)
        self.eye_relax_var = tk.BooleanVar(value=self.config_data.get('eye_relax_enabled', False))
        ttk.Checkbutton(parent_frame, text="Enable Eye Relax Reminder", variable=self.eye_relax_var).grid(row=1, column=0, pady=10, sticky=tk.W)
        ttk.Label(parent_frame, text="Eye Relax Interval (minutes)").grid(row=2, column=0, pady=5, sticky=tk.W)
        self.eye_relax_interval = ttk.Entry(parent_frame)
        self.eye_relax_interval.insert(0, self.config_data.get('eye_relax_interval', 20))
        self.eye_relax_interval.grid(row=2, column=1, pady=5)

        ttk.Label(parent_frame, text="Relax Duration (seconds)").grid(row=3, column=0, pady=5, sticky=tk.W)
        self.relax_duration = ttk.Entry(parent_frame)
        self.relax_duration.insert(0, self.config_data.get('relax_duration', 20))
        self.relax_duration.grid(row=3, column=1, pady=5)

        ttk.Label(parent_frame, text="Flash Frequency (Hz)").grid(row=4, column=0, pady=5, sticky=tk.W)
        self.flash_frequency = ttk.Entry(parent_frame)
        self.flash_frequency.insert(0, self.config_data.get('flash_frequency', 5))
        self.flash_frequency.grid(row=4, column=1, pady=5)

    def create_posture_section(self, parent_frame):
        # Posture Reminder Configurations
        ttk.Label(parent_frame, text="Posture Reminder Configuration", font=("Arial", self.header_fontsize)).grid(row=5, columnspan=2, pady=5, sticky=tk.W)
        self.posture_var = tk.BooleanVar(value=self.config_data.get('posture_enabled', False))
        ttk.Checkbutton(parent_frame, text="Enable Posture Reminder", variable=self.posture_var).grid(row=6, column=0, pady=10, sticky=tk.W)
        ttk.Label(parent_frame, text="Posture Reminder Interval (minutes)").grid(row=7, column=0, pady=5, sticky=tk.W)
        self.posture_interval = ttk.Entry(parent_frame)
        self.posture_interval.insert(0, self.config_data.get('posture_interval', 20))
        self.posture_interval.grid(row=7, column=1, pady=5)

        ttk.Label(parent_frame, text="Wait before voting (seconds)").grid(row=8, column=0, pady=5, sticky=tk.W)
        self.wait_duration = ttk.Entry(parent_frame)
        self.wait_duration.insert(0, self.config_data.get('wait_duration', 3))
        self.wait_duration.grid(row=8, column=1, pady=5)

    def create_offset_section(self, parent_frame):
        ttk.Label(parent_frame, text="Offset Configuration", font=("Arial", self.header_fontsize)).grid(row=9, columnspan=2, pady=5, sticky=tk.W)
        ttk.Label(parent_frame, text="Offset Posture reminder from eye Relaxer (minutes)").grid(row=10, column=0, pady=5, sticky=tk.W)
        self.offset_var = ttk.Entry(parent_frame)
        self.offset_var.insert(0, self.config_data.get('offset', 10))
        self.offset_var.grid(row=10, column=1, pady=5)

    def create_buttons_section(self, parent_frame):
        # Button to save configurations
        self.save_button = ttk.Button(parent_frame, text="Save Configurations", command=self.save_config, width=self.button_width)
        self.save_button.grid(row=11, columnspan=2, pady=20)

        # Button to toggle ReminderApp's running status
        self.running_button = ttk.Button(parent_frame, command=self.toggle_running_status, width=self.button_width)
        self.running_button.grid(row=13, columnspan=2, pady=20)
        self.update_running_button_text()  # Call this function to initially set the button text

        self.autostart_button = ttk.Button(parent_frame, command=self.toggle_autostart_entry, width=self.button_width)
        self.autostart_button.grid(row=14, columnspan=2, pady=20)
        self.update_autostart_button_text()  # Call this function to initially set the button text

        # Button for creating a desktop entry
        self.desktop_entry_button = ttk.Button(parent_frame, text="Create Desktop Entry", command=self.create_desktop_file, width=self.button_width)
        self.desktop_entry_button.grid(row=15, columnspan=2, pady=20)


    def reload_service(self):
        """Reload ReminderApp configuration using mmap."""
        if os.path.exists(self.COMMAND_FILE_PATH):
            with open(self.COMMAND_FILE_PATH, "r+b") as f:
                mmapped_file = mmap.mmap(f.fileno(), 8)
                mmapped_file.seek(0)
                mmapped_file.write(self.CMD_RELOAD)
            self.update_running_button_text()
            subprocess.run(['notify-send', 'ReminderApp', 'Reloaded service!'])
        else:
            subprocess.run(['notify-send', 'ReminderApp', 'App not running!'])


    # Changed function
    def check_service_status(self):
        """Check the status of the ReminderApp."""
        try:
            with open(self.STATE_FILE_PATH, "r+b") as f:
                mmapped_file = mmap.mmap(f.fileno(), 8)
                mmapped_file.seek(0)
                status = mmapped_file.read(7)
            return status
        except FileNotFoundError:
            return self.STATUS_STOPPED  # Modified line: Return STATUS_STOPPED if file not found

    def toggle_running_status(self):
        """Toggle the running status of the ReminderApp using mmap."""
        try:
            with open(self.COMMAND_FILE_PATH, "r+b") as f:
                mmapped_file = mmap.mmap(f.fileno(), 8)
                status = self.check_service_status()
                
                if status == self.STATUS_RUNNING:
                    mmapped_file.seek(0)
                    mmapped_file.write(self.CMD_STOP)
                    time.sleep(0.2)  # Wait for 200 ms
                    
                    # Re-check the status
                    status = self.check_service_status()
                    
                    # Remove the temp file if still running
                    if status == self.STATUS_RUNNING:
                        os.remove(self.COMMAND_FILE_PATH)
                        os.remove(self.STATE_FILE_PATH)
                else:
                    subprocess.Popen(["python3", self.reminder_app_path])
        except FileNotFoundError:
            # Start ReminderApp if file not found
            subprocess.Popen(["python3", self.reminder_app_path])

        self.update_running_button_text()


    def save_config(self):
        flash_frequency_val = float(self.flash_frequency.get()) if self.flash_frequency.get() else 1.0

        if flash_frequency_val > 1:
            response = messagebox.askyesno("Epilepsy Warning", "Setting the flash frequency to more than 1 Hz can cause epileptic seizures in susceptible individuals. Set anyway? No sets the frequency to 1 Hz.")
            if not response:
                flash_frequency_val = 1.0

        config_data = {
            'eye_relax_enabled': self.eye_relax_var.get() if self.eye_relax_var.get() else False,
            'eye_relax_interval': float(self.eye_relax_interval.get()) if self.eye_relax_interval.get() else 20,
            'relax_duration': float(self.relax_duration.get()) if self.relax_duration.get() else 20,
            'flash_frequency': flash_frequency_val if self.flash_frequency.get() else 5,
            'posture_enabled': self.posture_var.get() if self.posture_var.get() else False,
            'posture_interval': float(self.posture_interval.get()) if self.posture_interval.get() else 20,
            'wait_duration': float(self.wait_duration.get()) if self.wait_duration.get() else 3,
            'offset': float(self.offset_var.get()) if self.offset_var.get() else 10
        }
        
        with open(self.config_path, 'w') as file:
            json.dump(config_data, file)
        
        running = self.check_service_status()
        if running == self.STATUS_RUNNING:
            self.reload_service()
            subprocess.run(['notify-send', 'ReminderApp', 'Configurations saved and service restarted!'])
        else:
            subprocess.run(['notify-send', 'ReminderApp', 'Configurations saved!'])


    def create_desktop_file(self):
        setup_path = os.path.join(self.script_dir, 'setup.py')
        icon_path = os.path.join(self.script_dir, 'icon.png')
        desktop_file_content = f"""[Desktop Entry]
    Name=Reminder App
    Exec=/usr/bin/python3 {setup_path}
    Icon={icon_path}
    Terminal=false
    Type=Application
    Categories=Utility;Application;
    """
        desktop_file_path = os.path.join(os.path.expanduser("~"), ".local", "share", "applications", "reminderapp.desktop")
        with open(desktop_file_path, 'w') as desktop_file:
            desktop_file.write(desktop_file_content)
        
        os.chmod(desktop_file_path, 0o755)
        messagebox.showinfo("Info", "Desktop file created!")

    def update_running_button_text(self):
        """Update the button text based on the ReminderApp's status."""
        status = self.check_service_status()
        
        if status == self.STATUS_RUNNING:
            self.running_button.config(text="ReminderApp is ON (Click to turn OFF)")
        else:
            self.running_button.config(text="ReminderApp is OFF (Click to turn ON)")
        self.root.after(300, self.update_running_button_text)  # Call this function again after 1 second



    def toggle_autostart_entry(self):
        autostart_directory = os.path.expanduser("~/.config/autostart/")
        autostart_file_path = os.path.join(autostart_directory, "HealthNotifier.desktop")

        if os.path.exists(autostart_file_path):
            os.remove(autostart_file_path)
            messagebox.showinfo("Info", "HealthNotifier will NOT start on login!")
        else:
            # Ensure the autostart directory exists
            if not os.path.exists(autostart_directory):
                os.makedirs(autostart_directory)

            # Create the .desktop file
            with open(autostart_file_path, 'w') as file:
                file.write("[Desktop Entry]\n")
                file.write("Type=Application\n")
                file.write("Exec=python3 /home/flo/Programs/HealthNotifier/ReminderApp.py\n")
                file.write("Hidden=false\n")
                file.write("NoDisplay=false\n")
                file.write("X-GNOME-Autostart-enabled=true\n")
                file.write("Name[en_US]=HealthNotifier\n")
                file.write("Name=HealthNotifier\n")
                file.write("Comment[en_US]=Start HealthNotifier on login\n")
                file.write("Comment=Start HealthNotifier on login\n")
            
            messagebox.showinfo("Info", "HealthNotifier will now start on login!")

        self.update_autostart_button_text()
    def update_autostart_button_text(self):
            
        """Update the autostart button text based on the existence of the autostart file."""
        autostart_file_path = os.path.join(os.path.expanduser("~/.config/autostart/"), "HealthNotifier.desktop")
        if os.path.exists(autostart_file_path):
            self.autostart_button.config(text="Start on Login (Enabled)")
        else:
            self.autostart_button.config(text="Start on Login (Disabled)")


root = tk.Tk()
app = ConfigGUI(root)
root.mainloop()
