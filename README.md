# Remind2Rest

A health-focused application that helps you maintain good posture and reduce eye strain while working at your computer. It provides customizable reminders for taking breaks, relaxing your eyes, and maintaining proper posture.

## Features

- 👀 **Eye Relaxation Reminders**: Periodic reminders to look away from your screen
- 🪑 **Posture Checks**: Customizable reminders to maintain good posture
- ⚙️ **Web Configurator**: Easy-to-use interface for customizing all settings
- 🚀 **System Integration**: Runs as a system service with autostart capability

## Requirements

- Python 3.8 or higher
- Linux-based operating system (tested on Ubuntu/Debian)

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/Infraviored/Remind2Rest.git
   ```

2. Run the setup script:
   ```
   python3 setup.py
   ```

The setup script will:
- Install required system dependencies
- Install Python packages
- Set up the system service
- Create necessary configuration files
- Launch the web configurator

## Usage

After installation, you can:
- Access the web configurator through the desktop shortcut or by running:
  ```bash
  python3 web_configurator.py
  ```
- Control the service using standard systemd commands:
  ```bash
  systemctl --user start Remind2Rest    # Start the service
  systemctl --user stop Remind2Rest     # Stop the service
  systemctl --user status Remind2Rest   # Check service status
  ```

## Uninstallation

To remove Remind2Rest, run:
```bash
python3 setup.py
```
And select the uninstall option when prompted.

## License

MIT License - Feel free to use and modify as needed.
