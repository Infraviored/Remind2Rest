# Remind2Rest

**Remind2Rest** is an interactive application tailored to promote better health habits, especially for those who spend extended periods in front of a computer. By leveraging visual cues and reminders, it helps users to take breaks, relax their eyes, and maintain proper posture.

## Features

  
- **Eye Relax Reminder**: Encourages users to look away from the screen periodically to reduce eye strain. The reminder flashes alternating colors to promote distance gazing.
  
- **Posture Reminder**: Periodically reminds users to correct their sitting posture. Users can also rate their current posture, providing a feedback loop to improve over time.

- **Dynamic Plotting**: Offers a visualization of posture ratings over time.

- **Configuration GUI**: A user-friendly graphical interface (`setup.py`) to adjust various settings of the application.

- **Service Integration**: The application can be set up as a system service, ensuring that it runs in the background and starts automatically on boot.

- **Desktop Entry Creation**: Users can easily create a desktop entry for swift access to the Configuration GUI.

## Dependencies

- `Python3`
- `apscheduler`
- `pillow`
- `matplotlib`
- `numpy`
- `scipy`


## Setup


1. **Clone the Repository**:
   ```
   git clone https://github.com/Infraviored/Remind2Rest.git
   ```

2. **Navigate to the Repository Directory**:
   ```
   cd Remind2Rest
   ```

3. **Configuration**:
   Run the Configuration GUI to customize the behavior of the reminders:
   ```
   python3 setup.py
   ```

   Using the Configuration GUI, you can:
   - Set frequencies and durations for both eye relaxation and posture reminders.
   - Enable or disable specific reminders.
   - Install the application as a system service.
   - Create a desktop entry for quick access to the configuration tool.

4. **Start Using Remind2Rest**:
   Once set up, Remind2Rest will operate in the background, delivering reminders based on your configured settings.
