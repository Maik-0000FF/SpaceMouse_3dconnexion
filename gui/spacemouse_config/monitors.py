"""Background threads: live SpaceMouse event reader and KWin window monitor."""

import ast
import ctypes
import json
import os
import select
import socket
import subprocess

from PySide6.QtCore import QThread, Signal

from .profile_match import find_matching_profile
from .window_backend import (
    GNOME_WAYLAND,
    HYPRLAND,
    KWIN,
    SWAY,
    X11,
    parse_hyprland_event,
    parse_sway_focus_event,
    parse_window_calls_list,
    parse_xprop_active_window,
    parse_xprop_wm_class,
    select_backend,
)

# ── libspnav ctypes bindings ──────────────────────────────────────────


class SpnavMotion(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("z", ctypes.c_int),
        ("rx", ctypes.c_int),
        ("ry", ctypes.c_int),
        ("rz", ctypes.c_int),
        ("period", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]


class SpnavButton(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("press", ctypes.c_int),
        ("bnum", ctypes.c_int),
    ]


class SpnavEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("motion", SpnavMotion),
        ("button", SpnavButton),
    ]


# ── SpaceMouse Reader Thread ──────────────────────────────────────────


class SpnavReader(QThread):
    """Reads SpaceMouse events via libspnav for live axis preview.

    Uses select() on the spnav file descriptor instead of busy-polling.
    Automatically suspends event reading when 3D apps (Blender/FreeCAD)
    are active — no point updating a hidden preview bar.
    """

    axes_updated = Signal(list)
    button_pressed = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self._running = True
        self._suspended = False
        self._lib = None

    def set_suspended(self, suspended):
        """Suspend/resume event reading (called when 3D apps gain/lose focus)."""
        self._suspended = suspended

    def run(self):
        try:
            self._lib = ctypes.CDLL("libspnav.so")
        except OSError:
            return

        self._lib.spnav_fd.restype = ctypes.c_int
        connected = False
        spnav_fd = -1

        ev = SpnavEvent()
        while self._running:
            # When suspended, disconnect from spnav so Blender/FreeCAD
            # get full event throughput (spacenavd multiplexing issue)
            if self._suspended:
                if connected:
                    self._lib.spnav_close()
                    connected = False
                self.msleep(200)
                continue

            if not connected:
                if self._lib.spnav_open() == -1:
                    self.msleep(1000)
                    continue
                spnav_fd = self._lib.spnav_fd()
                connected = True
                # Drain stale events from buffer
                while self._lib.spnav_poll_event(ctypes.byref(ev)):
                    pass

            ready, _, _ = select.select([spnav_fd], [], [], 0.5)
            if not ready:
                continue

            if self._lib.spnav_poll_event(ctypes.byref(ev)):
                if ev.type == 1:  # SPNAV_EVENT_MOTION
                    # spacenavd swaps Ry/Rz vs the kernel's evdev mapping for
                    # the SpaceNavigator: physical twist arrives on motion.ry,
                    # tilt left/right on motion.rz. The daemon reads the kernel
                    # device directly, so to keep the "rz = Yaw/Twist" semantics
                    # consistent across config keys and live preview, swap them
                    # back here.
                    self.axes_updated.emit(
                        [
                            ev.motion.x,
                            ev.motion.y,
                            ev.motion.z,
                            ev.motion.rx,
                            ev.motion.rz,
                            ev.motion.ry,
                        ]
                    )
                elif ev.type == 2:  # SPNAV_EVENT_BUTTON
                    self.button_pressed.emit(ev.button.bnum, bool(ev.button.press))

        if connected:
            self._lib.spnav_close()

    def stop(self):
        self._running = False
        self.wait(2000)


# ── Window Monitor Thread ─────────────────────────────────────────────


