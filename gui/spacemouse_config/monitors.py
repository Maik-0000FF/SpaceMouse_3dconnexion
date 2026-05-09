"""Background threads: live SpaceMouse event reader and KWin window monitor."""

import ctypes
import os
import select
import struct
import subprocess

from PySide6.QtCore import QThread, Signal

# ── libspnav ctypes bindings ──────────────────────────────────────────

class SpnavMotion(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("z", ctypes.c_int),
        ("rx", ctypes.c_int), ("ry", ctypes.c_int), ("rz", ctypes.c_int),
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
                    self.axes_updated.emit([
                        ev.motion.x, ev.motion.y, ev.motion.z,
                        ev.motion.rx, ev.motion.rz, ev.motion.ry
                    ])
                elif ev.type == 2:  # SPNAV_EVENT_BUTTON
                    self.button_pressed.emit(ev.button.bnum, bool(ev.button.press))

        if connected:
            self._lib.spnav_close()

    def stop(self):
        self._running = False
        self.wait(2000)

# ── Window Monitor Thread ─────────────────────────────────────────────

class WindowMonitor(QThread):
    """Monitors active window via KWin scripting and switches daemon profile."""
    window_changed = Signal(str, str)

    _KWIN_SCRIPT_NAME = "spacemouse-wm-watch"
    _KWIN_SCRIPT = (
        'workspace.windowActivated.connect(function(w) {\n'
        '    if (w && w.resourceClass)\n'
        '        print("SPACEMOUSE_WM:" + w.resourceClass);\n'
        '});\n'
        'var cur = workspace.activeWindow;\n'
        'if (cur && cur.resourceClass)\n'
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
                ["gdbus", "call", "--session",
                 "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                 "--method", "org.kde.kwin.Scripting.unloadScript",
                 self._KWIN_SCRIPT_NAME],
                capture_output=True, timeout=2)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        try:
            subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                 "--method", "org.kde.kwin.Scripting.loadScript",
                 self._script_path, self._KWIN_SCRIPT_NAME],
                capture_output=True, timeout=2)
            subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                 "--method", "org.kde.kwin.Scripting.start"],
                capture_output=True, timeout=2)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _uninstall_kwin_script(self):
        try:
            subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                 "--method", "org.kde.kwin.Scripting.unloadScript",
                 self._KWIN_SCRIPT_NAME],
                capture_output=True, timeout=2)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _find_matching_profile(self, wm_class):
        wm_lower = wm_class.lower()
        for name, profile in self._profiles.items():
            if name == "default":
                continue
            for wc in profile.get("match_wm_class", []):
                wc_lower = wc.lower()
                if (wc_lower == wm_lower or
                    wm_lower.startswith(wc_lower) or
                    wc_lower in wm_lower):
                    return name
        return "default"

    def run(self):
        # Start the journal tail BEFORE loading the KWin script. The script
        # prints the currently active window the moment it starts, and we
        # need that line to land in the stream we're reading — otherwise the
        # daemon stays on whatever profile it booted with until the user
        # alt-tabs to another window.
        try:
            self._proc = subprocess.Popen(
                ["journalctl", "--user", "-t", "kwin_wayland",
                 "-f", "-o", "cat", "--since", "now"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
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


# ── Mouse Click Monitor ───────────────────────────────────────────────

class MouseClickMonitor(QThread):
    """Detects global mouse button presses via /dev/input/event* devices.

    Wayland blocks userspace global click capture, so we read evdev
    directly. Used as the focus signal for the GUI: the compositor's
    notion of "active window" doesn't change on a desktop click, but
    a real mouse press still happens — we catch it here and let the
    app decide focus by comparing cursor position to GUI geometry.
    """
    clicked = Signal()

    _EVENT_FORMAT = "@qqHHi"
    _EVENT_SIZE = struct.calcsize(_EVENT_FORMAT)
    _EV_KEY = 0x01
    _BTN_MOUSE = (0x110, 0x111, 0x112)  # LEFT, RIGHT, MIDDLE

    def __init__(self):
        super().__init__()
        self._running = True
        self._fds = []

    @staticmethod
    def _find_mouse_event_devices():
        paths = []
        try:
            with open("/proc/bus/input/devices") as f:
                blocks = f.read().split("\n\n")
        except (IOError, OSError):
            return paths
        for block in blocks:
            if "mouse" not in block:
                continue
            for line in block.splitlines():
                if not line.startswith("H: Handlers="):
                    continue
                for h in line[len("H: Handlers="):].split():
                    if h.startswith("event"):
                        paths.append(f"/dev/input/{h}")
                break
        return paths

    def run(self):
        for path in self._find_mouse_event_devices():
            try:
                self._fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        if not self._fds:
            return
        while self._running:
            try:
                ready, _, _ = select.select(self._fds, [], [], 0.5)
            except (OSError, ValueError):
                break
            for fd in ready:
                try:
                    data = os.read(fd, self._EVENT_SIZE * 32)
                except (OSError, BlockingIOError):
                    continue
                emitted = False
                for i in range(0, len(data) - self._EVENT_SIZE + 1, self._EVENT_SIZE):
                    _, _, evtype, code, value = struct.unpack(
                        self._EVENT_FORMAT, data[i:i + self._EVENT_SIZE])
                    if (evtype == self._EV_KEY and value == 1
                            and code in self._BTN_MOUSE):
                        if not emitted:
                            self.clicked.emit()
                            emitted = True
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []

    def stop(self):
        self._running = False
        self.wait(2000)
