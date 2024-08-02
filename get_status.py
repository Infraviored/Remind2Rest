import socket
import json

SOCKET_PATH = '/tmp/reminderapp.sock'

def get_status():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        try:
            s.connect(SOCKET_PATH)
            return json.loads(s.recv(1024).decode())
        except:
            return {"running": False, "next_reminder": None, "time_to_next": None}

print(get_status())