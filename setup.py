#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import subprocess

class ConfigGUI:
    def __init__(self, root):
        # Determine the directory of the current script
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        # Construct the full path to reminder_config.json based on the script's directory
        self.config_path = os.path.join(self.script_dir, 'reminder_config.json')

        self.header_fontsize = 20
        self.content_fontsize = 12
        button_width = 25

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

        self.save_button = ttk.Button(frame, text="Save Configurations", command=self.save_config, width=button_width)
        self.save_button.grid(row=11, columnspan=2, pady=20)


        self.boot_button = ttk.Button(frame, command=self.toggle_boot_status, width=button_width)  # Text will be set based on boot status
        self.boot_button.grid(row=12, columnspan=2, pady=20)
        

        self.running_button = ttk.Button(frame, command=self.toggle_running_status, width=button_width)  # Text will be set based on boot status
        self.running_button.grid(row=13, columnspan=2, pady=20)
        

        self.service_button = ttk.Button(frame, text="Set up System Service", command=self.setup_service, width=button_width)
        self.service_button.grid(row=14, columnspan=2, pady=20)

        self.service_button = ttk.Button(frame, text="Create Desktop Entry", command=self.create_desktop_file, width=button_width)
        self.service_button.grid(row=15, columnspan=2, pady=20)

        self.update_boot_button_text()
        self.update_running_button_text()

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
        
        running, _ = self.check_service_status()
        if running:
            self.restart_service()
            messagebox.showinfo("Info", "Configurations saved and service restarted!")
        else:
            messagebox.showinfo("Info", "Configurations saved!")

    def setup_service(self):
        # Determine the directory of the current script
        ReminderApp_path = os.path.join(self.script_dir, 'ReminderApp.py')


        # Write the systemd service file content
        service_content = f"""[Unit]
    Description=Reminder App Service
    After=network.target

    [Service]
    ExecStart=/usr/bin/python3 {ReminderApp_path}
    Restart=always
    Environment="DISPLAY=:0"

    [Install]
    WantedBy=default.target
    """

        service_path = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user", "reminderapp.service")
        
        with open(service_path, 'w') as temp_service_file:
            temp_service_file.write(service_content)

        # Make the Python files executable
        os.chmod(ReminderApp_path, 0o755)

        # Reload the systemd user daemon and enable the service
        if os.system("systemctl --user daemon-reload") == 0 and \
        os.system("systemctl --user enable reminderapp") == 0 and \
        os.system("systemctl --user start reminderapp") == 0:
            os.system('notify-send "Info" "User service for ReminderApp.py set up!"')

            messagebox.showinfo("Info", "User service for ReminderApp.py set up!")
        else:
            messagebox.showerror("Error", "Failed to set up the service. Please ensure you have the necessary permissions.")
            
        self.update_boot_button_text()
        self.update_running_button_text()

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



    def check_service_status(self):
        """Check the status of the reminderapp service and return its status."""
        # Check if the service is active
        process = subprocess.Popen(["systemctl", "--user", "is-active", "reminderapp"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()
        running = output.decode('utf-8').strip().lower() == "active"

        # Check if the service is enabled on boot
        process = subprocess.Popen(["systemctl", "--user", "is-enabled", "reminderapp"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()

        start_on_boot = "enabled" in output.decode('utf-8')
        print(f"Service is running: {running} | Service is enabled on boot: {start_on_boot}")

        return running, start_on_boot

    def restart_service(self):
        """Restart the reminderapp service."""
        os.system("systemctl --user restart reminderapp")

    def toggle_boot_status(self):
        """Toggle the boot status of the service and update the button text."""
        _, boot = self.check_service_status()
        if boot:
            # Disable the service on boot if it's currently enabled
            os.system("systemctl --user disable reminderapp")
        else:
            # Enable the service on boot if it's currently disabled
            os.system("systemctl --user enable reminderapp")
        self.update_boot_button_text()

    def update_boot_button_text(self):
        """Update the boot button text based on the service's boot status."""
        _, boot = self.check_service_status()
        if boot:
            self.boot_button.config(text="Start on Boot is ON")
        else:
            self.boot_button.config(text="Start on Boot is OFF")


    def toggle_running_status(self):
        """Toggle the boot status of the service and update the button text."""
        running, _ = self.check_service_status()
        if running:
            os.system("systemctl --user stop reminderapp")
        else:
            os.system("systemctl --user start reminderapp")
        self.update_running_button_text()


    def update_running_button_text(self):
        """Update the boot button text based on the service's boot status."""
        running, boot = self.check_service_status()
        if running:
            self.running_button.config(text="Service is ON")
        else:
            self.running_button.config(text="Service is OFF")

root = tk.Tk()
app = ConfigGUI(root)
root.mainloop()
