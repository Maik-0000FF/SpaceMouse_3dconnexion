"""Tests for wait_for_daemon_socket() — daemon-socket race-condition fix.

When the GUI calls `systemctl start spacemouse-desktop` it returns as soon
as the unit forks, but the daemon needs a beat to bind its command socket.
wait_for_daemon_socket() exists to bridge that gap so the first PROFILE
command isn't dropped against an empty socket.
"""

import socket
import threading
import time

import pytest
from spacemouse_config import daemon_socket


@pytest.fixture
def patched_sock_path(monkeypatch, tmp_path):
    """Point daemon_socket.SOCK_PATH at a fresh path for each test."""
    p = tmp_path / "spacemouse-cmd.sock"
    monkeypatch.setattr(daemon_socket, "SOCK_PATH", str(p))
    return str(p)


def _listen_unix(path):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    return server


def test_returns_true_when_socket_already_listening(patched_sock_path):
    server = _listen_unix(patched_sock_path)
    try:
        assert daemon_socket.wait_for_daemon_socket(timeout=0.5) is True
    finally:
        server.close()


def test_returns_false_when_socket_never_appears(patched_sock_path):
    start = time.monotonic()
    result = daemon_socket.wait_for_daemon_socket(timeout=0.2)
    elapsed = time.monotonic() - start
    assert result is False
    # Should have waited approximately the full timeout — not bailed out
    # early, not run dramatically over (allow generous slack for slow CI).
    assert 0.15 <= elapsed < 0.6


def test_returns_true_once_socket_appears_mid_wait(patched_sock_path):
    """The polling loop must pick up a late socket without exceeding timeout."""
    holder = []

    def delayed_listen():
        time.sleep(0.1)
        holder.append(_listen_unix(patched_sock_path))

    t = threading.Thread(target=delayed_listen)
    t.start()
    try:
        start = time.monotonic()
        assert daemon_socket.wait_for_daemon_socket(timeout=1.0) is True
        elapsed = time.monotonic() - start
        # We expect to return shortly after the socket appears (~0.1s + polling
        # granularity of 0.05s), well before the 1s timeout.
        assert elapsed < 0.5
    finally:
        t.join()
        if holder:
            holder[0].close()
