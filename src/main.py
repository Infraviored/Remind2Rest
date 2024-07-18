import os
import platform
from web_configurator import app
from service_manager import ServiceManager

def main():
    service_manager = ServiceManager()
    
    if not service_manager.is_installed():
        print("ReminderApp service is not installed. Installing...")
        service_manager.install()
    
    if not service_manager.is_running():
        print("ReminderApp service is not running. Starting...")
        service_manager.start()

    print("Starting web configurator...")
    app.run(debug=True, use_reloader=False)

if __name__ == "__main__":
    main()