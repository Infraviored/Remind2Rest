import os
import socket
from src.config import ADDR, SOCKET_FAMILY

def cleanup_socket():
    if os.name != 'nt' and isinstance(ADDR, str) and os.path.exists(ADDR):
        try:
            os.remove(ADDR)
        except Exception:
            pass

def create_server_socket():
    cleanup_socket()
    s = socket.socket(SOCKET_FAMILY, socket.SOCK_STREAM)
    try:
        if SOCKET_FAMILY == socket.AF_INET:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(ADDR)
        s.listen()
        s.setblocking(False)
        return s
    except Exception as e:
        s.close()
        raise e
