import json
import os

class ConfigManager:
    def __init__(self):
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.config_path = os.path.join(self.script_dir, 'reminder_config.json')

    def load_config(self):
        try:
            with open(self.config_path, 'r') as file:
                config = json.load(file)
            self.validate_config(config)
            return config
        except (json.JSONDecodeError, FileNotFoundError, ValueError) as e:
            print(f"Error loading configuration: {str(e)}")
            return self.get_default_config()

    def save_config(self, config):
        try:
            self.validate_config(config)
            with open(self.config_path, 'w') as file:
                json.dump(config, file, indent=2)
            return True
        except ValueError as e:
            print(f"Error saving configuration: {str(e)}")
            return False

    def validate_config(self, config):
        if 'global_interval' not in config:
            raise ValueError("Missing 'global_interval' in config")
        for module in ['eye_relax', 'posture']:
            if module not in config:
                raise ValueError(f"Missing '{module}' in config")
            if 'enabled' not in config[module]:
                raise ValueError(f"Missing 'enabled' for module {module}")
            if 'reminders' not in config[module]:
                raise ValueError(f"Missing 'reminders' for module {module}")
        
        # Validate specific settings for each module
        if 'eye_relax' in config:
            if 'flash_frequency' not in config['eye_relax']:
                raise ValueError("Missing 'flash_frequency' in eye_relax config")
            if 'relax_duration' not in config['eye_relax']:
                raise ValueError("Missing 'relax_duration' in eye_relax config")
        
        if 'posture' in config:
            if 'wait_duration' not in config['posture']:
                raise ValueError("Missing 'wait_duration' in posture config")

    def get_default_config(self):
        return {
            "global_interval": 60,
            "eye_relax": {
                "enabled": True,
                "reminders": [20, 40],
                "flash_frequency": 0.5,
                "relax_duration": 20
            },
            "posture": {
                "enabled": True,
                "reminders": [30],
                "wait_duration": 10
            }
        }

    def print_config_summary(self, config):
        print(f"Reminder Interval: {config['global_interval']}min")
        print(f"Eye Relax Reminders: {', '.join(map(str, config['eye_relax']['reminders'])) if config['eye_relax']['enabled'] else 'Not set'}")
        print(f"Posture Reminders: {', '.join(map(str, config['posture']['reminders'])) if config['posture']['enabled'] else 'Not set'}")
        print()