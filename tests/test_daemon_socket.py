"""Tests for daemon_socket helpers.

wait_for_daemon_socket() — race-condition fix:
when the GUI calls `systemctl start spacemouse-desktop` it returns as soon
as the unit forks, but the daemon needs a beat to bind its command socket.
wait_for_daemon_socket() exists to bridge that gap so the first PROFILE
command isn't dropped against an empty socket.

query_device_info() — DEVICE response parser:
pure-function tests; mock send_daemon_cmd to feed canned wire responses.
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


# ── query_device_info() ──────────────────────────────────────────────


@pytest.fixture
def patched_send(monkeypatch):
    """Patch send_daemon_cmd to return a canned response per test."""

    def install(response):
        monkeypatch.setattr(daemon_socket, "send_daemon_cmd", lambda _cmd: response)

    return install


def test_query_device_info_parses_typical_response(patched_send):
    patched_send("OK vid=256f pid=c635 buttons=2 known=1 name=3Dconnexion SpaceMouse Compact")
    info = daemon_socket.query_device_info()
    assert info == {
        "vid": 0x256F,
        "pid": 0xC635,
        "button_count": 2,
        "known": True,
        "name": "3Dconnexion SpaceMouse Compact",
    }


def test_query_device_info_handles_name_with_multiple_spaces(patched_send):
    # The whole "rest of line" past the first "name=" is the device name —
    # spaces inside it must round-trip verbatim.
    patched_send("OK vid=046d pid=c629 buttons=31 known=1 name=3Dconnexion SpacePilot Pro")
    info = daemon_socket.query_device_info()
    assert info is not None
    assert info["name"] == "3Dconnexion SpacePilot Pro"
    assert info["button_count"] == 31
    assert info["known"] is True


def test_query_device_info_trims_trailing_newline_in_name(patched_send):
    # The daemon's snprintf appends "\n"; send_daemon_cmd usually strips
    # via recv().decode().strip(), but defend against a stray \r etc.
    patched_send("OK vid=256f pid=c635 buttons=2 known=1 name=3Dconnexion SpaceMouse Compact\n")
    info = daemon_socket.query_device_info()
    assert info is not None
    assert info["name"] == "3Dconnexion SpaceMouse Compact"


def test_query_device_info_unknown_device_known_zero(patched_send):
    patched_send("OK vid=1234 pid=5678 buttons=0 known=0 name=Unknown SpaceMouse")
    info = daemon_socket.query_device_info()
    assert info is not None
    assert info["known"] is False
    assert info["button_count"] == 0


def test_query_device_info_none_response(patched_send):
    patched_send("NONE")
    assert daemon_socket.query_device_info() is None


def test_query_device_info_daemon_unreachable(patched_send):
    patched_send(None)
    assert daemon_socket.query_device_info() is None


def test_query_device_info_rejects_unknown_prefix(patched_send):
    patched_send("ERR something went wrong")
    assert daemon_socket.query_device_info() is None


def test_query_device_info_rejects_missing_name_field(patched_send):
    # Defensive: if a future daemon drops the name= field entirely the
    # parser should refuse rather than returning a stub with name="".
    patched_send("OK vid=256f pid=c635 buttons=2 known=1")
    assert daemon_socket.query_device_info() is None


def test_query_device_info_rejects_garbage_numbers(patched_send):
    patched_send("OK vid=zz pid=c635 buttons=2 known=1 name=Whatever")
    assert daemon_socket.query_device_info() is None