class KWinWindowMonitor(QThread):
    """Monitors active window via KWin scripting and switches daemon profile.

    KDE-Plasma-only. Loads a small JS into KWin via gdbus that prints
    SPACEMOUSE_WM:<resourceClass> on every window activation; the thread
    tails kwin_wayland's journal stream and emits window_changed.
    """

    window_changed = Signal(str, str)

    _KWIN_SCRIPT_NAME = "spacemouse-wm-watch"
    _KWIN_SCRIPT = (
        "workspace.windowActivated.connect(function(w) {\n"
        "    if (w && w.resourceClass)\n"
        '        print("SPACEMOUSE_WM:" + w.resourceClass);\n'
        "});\n"
        "var cur = workspace.activeWindow;\n"
        "if (cur && cur.resourceClass)\n"
        '    print("SPACEMOUSE_WM:" + cur.resourceClass);\n'
    )

    def __init__(self, profiles):
        super().__init__()
        self._running = True
        self._profiles = profiles
        self._last_profile = ""
        self._proc = None
        self._script_path = f"/run/user/{os.getuid()}/spacemouse_wm_watch.js"

    def update_profiles(self, profiles):
        self._profiles = profiles
        # Force re-evaluation: the next event must fire even if the resolved
        # profile name is identical, and reloading the KWin script re-emits
        # the initial workspace.activeWindow print so the currently focused
        # window gets re-classified against the new profile list right away.
        self._last_profile = ""
        if self._proc is not None:
            self._install_kwin_script()

    def _install_kwin_script(self):
        with open(self._script_path, "w") as f:
            f.write(self._KWIN_SCRIPT)
        try:
            subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.kde.KWin",
                    "--object-path",
                    "/Scripting",
                    "--method",
                    "org.kde.kwin.Scripting.unloadScript",
                    self._KWIN_SCRIPT_NAME,
                ],
                capture_output=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        try:
            subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.kde.KWin",
                    "--object-path",
                    "/Scripting",
                    "--method",
                    "org.kde.kwin.Scripting.loadScript",
                    self._script_path,
                    self._KWIN_SCRIPT_NAME,
                ],
                capture_output=True,
                timeout=2,
            )
            subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.kde.KWin",
                    "--object-path",
                    "/Scripting",
                    "--method",
                    "org.kde.kwin.Scripting.start",
                ],
                capture_output=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _uninstall_kwin_script(self):
        try:
            subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.kde.KWin",
                    "--object-path",
                    "/Scripting",
                    "--method",
                    "org.kde.kwin.Scripting.unloadScript",
                    self._KWIN_SCRIPT_NAME,
                ],
                capture_output=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _find_matching_profile(self, wm_class):
        return find_matching_profile(wm_class, self._profiles)

    def run(self):
        # Start the journal tail BEFORE loading the KWin script. The script
        # prints the currently active window the moment it starts, and we
        # need that line to land in the stream we're reading — otherwise the
        # daemon stays on whatever profile it booted with until the user
        # alt-tabs to another window.
        try:
            self._proc = subprocess.Popen(
                ["journalctl", "--user", "-t", "kwin_wayland", "-f", "-o", "cat", "--since", "now"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError:
            return
        self._install_kwin_script()
        stdout = self._proc.stdout
        if not stdout:
            return
        while self._running:
            line = stdout.readline()
            if not line:
                break
            if not line.startswith("SPACEMOUSE_WM:"):
                continue
            wm_class = line.strip().split(":", 1)[1]
            profile_name = self._find_matching_profile(wm_class)
            if profile_name != self._last_profile:
                self._last_profile = profile_name
                self.window_changed.emit(wm_class, profile_name)
        if self._proc:
            self._proc.terminate()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
        self._uninstall_kwin_script()
        self.wait(2000)


# ── X11 Window Monitor Thread ─────────────────────────────────────────


class X11WindowMonitor(QThread):
    """Monitors active window on X11 sessions via xprop.

    Spawns `xprop -spy -root _NET_ACTIVE_WINDOW` as a long-running
    process; every focus change prints one line. For each new window id
    we run a one-shot `xprop -id <id> WM_CLASS` to read the class and
    emit window_changed. Works on XFCE, Cinnamon, MATE, LXQt and the
    X11 sessions of KDE/GNOME.
    """

    window_changed = Signal(str, str)

    def __init__(self, profiles):
        super().__init__()
        self._running = True
        self._profiles = profiles
        self._last_profile = ""
        self._last_wid = None
        self._proc = None

    def update_profiles(self, profiles):
        self._profiles = profiles
        # Force re-evaluation on the next event.
        self._last_profile = ""
        self._last_wid = None

    def _wm_class_for(self, wid):
        try:
            result = subprocess.run(
                ["xprop", "-id", wid, "WM_CLASS"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        return parse_xprop_wm_class(result.stdout)

    def run(self):
        try:
            self._proc = subprocess.Popen(
                ["xprop", "-spy", "-root", "_NET_ACTIVE_WINDOW"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError:
            return
        stdout = self._proc.stdout
        if not stdout:
            return
        while self._running:
            line = stdout.readline()
            if not line:
                break
            wid = parse_xprop_active_window(line)
            if not wid or wid == self._last_wid:
                continue
            self._last_wid = wid
            wm_class = self._wm_class_for(wid)
            if not wm_class:
                continue
            profile_name = find_matching_profile(wm_class, self._profiles)
            if profile_name != self._last_profile:
                self._last_profile = profile_name
                self.window_changed.emit(wm_class, profile_name)
        if self._proc:
            self._proc.terminate()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
        self.wait(2000)


# ── Sway Window Monitor Thread ────────────────────────────────────────


class SwayWindowMonitor(QThread):
    """Monitors active window on Sway via swaymsg event subscription.

    `swaymsg -t subscribe -m '["window"]'` streams one JSON object per
    event. We pick out focus changes and read the focused container's
    app_id (native Wayland) or window_properties.class (Xwayland).
    """

    window_changed = Signal(str, str)

    def __init__(self, profiles):
        super().__init__()
        self._running = True
        self._profiles = profiles
        self._last_profile = ""
        self._proc = None

    def update_profiles(self, profiles):
        self._profiles = profiles
        self._last_profile = ""

    def run(self):
        try:
            self._proc = subprocess.Popen(
                ["swaymsg", "-t", "subscribe", "-m", '["window"]'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError:
            return
        stdout = self._proc.stdout
        if not stdout:
            return
        while self._running:
            line = stdout.readline()
            if not line:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            wm_class = parse_sway_focus_event(obj)
            if not wm_class:
                continue
            profile_name = find_matching_profile(wm_class, self._profiles)
            if profile_name != self._last_profile:
                self._last_profile = profile_name
                self.window_changed.emit(wm_class, profile_name)
        if self._proc:
            self._proc.terminate()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
        self.wait(2000)


# ── Hyprland Window Monitor Thread ────────────────────────────────────


class HyprlandWindowMonitor(QThread):
    """Monitors active window on Hyprland via the event socket.

    Hyprland exposes $XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock
    which streams events of the form 'EVENT>>DATA\\n'. We listen for
    activewindow events and pull the class out of 'CLASS,TITLE'. No
    external CLI needed — Python's UNIX socket support is enough.
    """

    window_changed = Signal(str, str)

    def __init__(self, profiles):
        super().__init__()
        self._running = True
        self._profiles = profiles
        self._last_profile = ""
        self._sock = None

    def update_profiles(self, profiles):
        self._profiles = profiles
        self._last_profile = ""

    def _socket_path(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not sig or not runtime:
            return None
        return f"{runtime}/hypr/{sig}/.socket2.sock"

    def run(self):
        path = self._socket_path()
        if not path:
            return
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(path)
        except OSError:
            self._sock = None
            return

        buf = b""
        while self._running:
            try:
                chunk = self._sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                wm_class = parse_hyprland_event(line.decode("utf-8", errors="replace"))
                if not wm_class:
                    continue
                profile_name = find_matching_profile(wm_class, self._profiles)
                if profile_name != self._last_profile:
                    self._last_profile = profile_name
                    self.window_changed.emit(wm_class, profile_name)
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.wait(2000)


# ── GNOME-Wayland Window Monitor Thread ───────────────────────────────


class GnomeWaylandWindowMonitor(QThread):
    """Monitors active window on GNOME-Wayland via the Window Calls extension.

    GNOME-Wayland exposes no portable window-listing protocol, so this
    backend depends on the user-installed `Window Calls` Shell extension
    (extensions.gnome.org/extension/4974). It publishes
    `org.gnome.Shell.Extensions.Windows.List` on the session bus,
    returning a JSON string with every window's wm_class and focus
    flag. There is no focus-change signal, so we poll on a fixed
    interval — 400 ms is a good trade-off between latency and CPU.
    """

    window_changed = Signal(str, str)

    _DBUS_DEST = "org.gnome.Shell"
    _DBUS_PATH = "/org/gnome/Shell/Extensions/Windows"
    _DBUS_METHOD = "org.gnome.Shell.Extensions.Windows.List"
    _POLL_INTERVAL_MS = 400

    def __init__(self, profiles):
        super().__init__()
        self._running = True
        self._profiles = profiles
        self._last_profile = ""
        self._last_class = None

    def update_profiles(self, profiles):
        self._profiles = profiles
        self._last_profile = ""
        self._last_class = None

    @classmethod
    def probe(cls):
        """Return True if the Window Calls extension is reachable on D-Bus."""
        try:
            result = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    cls._DBUS_DEST,
                    "--object-path",
                    cls._DBUS_PATH,
                    "--method",
                    cls._DBUS_METHOD,
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        return result.returncode == 0

    def _query(self):
        try:
            result = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    self._DBUS_DEST,
                    "--object-path",
                    self._DBUS_PATH,
                    "--method",
                    self._DBUS_METHOD,
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:
            return None
        # gdbus wraps the returned string in Python-tuple syntax:
        # ('[{"wm_class": "firefox", ...}]',)
        try:
            value = ast.literal_eval(result.stdout.strip())
        except (SyntaxError, ValueError):
            return None
        if isinstance(value, tuple) and value and isinstance(value[0], str):
            return value[0]
        return None

    def run(self):
        while self._running:
            payload = self._query()
            if payload is not None:
                wm_class = parse_window_calls_list(payload)
                if wm_class and wm_class != self._last_class:
                    self._last_class = wm_class
                    profile_name = find_matching_profile(wm_class, self._profiles)
                    if profile_name != self._last_profile:
                        self._last_profile = profile_name
                        self.window_changed.emit(wm_class, profile_name)
            self.msleep(self._POLL_INTERVAL_MS)

    def stop(self):
        self._running = False
        self.wait(2000)


# ── Factory ───────────────────────────────────────────────────────────


def make_window_monitor(profiles):
    """Return the right monitor for the current session, or None.

    None means no portable backend is available — the daemon stays on
    its default profile. On GNOME-Wayland that happens when the Window
    Calls extension is not installed; manual profile switching via the
    tray still works.
    """
    backend = select_backend()
    if backend == KWIN:
        return KWinWindowMonitor(profiles)
    if backend == X11:
        return X11WindowMonitor(profiles)
    if backend == SWAY:
        return SwayWindowMonitor(profiles)
    if backend == HYPRLAND:
        return HyprlandWindowMonitor(profiles)
    if backend == GNOME_WAYLAND and GnomeWaylandWindowMonitor.probe():
        return GnomeWaylandWindowMonitor(profiles)
    return None
