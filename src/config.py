import os
import json
import socket
import logging

from src.library import fill_defaults

script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Platform-specific paths and socket configuration
if os.name == 'nt':
    appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~/AppData/Local'))
    base_dir = os.path.join(appdata, 'Remind2Rest')
    os.makedirs(base_dir, exist_ok=True)
    CONFIG_PATH = os.path.join(base_dir, 'reminder_config.json')
    LOG_PATH = os.path.join(base_dir, 'Remind2Rest.log')
    RATINGS_FILE_PATH = os.path.join(base_dir, 'posture_ratings.txt')
    WATER_LOG_PATH = os.path.join(base_dir, 'water_log.txt')
    ADDR = ('127.0.0.1', 55555)
    SOCKET_FAMILY = socket.AF_INET
else:
    CONFIG_PATH = os.path.expanduser("~/.config/Remind2Rest/reminder_config.json")
    LOG_PATH = os.path.expanduser("~/.local/share/Remind2Rest/Remind2Rest.log")
    RATINGS_FILE_PATH = os.path.join(script_dir, 'posture_ratings.txt')
    WATER_LOG_PATH = os.path.join(script_dir, 'water_log.txt')
    ADDR = os.path.expanduser("~/.Remind2Rest.sock")
    SOCKET_FAMILY = getattr(socket, 'AF_UNIX', socket.AF_INET)

def load_config():
    try:
        if not os.path.exists(CONFIG_PATH):
            default_config = fill_defaults({"global_interval": 60})
            save_config(default_config)
            return default_config
        with open(CONFIG_PATH, "r") as file:
            config = json.load(file)
        validate_config(config)
        return fill_defaults(config)
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
    return None

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as file:
            json.dump(config, file, indent=2)
    except Exception as e:
        logging.error(f"Error saving configuration: {e}")

def validate_config(config):
    if "global_interval" not in config:
        raise ValueError("Missing 'global_interval' in config")
    # Missing reminder types or keys are filled from the library by load_config.
