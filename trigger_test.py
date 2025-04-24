#!/usr/bin/env python3
import socket
import json

# Prepare the custom reminder message
msg = {
    "action": "custom_reminder",
    "message": "Drink water!",
    "flashing": True,
    "flashing_freq": 10,       # 20 Hz flashing
    "duration": 8,  # seconds (0 = infinite)
    "cancel_key": "Escape",  # Press Escape to close immediately
    "initial_color": "white", # Start with white background
    "fontsize": 180
}

SOCKET_PATH = "/home/schneider/.Remind2Rest.sock"

try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(SOCKET_PATH)
        s.sendall(json.dumps(msg).encode())
        response = s.recv(1024)
        print(f"Response from Remind2Rest: {response.decode()}")
except Exception as e:
    print(f"Failed to trigger reminder: {e}")
