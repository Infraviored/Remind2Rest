<img src="Remind2Rest.png" alt="" width="64" height="64">

# Remind2Rest

**Remind2Rest** is an interactive application tailored to promote better health habits, especially for those who spend extended periods in front of a computer. By leveraging visual cues and reminders, it helps users to take breaks, relax their eyes, and maintain proper posture.

## Features

- **Eye Relax Reminder**: Encourages users to look away from the screen periodically to reduce eye strain. The reminder flashes alternating colors to promote distance gazing.
- **Posture Reminder**: Periodically reminds users to correct their sitting posture. Users can also rate their current posture, providing a feedback loop to improve over time.
- **Dynamic Plotting**: Offers a visualization of posture ratings over time.
- **Cross-Platform Support**:
  - **Windows**: Native support with always-on-top Tkinter overlays.
  - **Linux (Wayland)**: High-performance GTK overlays with Layer Shell support.
  - **Linux (X11)**: Reliable Tkinter fullscreen overlays.
- **Settings window**: A small desktop window (pywebview) to adjust reminders, start/stop the service and toggle autostart. No local web server.
- **GNOME Shell extension**: Countdown to the next reminder in the top bar, with pause, "remind me now" and a shortcut to the settings.
- **Service Integration**: Supports running as a background service on both Windows (via Startup) and Linux (via systemd).

## Dependencies

- `Python 3.8+`
- `apscheduler`
- `pillow`
- `matplotlib`
- `numpy`
- `scipy`
- `pywebview` (Linux needs `gir1.2-webkit2-4.1`)
- `PyGObject` (Linux/Wayland only)

## Setup

### 1. Clone the Repository
```bash
git clone https://github.com/Infraviored/Remind2Rest.git
cd Remind2Rest
```

### 2. Installation

#### **Linux (Ubuntu/Debian)**
Run the setup script to install dependencies, create a virtual environment, and set up a systemd user service:
```bash
python3 setup.py
```
This will:
- Install system dependencies (`python3-tk`, `python3-pil.imagetk`).
- Create a virtual environment in `~/.local/share/Remind2Rest/venv`.
- Set up a systemd service for the background reminder app.
- Create a desktop entry for the settings window.
- On GNOME: link and enable the top bar extension (log out and back in once so GNOME Shell loads it). Elsewhere: autostart the AppIndicator tray icon.

#### **Windows**
Run the PowerShell installer script:
1. Open PowerShell in the project directory.
2. Run:
   ```powershell
   .\Install-Remind2Rest.ps1
   ```
This will:
- Create a virtual environment in `%LOCALAPPDATA%\Remind2Rest\venv`.
- Install all requirements.
- Add Remind2Rest to your **Windows Startup** folder.
- Create a **Desktop Shortcut** for the settings window.

### 3. Usage
Once installed, the background service will start automatically on login. Open the settings from the app menu (**Remind2Rest**), the GNOME top bar menu, or with `python configurator.py`.

The top bar extension and the settings window talk to the service over its socket (`~/.Remind2Rest.sock`) with plain-text commands: `STATUS`, `RELOAD`, `PAUSE <minutes>`, `RESUME`, `TRIGGER eye_relax|posture`.
