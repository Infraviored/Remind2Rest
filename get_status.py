import socket
import json
import os

SOCKET_PATH = os.path.expanduser('~/.reminderapp.sock')

def get_status():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        try:
            s.connect(SOCKET_PATH)
            return json.loads(s.recv(1024).decode())
        except Exception as e:
            print(f"Error connecting to socket: {e}")
            return {"running": False, "next_reminder": None, "time_to_next": None}

print(get_status())