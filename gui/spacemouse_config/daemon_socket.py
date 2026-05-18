"""UNIX-socket helpers for talking to the spacemouse-desktop daemon.

Kept Qt-free so the helpers can be unit-tested without pulling in PySide6.
"""

import socket
import time

from .constants import SOCK_PATH


def send_daemon_cmd(cmd):
    """Send command to spacemouse-desktop daemon via UNIX socket."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(SOCK_PATH)
        sock.sendall(f"{cmd}\n".encode())
        response = sock.recv(1024).decode().strip()
        sock.close()
        return response
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return None


def query_device_info():
    """Ask the daemon what device is currently open.

    Returns a dict like ``{"vid": 0x256f, "pid": 0xc635,
    "button_count": 2, "known": True, "name": "3Dconnexion …"}`` or
    ``None`` if no device is attached / the daemon is unreachable.
    """
    resp = send_daemon_cmd("DEVICE")
    if not resp or resp == "NONE":
        return None
    if not resp.startswith("OK "):
        return None
    # Response shape (positional — name= must remain the final field):
    #   OK vid=XXXX pid=XXXX buttons=N known=0|1 name=<rest of line>
    body = resp[3:]
    head, sep, name_value = body.partition("name=")
    if not sep:
        return None
    info = {}
    for token in head.split():
        key, _, value = token.partition("=")
        if key:
            info[key] = value
    try:
        return {
            "vid": int(info.get("vid", "0"), 16),
            "pid": int(info.get("pid", "0"), 16),
            "button_count": int(info.get("buttons", "0")),
            "known": info.get("known", "0") == "1",
            "name": name_value.strip(),
        }
    except ValueError:
        return None


def wait_for_daemon_socket(timeout=2.0):
    """Block until the daemon command socket is reachable, or timeout.

    systemctl start returns as soon as the unit is forked (Type=simple),
    but the daemon needs a moment to load config and bind the socket.
    Callers that send commands right after starting the service must wait
    for the socket, otherwise the first PROFILE command is dropped and
    the daemon stays on its initial profile.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            sock.connect(SOCK_PATH)
            sock.close()
            return True
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            time.sleep(0.05)
    return False
