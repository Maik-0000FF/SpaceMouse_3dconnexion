#!/usr/bin/env python3
"""
SpaceMouse Control — Unified configuration for Desktop, FreeCAD, and Blender.

PySide6 application with:
- System tray icon with profile switching
- Dark-themed settings window with sidebar navigation
- Desktop daemon profile editor (scroll, zoom, axes, buttons)
- FreeCAD SpaceMouse settings (direct user.cfg XML editing)
- Blender NDOF settings (JSON config + startup script installer)
- Live SpaceMouse axis preview bar
- Automatic active window detection via KWin D-Bus
- UNIX socket communication with spacemouse-desktop daemon
"""

import sys
import os
import json
import shutil
import socket
import subprocess
import signal
import atexit
import ctypes
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QComboBox, QSlider,
    QPushButton, QLineEdit, QProgressBar, QFormLayout,
    QMessageBox, QMenu, QInputDialog, QSystemTrayIcon,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPropertyAnimation, Property, QEasingCurve, QSize
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont

# ── Constants ──────────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".config" / "spacemouse"
CONFIG_PATH = CONFIG_DIR / "config.json"
BLENDER_NDOF_PATH = CONFIG_DIR / "blender-ndof.json"
SOCK_PATH = f"/run/user/{os.getuid()}/spacemouse-cmd.sock"

BLENDER_STARTUP_DIR = Path.home() / ".config" / "blender" / "5.0" / "scripts" / "startup"
BLENDER_SYNC_SCRIPT = "spacemouse_sync.py"

AXIS_ACTIONS = ["none", "scroll_h", "scroll_v", "zoom", "desktop_switch"]
AXIS_ACTION_LABELS = ["None", "Horizontal Scroll", "Vertical Scroll", "Zoom", "Desktop Switch"]

BTN_ACTIONS = ["none", "overview", "show_desktop"]
BTN_ACTION_LABELS = ["None", "Overview (Expose)", "Show Desktop"]

AXIS_NAMES = ["TX (Left/Right)", "TY (Push/Pull)", "TZ (Up/Down)",
              "RX (Pitch)", "RY (Yaw/Twist)", "RZ (Roll)"]
AXIS_KEYS = ["tx", "ty", "tz", "rx", "ry", "rz"]

FREECAD_BTN_COMMANDS = [
    "Std_ViewFitAll", "Std_ViewHome", "Std_ViewIsometric",
    "Std_ViewFront", "Std_ViewTop", "Std_ViewRight",
]
FREECAD_BTN_LABELS = [
    "Fit All", "Home View", "Isometric",
    "Front", "Top", "Right",
]

FREECAD_NAV_STYLES = [
    "Gui::InventorNavigationStyle",
    "Gui::BlenderNavigationStyle",
    "Gui::CADNavigationStyle",
    "Gui::OpenCascadeNavigationStyle",
    "Gui::RevitNavigationStyle",
]
FREECAD_NAV_LABELS = ["Inventor", "Blender", "CAD", "OpenCascade", "Revit"]

FREECAD_ORBIT_STYLES = {"Trackball": 1, "Turntable": 0}

# ── Dark Theme QSS ────────────────────────────────────────────────────

DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: sans-serif;
    font-size: 13px;
}

/* Sidebar */
#sidebar {
    background-color: #181825;
    border-right: 1px solid #313244;
}
#sidebar QPushButton {
    background-color: transparent;
    color: #a6adc8;
    border: none;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: left;
    font-size: 13px;
    font-weight: bold;
}
#sidebar QPushButton:hover {
    background-color: #313244;
    color: #cdd6f4;
}
#sidebar QPushButton:checked {
    background-color: #5294e2;
    color: #ffffff;
}

/* Cards / Sections */
QFrame.card {
    background-color: #2a2a3e;
    border-radius: 8px;
    padding: 12px;
}
QFrame.card QLabel.section-title {
    color: #a6adc8;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    padding-bottom: 4px;
}

/* Labels */
QLabel {
    color: #cdd6f4;
    background: transparent;
}
QLabel.dimmed {
    color: #a6adc8;
}
QLabel.value-label {
    color: #5294e2;
    font-weight: bold;
    min-width: 40px;
}

/* Sliders */
QSlider::groove:horizontal {
    background: #45475a;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #5294e2;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal {
    background: #5294e2;
    border-radius: 3px;
}

/* Combos */
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 160px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #a6adc8;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #5294e2;
    border: 1px solid #45475a;
    border-radius: 4px;
}

/* Checkboxes — hide default indicator, ToggleSwitch paints itself */
QCheckBox {
    spacing: 8px;
    color: #cdd6f4;
}

/* Buttons */
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton#apply-btn {
    background-color: #5294e2;
    color: #ffffff;
    border: none;
    padding: 8px 32px;
    font-size: 14px;
}
QPushButton#apply-btn:hover {
    background-color: #6ba4f0;
}

/* Line edits */
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 10px;
}

/* Progress bars (live preview) */
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 3px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #5294e2;
    border-radius: 3px;
}

/* Scroll area */
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* Live bar */
#live-bar {
    background-color: #181825;
    border-top: 1px solid #313244;
}

/* Warning label */
QLabel.warning {
    color: #f9e2af;
    background-color: #3a3636;
    border-radius: 6px;
    padding: 8px;
}
"""

# ── Daemon Communication ──────────────────────────────────────────────

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
    """Reads SpaceMouse events via libspnav for live axis preview."""
    axes_updated = Signal(list)
    button_pressed = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self._running = True
        self._lib = None

    def run(self):
        try:
            self._lib = ctypes.CDLL("libspnav.so")
        except OSError:
            return

        if self._lib.spnav_open() == -1:
            return

        ev = SpnavEvent()
        while self._running:
            ret = self._lib.spnav_poll_event(ctypes.byref(ev))
            if ret == 0:
                self.msleep(16)
                continue
            if ev.type == 1:
                self.axes_updated.emit([
                    ev.motion.x, ev.motion.y, ev.motion.z,
                    ev.motion.rx, ev.motion.ry, ev.motion.rz
                ])
            elif ev.type == 2:
                self.button_pressed.emit(ev.button.bnum, bool(ev.button.press))

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
        self._install_kwin_script()
        try:
            self._proc = subprocess.Popen(
                ["journalctl", "--user", "-t", "kwin_wayland",
                 "-f", "-o", "cat", "--since", "now"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except FileNotFoundError:
            return
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
                send_daemon_cmd(f"PROFILE {profile_name}")
        if self._proc:
            self._proc.terminate()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
        self._uninstall_kwin_script()
        self.wait(2000)

# ── FreeCAD Config (XML) ──────────────────────────────────────────────

class FreeCADConfig:
    """Read/write FreeCAD user.cfg XML for SpaceMouse settings."""

    _CANDIDATES = [
        Path.home() / ".config" / "FreeCAD" / "user.cfg",
        Path.home() / ".FreeCAD" / "user.cfg",
        Path.home() / ".local" / "share" / "FreeCAD" / "user.cfg",
    ]

    def __init__(self):
        self.path = None
        for c in self._CANDIDATES:
            if c.exists():
                self.path = c
                break

    def is_available(self):
        return self.path is not None

    @staticmethod
    def is_running():
        try:
            result = subprocess.run(
                ["pgrep", "-x", "FreeCAD"], capture_output=True, timeout=2)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    # XML helpers (same logic as freecad-spacemouse-patch.sh)
    @staticmethod
    def _find_group(parent, name):
        for child in parent:
            if child.tag == "FCParamGroup" and child.get("Name") == name:
                return child
        return None

    @staticmethod
    def _ensure_group(parent, name):
        grp = FreeCADConfig._find_group(parent, name)
        if grp is not None:
            return grp
        return ET.SubElement(parent, "FCParamGroup", Name=name)

    @staticmethod
    def _get_bool(parent, name, default=False):
        for child in parent:
            if child.tag == "FCBool" and child.get("Name") == name:
                return child.get("Value") == "1"
        return default

    @staticmethod
    def _get_int(parent, name, default=0):
        for child in parent:
            if child.tag == "FCInt" and child.get("Name") == name:
                try:
                    return int(child.get("Value"))
                except (TypeError, ValueError):
                    return default
        return default

    @staticmethod
    def _get_text(parent, name, default=""):
        for child in parent:
            if child.tag == "FCText" and child.get("Name") == name:
                val = child.get("Value")
                if val is not None:
                    return val
                return (child.text or "").strip()
        return default

    @staticmethod
    def _set_bool(parent, name, value):
        val_str = "1" if value else "0"
        for child in parent:
            if child.tag == "FCBool" and child.get("Name") == name:
                child.set("Value", val_str)
                return
        ET.SubElement(parent, "FCBool", Name=name, Value=val_str)

    @staticmethod
    def _set_int(parent, name, value):
        val_str = str(value)
        for child in parent:
            if child.tag == "FCInt" and child.get("Name") == name:
                child.set("Value", val_str)
                return
        ET.SubElement(parent, "FCInt", Name=name, Value=val_str)

    @staticmethod
    def _set_text(parent, name, value):
        for child in parent:
            if child.tag == "FCText" and child.get("Name") == name:
                if child.get("Value") is not None:
                    child.set("Value", value)
                else:
                    child.text = value
                return
        elem = ET.SubElement(parent, "FCText", Name=name)
        elem.text = value

    def read(self):
        """Read SpaceMouse-related settings from user.cfg. Returns dict."""
        defaults = {
            "global_sensitivity": -15,
            "flip_yz": True,
            "dominant": False,
            "pan_lr_enable": True, "pan_ud_enable": True, "zoom_enable": True,
            "tilt_enable": True, "roll_enable": True, "spin_enable": True,
            "pan_lr_reverse": False, "pan_ud_reverse": False, "zoom_reverse": False,
            "tilt_reverse": False, "roll_reverse": False, "spin_reverse": False,
            "btn0_command": "Std_ViewFitAll",
            "btn1_command": "Std_ViewHome",
            "nav_style": "Gui::BlenderNavigationStyle",
            "orbit_style": 1,
        }
        if not self.path:
            return defaults

        try:
            tree = ET.parse(self.path)
        except ET.ParseError:
            return defaults

        xml_root = tree.getroot()
        fc_root = self._find_group(xml_root, "Root")
        if fc_root is None:
            return defaults
        base_app = self._find_group(fc_root, "BaseApp")
        if base_app is None:
            return defaults

        # Spaceball settings (BaseApp/Spaceball/Motion)
        spaceball = self._find_group(base_app, "Spaceball")
        if spaceball is None:
            return defaults
        motion = self._find_group(spaceball, "Motion")

        result = dict(defaults)
        if motion is not None:
            result["global_sensitivity"] = self._get_int(motion, "GlobalSensitivity", -15)
            result["flip_yz"] = self._get_bool(motion, "FlipYZ", True)
            result["dominant"] = self._get_bool(motion, "Dominant", False)
            for axis in ["PanLR", "PanUD", "Zoom", "Tilt", "Roll", "Spin"]:
                key_en = f"{axis.lower()}_enable"
                key_rev = f"{axis.lower()}_reverse"
                # Normalize: PanLR -> panlr, PanUD -> panud
                key_en = axis[0].lower() + axis[1:].lower() + "_enable"
                key_rev = axis[0].lower() + axis[1:].lower() + "_reverse"
                # Simpler: just lowercase
                key_en = axis.lower() + "_enable"
                key_rev = axis.lower() + "_reverse"
                result[key_en] = self._get_bool(motion, f"{axis}Enable", True)
                result[key_rev] = self._get_bool(motion, f"{axis}Reverse", False)

        # Buttons (BaseApp/Spaceball/Buttons/0, /1)
        buttons = self._find_group(spaceball, "Buttons")
        if buttons is not None:
            btn0 = self._find_group(buttons, "0")
            if btn0 is not None:
                result["btn0_command"] = self._get_text(btn0, "Command", "Std_ViewFitAll")
            btn1 = self._find_group(buttons, "1")
            if btn1 is not None:
                result["btn1_command"] = self._get_text(btn1, "Command", "Std_ViewHome")

        # View preferences (BaseApp/Preferences/View)
        prefs = self._find_group(base_app, "Preferences")
        if prefs is not None:
            view = self._find_group(prefs, "View")
            if view is not None:
                result["nav_style"] = self._get_text(view, "NavigationStyle",
                                                     "Gui::BlenderNavigationStyle")
                result["orbit_style"] = self._get_int(view, "OrbitStyle", 1)

        return result

    def write(self, settings):
        """Write SpaceMouse-related settings to user.cfg."""
        if not self.path:
            return False

        try:
            tree = ET.parse(self.path)
        except ET.ParseError:
            return False

        xml_root = tree.getroot()
        fc_root = self._find_group(xml_root, "Root")
        if fc_root is None:
            return False
        base_app = self._find_group(fc_root, "BaseApp")
        if base_app is None:
            return False

        # Spaceball/Motion
        spaceball = self._ensure_group(base_app, "Spaceball")
        motion = self._ensure_group(spaceball, "Motion")

        self._set_int(motion, "GlobalSensitivity", settings.get("global_sensitivity", -15))
        self._set_bool(motion, "FlipYZ", settings.get("flip_yz", True))
        self._set_bool(motion, "Dominant", settings.get("dominant", False))

        for axis in ["PanLR", "PanUD", "Zoom", "Tilt", "Roll", "Spin"]:
            key_en = axis.lower() + "_enable"
            key_rev = axis.lower() + "_reverse"
            self._set_bool(motion, f"{axis}Enable", settings.get(key_en, True))
            self._set_bool(motion, f"{axis}Reverse", settings.get(key_rev, False))

        # Buttons
        buttons = self._ensure_group(spaceball, "Buttons")
        btn0 = self._ensure_group(buttons, "0")
        self._set_text(btn0, "Command", settings.get("btn0_command", "Std_ViewFitAll"))
        btn1 = self._ensure_group(buttons, "1")
        self._set_text(btn1, "Command", settings.get("btn1_command", "Std_ViewHome"))

        # View preferences
        prefs = self._ensure_group(base_app, "Preferences")
        view = self._ensure_group(prefs, "View")
        self._set_text(view, "NavigationStyle",
                       settings.get("nav_style", "Gui::BlenderNavigationStyle"))
        self._set_int(view, "OrbitStyle", settings.get("orbit_style", 1))

        tree.write(str(self.path), xml_declaration=True, encoding="utf-8")
        return True

# ── Blender Config (JSON) ─────────────────────────────────────────────

class BlenderConfig:
    """Read/write Blender NDOF settings as JSON + manage startup script."""

    DEFAULTS = {
        "ndof_sensitivity": 1.0,
        "ndof_orbit_sensitivity": 1.0,
        "ndof_deadzone": 0.1,
        "ndof_lock_horizon": False,
        "ndof_pan_yz_swap_axis": False,
        "ndof_zoom_invert": False,
        "ndof_rotx_invert_axis": False,
        "ndof_roty_invert_axis": False,
        "ndof_rotz_invert_axis": False,
        "ndof_panx_invert_axis": False,
        "ndof_pany_invert_axis": False,
        "ndof_panz_invert_axis": False,
    }

    def read(self):
        if BLENDER_NDOF_PATH.exists():
            try:
                with open(BLENDER_NDOF_PATH) as f:
                    saved = json.load(f)
                result = dict(self.DEFAULTS)
                result.update(saved)
                return result
            except (json.JSONDecodeError, IOError):
                pass
        return dict(self.DEFAULTS)

    def write(self, settings):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(BLENDER_NDOF_PATH, "w") as f:
            json.dump(settings, f, indent=2)

    def is_script_installed(self):
        return (BLENDER_STARTUP_DIR / BLENDER_SYNC_SCRIPT).exists()

    def install_startup_script(self):
        """Copy blender_spacemouse_sync.py to Blender's startup dir."""
        BLENDER_STARTUP_DIR.mkdir(parents=True, exist_ok=True)
        src = Path(__file__).parent / "blender_spacemouse_sync.py"
        dst = BLENDER_STARTUP_DIR / BLENDER_SYNC_SCRIPT
        if src.exists():
            shutil.copy2(src, dst)
            return True
        return False

# ── UI Helper Widgets ─────────────────────────────────────────────────

def make_card(title=None):
    """Create a styled card frame with optional section title."""
    card = QFrame()
    card.setProperty("class", "card")
    card.setObjectName("card")
    card.setStyleSheet(
        "QFrame#card { background-color: #2a2a3e; border-radius: 8px; padding: 12px; }")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold;")
        layout.addWidget(lbl)
    return card, layout


def make_slider(minimum, maximum, value, decimals=0, suffix=""):
    """Create a horizontal slider with value label. Returns (widget, slider, label)."""
    container = QWidget()
    hl = QHBoxLayout(container)
    hl.setContentsMargins(0, 0, 0, 0)

    slider = QSlider(Qt.Orientation.Horizontal)
    scale = 10 ** decimals
    slider.setRange(int(minimum * scale), int(maximum * scale))
    slider.setValue(int(value * scale))
    slider.setMinimumWidth(200)

    val_label = QLabel()
    val_label.setStyleSheet("color: #5294e2; font-weight: bold; min-width: 45px;")
    val_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def update_label(v):
        if decimals > 0:
            val_label.setText(f"{v / scale:.{decimals}f}{suffix}")
        else:
            val_label.setText(f"{v}{suffix}")

    slider.valueChanged.connect(update_label)
    update_label(slider.value())

    hl.addWidget(slider, 1)
    hl.addWidget(val_label)
    return container, slider, val_label


class ToggleSwitch(QWidget):
    """Apple-style animated toggle switch with label."""
    stateChanged = Signal(int)

    def __init__(self, label_text="", checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._label_text = label_text
        self._knob_x = 1.0  # animation position: 0.0 = off, 1.0 = on

        # Track dimensions
        self._track_w = 44
        self._track_h = 24
        self._knob_margin = 2
        self._knob_size = self._track_h - 2 * self._knob_margin
        self._label_gap = 10

        # Animation
        self._anim = QPropertyAnimation(self, b"knob_position")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        if checked:
            self._knob_x = 1.0
        else:
            self._knob_x = 0.0

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self._track_h + 4)

    def _get_knob_position(self):
        return self._knob_x

    def _set_knob_position(self, val):
        self._knob_x = val
        self.update()

    knob_position = Property(float, _get_knob_position, _set_knob_position)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked == checked:
            return
        self._checked = checked
        self._animate(checked)
        self.stateChanged.emit(1 if checked else 0)

    def _animate(self, to_on):
        self._anim.stop()
        self._anim.setStartValue(self._knob_x)
        self._anim.setEndValue(1.0 if to_on else 0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self._animate(self._checked)
            self.stateChanged.emit(1 if self._checked else 0)

    def sizeHint(self):
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self._label_text) if self._label_text else 0
        total_w = self._track_w + (self._label_gap + text_w if text_w else 0)
        return QSize(total_w + 4, max(self._track_h + 4, fm.height() + 4))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        y_offset = (self.height() - self._track_h) // 2

        # Track colors
        off_color = QColor(0x45, 0x47, 0x5a)
        on_color = QColor(0x52, 0x94, 0xe2)

        # Interpolate track color
        t = self._knob_x
        r = int(off_color.red() + t * (on_color.red() - off_color.red()))
        g = int(off_color.green() + t * (on_color.green() - off_color.green()))
        b = int(off_color.blue() + t * (on_color.blue() - off_color.blue()))
        track_color = QColor(r, g, b)

        # Draw track (pill shape)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(0, y_offset, self._track_w, self._track_h,
                          self._track_h / 2, self._track_h / 2)

        # Draw knob (white circle)
        knob_travel = self._track_w - self._knob_size - 2 * self._knob_margin
        knob_x = self._knob_margin + self._knob_x * knob_travel
        knob_y = y_offset + self._knob_margin

        # Subtle shadow
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawEllipse(int(knob_x), int(knob_y + 1), self._knob_size, self._knob_size)

        # White knob
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(int(knob_x), int(knob_y), self._knob_size, self._knob_size)

        # Draw label text
        if self._label_text:
            p.setPen(QColor(0xcd, 0xd6, 0xf4))
            text_x = self._track_w + self._label_gap
            text_y = (self.height() + self.fontMetrics().ascent() - self.fontMetrics().descent()) // 2
            p.drawText(text_x, text_y, self._label_text)

        p.end()


def make_toggle(label_text, checked=False):
    """Create an Apple-style toggle switch with label."""
    return ToggleSwitch(label_text, checked)

# ── Desktop Page ──────────────────────────────────────────────────────

class DesktopPage(QWidget):
    """Daemon profile editor page."""
    changed = Signal()

    def __init__(self, config_data):
        super().__init__()
        self._building = True
        self._config = config_data
        self._setup_ui()
        self._building = False

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 8, 0)

        profiles = self._config.get("profiles", {})
        profile_names = list(profiles.keys())

        # Profile selector
        card, cl = make_card("PROFILE")
        hl = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(profile_names)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        hl.addWidget(QLabel("Active Profile:"))
        hl.addWidget(self.profile_combo, 1)

        add_btn = QPushButton("+")
        add_btn.setFixedWidth(32)
        add_btn.setToolTip("Add profile")
        add_btn.clicked.connect(self._add_profile)
        hl.addWidget(add_btn)

        self.del_btn = QPushButton("-")
        self.del_btn.setFixedWidth(32)
        self.del_btn.setToolTip("Delete profile")
        self.del_btn.clicked.connect(self._del_profile)
        hl.addWidget(self.del_btn)

        cl.addLayout(hl)

        # WM class (hidden for default)
        self.wm_row = QWidget()
        wm_hl = QHBoxLayout(self.wm_row)
        wm_hl.setContentsMargins(0, 0, 0, 0)
        wm_hl.addWidget(QLabel("Window Match:"))
        self.wm_class_edit = QLineEdit()
        self.wm_class_edit.setPlaceholderText("e.g. firefox, chromium")
        self.wm_class_edit.textChanged.connect(self._emit_changed)
        wm_hl.addWidget(self.wm_class_edit, 1)
        cl.addWidget(self.wm_row)
        layout.addWidget(card)

        # Speed / Sensitivity
        card, cl = make_card("SPEED")
        fl = QFormLayout()
        fl.setSpacing(10)

        self.sensitivity_w, self.sensitivity_s, _ = make_slider(0.1, 10.0, 1.0, 1)
        self.sensitivity_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Sensitivity:", self.sensitivity_w)

        self.scroll_speed_w, self.scroll_speed_s, _ = make_slider(0, 20, 3.0, 1)
        self.scroll_speed_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Scroll Speed:", self.scroll_speed_w)

        self.zoom_speed_w, self.zoom_speed_s, _ = make_slider(0, 20, 2.0, 1)
        self.zoom_speed_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Zoom Speed:", self.zoom_speed_w)

        self.scroll_exp_w, self.scroll_exp_s, _ = make_slider(0.5, 5.0, 2.0, 1)
        self.scroll_exp_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Scroll Curve:", self.scroll_exp_w)

        self.deadzone_w, self.deadzone_s, _ = make_slider(0, 100, 15, 0)
        self.deadzone_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Deadzone:", self.deadzone_w)

        cl.addLayout(fl)
        layout.addWidget(card)

        # Axes
        card, cl = make_card("AXES")
        fl = QFormLayout()
        fl.setSpacing(8)
        self.axis_combos = []
        for i, name in enumerate(AXIS_NAMES):
            combo = QComboBox()
            combo.addItems(AXIS_ACTION_LABELS)
            combo.currentIndexChanged.connect(self._emit_changed)
            fl.addRow(f"{name}:", combo)
            self.axis_combos.append(combo)

        self.invert_x = make_toggle("Invert Horizontal Scroll")
        self.invert_x.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.invert_x)

        self.invert_y = make_toggle("Invert Vertical Scroll")
        self.invert_y.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.invert_y)

        cl.addLayout(fl)
        layout.addWidget(card)

        # Buttons
        card, cl = make_card("BUTTONS")
        fl = QFormLayout()
        fl.setSpacing(8)
        self.btn_combos = []
        for i in range(2):
            combo = QComboBox()
            combo.addItems(BTN_ACTION_LABELS)
            combo.currentIndexChanged.connect(self._emit_changed)
            fl.addRow(f"Button {i + 1}:", combo)
            self.btn_combos.append(combo)
        cl.addLayout(fl)
        layout.addWidget(card)

        # Desktop switching
        card, cl = make_card("DESKTOP SWITCHING")
        fl = QFormLayout()
        fl.setSpacing(8)
        self.dswitch_thresh_w, self.dswitch_thresh_s, _ = make_slider(0, 500, 200, 0)
        self.dswitch_thresh_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Threshold:", self.dswitch_thresh_w)

        self.dswitch_cool_w, self.dswitch_cool_s, _ = make_slider(100, 2000, 500, 0, " ms")
        self.dswitch_cool_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Cooldown:", self.dswitch_cool_w)

        cl.addLayout(fl)
        layout.addWidget(card)

        layout.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Load first profile
        if profile_names:
            self._load_profile(profile_names[0])

    def _emit_changed(self):
        if not self._building:
            self.changed.emit()

    def _on_profile_changed(self, name):
        if not name:
            return
        profiles = self._config.get("profiles", {})
        if name in profiles:
            self._building = True
            self._load_profile(name)
            self._building = False

    def _load_profile(self, name):
        profiles = self._config.get("profiles", {})
        data = profiles.get(name, {})
        is_default = (name == "default")

        self.wm_row.setVisible(not is_default)
        self.del_btn.setEnabled(not is_default)

        if not is_default:
            self.wm_class_edit.setText(", ".join(data.get("match_wm_class", [])))

        self.sensitivity_s.setValue(int(data.get("sensitivity", 1.0) * 10))
        self.scroll_speed_s.setValue(int(data.get("scroll_speed", 3.0) * 10))
        self.zoom_speed_s.setValue(int(data.get("zoom_speed", 2.0) * 10))
        self.scroll_exp_s.setValue(int(data.get("scroll_exponent", 2.0) * 10))
        self.deadzone_s.setValue(data.get("deadzone", 15))

        amap = data.get("axis_mapping", {})
        for i, key in enumerate(AXIS_KEYS):
            action = amap.get(key, "none")
            idx = AXIS_ACTIONS.index(action) if action in AXIS_ACTIONS else 0
            self.axis_combos[i].setCurrentIndex(idx)

        self.invert_x.setChecked(data.get("invert_scroll_x", False))
        self.invert_y.setChecked(data.get("invert_scroll_y", False))

        bmap = data.get("button_mapping", {})
        for i in range(2):
            action = bmap.get(str(i), "none")
            idx = BTN_ACTIONS.index(action) if action in BTN_ACTIONS else 0
            self.btn_combos[i].setCurrentIndex(idx)

        self.dswitch_thresh_s.setValue(data.get("desktop_switch_threshold", 200))
        self.dswitch_cool_s.setValue(data.get("desktop_switch_cooldown_ms", 500))

    def _add_profile(self):
        name, ok = QInputDialog.getText(
            self, "New Profile", "Profile name (e.g. firefox, krita):")
        if not ok or not name.strip():
            return
        name = name.strip().lower().replace(" ", "_")
        profiles = self._config.get("profiles", {})
        if name in profiles:
            QMessageBox.warning(self, "Error", f"Profile '{name}' already exists.")
            return
        default_data = dict(profiles.get("default", {}))
        default_data["match_wm_class"] = [name]
        profiles[name] = default_data
        self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)

    def _del_profile(self):
        name = self.profile_combo.currentText()
        if name == "default":
            return
        reply = QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{name}'?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        profiles = self._config.get("profiles", {})
        profiles.pop(name, None)
        idx = self.profile_combo.findText(name)
        if idx >= 0:
            self.profile_combo.removeItem(idx)

    def get_current_profile_data(self):
        """Return current profile data as dict."""
        data = {}
        name = self.profile_combo.currentText()
        if name != "default":
            wm_text = self.wm_class_edit.text().strip()
            if wm_text:
                data["match_wm_class"] = [s.strip() for s in wm_text.split(",") if s.strip()]

        data["sensitivity"] = self.sensitivity_s.value() / 10.0
        data["scroll_speed"] = self.scroll_speed_s.value() / 10.0
        data["zoom_speed"] = self.zoom_speed_s.value() / 10.0
        data["scroll_exponent"] = self.scroll_exp_s.value() / 10.0
        data["deadzone"] = self.deadzone_s.value()

        data["axis_mapping"] = {}
        for i, key in enumerate(AXIS_KEYS):
            data["axis_mapping"][key] = AXIS_ACTIONS[self.axis_combos[i].currentIndex()]

        data["button_mapping"] = {}
        for i in range(2):
            data["button_mapping"][str(i)] = BTN_ACTIONS[self.btn_combos[i].currentIndex()]

        data["invert_scroll_x"] = self.invert_x.isChecked()
        data["invert_scroll_y"] = self.invert_y.isChecked()
        data["desktop_switch_threshold"] = self.dswitch_thresh_s.value()
        data["desktop_switch_cooldown_ms"] = self.dswitch_cool_s.value()
        return data

    def save_current_profile(self):
        """Save current UI state back into config dict."""
        name = self.profile_combo.currentText()
        if not name:
            return
        profiles = self._config.setdefault("profiles", {})
        profiles[name] = self.get_current_profile_data()

    def get_all_config(self):
        """Return full daemon config dict with all profiles."""
        self.save_current_profile()
        return self._config

    def update_config(self, config):
        """Replace config data and refresh UI."""
        self._config = config
        self._building = True
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        profiles = config.get("profiles", {})
        self.profile_combo.addItems(list(profiles.keys()))
        if current in profiles:
            self.profile_combo.setCurrentText(current)
        elif profiles:
            self.profile_combo.setCurrentIndex(0)
        self._building = False

# ── FreeCAD Page ──────────────────────────────────────────────────────

class FreeCADPage(QWidget):
    """FreeCAD SpaceMouse settings editor."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._building = True
        self._fc = FreeCADConfig()
        self._setup_ui()
        self._load_settings()
        self._building = False

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 8, 0)

        # Warning if FreeCAD not found
        if not self._fc.is_available():
            warn = QLabel("FreeCAD user.cfg not found. Start FreeCAD once to generate it.")
            warn.setStyleSheet(
                "color: #f9e2af; background-color: #3a3636; "
                "border-radius: 6px; padding: 8px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # Running warning
        self.running_warn = QLabel(
            "FreeCAD is running — it overwrites user.cfg on exit.\n"
            "Close FreeCAD before applying changes.")
        self.running_warn.setStyleSheet(
            "color: #f38ba8; background-color: #3a2a2a; "
            "border-radius: 6px; padding: 8px;")
        self.running_warn.setWordWrap(True)
        self.running_warn.setVisible(False)
        layout.addWidget(self.running_warn)

        # Sensitivity
        card, cl = make_card("SENSITIVITY")
        fl = QFormLayout()
        fl.setSpacing(10)
        self.sensitivity_w, self.sensitivity_s, _ = make_slider(-50, 50, -15, 0)
        self.sensitivity_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Global Sensitivity:", self.sensitivity_w)
        cl.addLayout(fl)
        layout.addWidget(card)

        # Axes enable/disable
        card, cl = make_card("AXES")
        fl = QFormLayout()
        fl.setSpacing(8)

        axis_names = ["PanLR (Left/Right)", "PanUD (Up/Down)", "Zoom",
                      "Tilt (Pitch)", "Roll", "Spin (Yaw)"]
        self._fc_axis_keys = ["panlr", "panud", "zoom", "tilt", "roll", "spin"]

        self.fc_enable_toggles = []
        self.fc_reverse_toggles = []
        for i, name in enumerate(axis_names):
            row = QHBoxLayout()
            en = make_toggle("Enable")
            en.stateChanged.connect(self._emit_changed)
            rev = make_toggle("Invert")
            rev.stateChanged.connect(self._emit_changed)
            row.addWidget(QLabel(name))
            row.addStretch()
            row.addWidget(en)
            row.addWidget(rev)
            fl.addRow(row)
            self.fc_enable_toggles.append(en)
            self.fc_reverse_toggles.append(rev)

        self.fc_flip_yz = make_toggle("Flip Y/Z")
        self.fc_flip_yz.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.fc_flip_yz)

        self.fc_dominant = make_toggle("Dominant Mode (single axis at a time)")
        self.fc_dominant.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.fc_dominant)

        cl.addLayout(fl)
        layout.addWidget(card)

        # Buttons
        card, cl = make_card("BUTTONS")
        fl = QFormLayout()
        fl.setSpacing(8)
        self.fc_btn_combos = []
        for i in range(2):
            combo = QComboBox()
            combo.addItems(FREECAD_BTN_LABELS)
            combo.currentIndexChanged.connect(self._emit_changed)
            fl.addRow(f"Button {i + 1}:", combo)
            self.fc_btn_combos.append(combo)
        cl.addLayout(fl)
        layout.addWidget(card)

        # Navigation
        card, cl = make_card("NAVIGATION")
        fl = QFormLayout()
        fl.setSpacing(8)

        self.fc_nav_combo = QComboBox()
        self.fc_nav_combo.addItems(FREECAD_NAV_LABELS)
        self.fc_nav_combo.currentIndexChanged.connect(self._emit_changed)
        fl.addRow("Navigation Style:", self.fc_nav_combo)

        self.fc_orbit_combo = QComboBox()
        self.fc_orbit_combo.addItems(list(FREECAD_ORBIT_STYLES.keys()))
        self.fc_orbit_combo.currentIndexChanged.connect(self._emit_changed)
        fl.addRow("Orbit Style:", self.fc_orbit_combo)

        cl.addLayout(fl)
        layout.addWidget(card)

        layout.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Timer to check if FreeCAD is running
        self._running_timer = QTimer()
        self._running_timer.timeout.connect(self._check_running)
        self._running_timer.start(5000)

    def _emit_changed(self):
        if not self._building:
            self.changed.emit()

    def _check_running(self):
        self.running_warn.setVisible(self._fc.is_running())

    def _load_settings(self):
        settings = self._fc.read()
        self.sensitivity_s.setValue(settings["global_sensitivity"])
        self.fc_flip_yz.setChecked(settings["flip_yz"])
        self.fc_dominant.setChecked(settings["dominant"])

        for i, key in enumerate(self._fc_axis_keys):
            self.fc_enable_toggles[i].setChecked(settings.get(f"{key}_enable", True))
            self.fc_reverse_toggles[i].setChecked(settings.get(f"{key}_reverse", False))

        # Buttons
        for i, combo in enumerate(self.fc_btn_combos):
            cmd = settings.get(f"btn{i}_command", "")
            idx = FREECAD_BTN_COMMANDS.index(cmd) if cmd in FREECAD_BTN_COMMANDS else 0
            combo.setCurrentIndex(idx)

        # Navigation
        nav = settings.get("nav_style", "")
        idx = FREECAD_NAV_STYLES.index(nav) if nav in FREECAD_NAV_STYLES else 1
        self.fc_nav_combo.setCurrentIndex(idx)

        orbit = settings.get("orbit_style", 1)
        orbit_values = list(FREECAD_ORBIT_STYLES.values())
        idx = orbit_values.index(orbit) if orbit in orbit_values else 0
        self.fc_orbit_combo.setCurrentIndex(idx)

    def get_settings(self):
        """Return dict of FreeCAD settings."""
        s = {
            "global_sensitivity": self.sensitivity_s.value(),
            "flip_yz": self.fc_flip_yz.isChecked(),
            "dominant": self.fc_dominant.isChecked(),
        }
        for i, key in enumerate(self._fc_axis_keys):
            s[f"{key}_enable"] = self.fc_enable_toggles[i].isChecked()
            s[f"{key}_reverse"] = self.fc_reverse_toggles[i].isChecked()

        for i in range(2):
            idx = self.fc_btn_combos[i].currentIndex()
            s[f"btn{i}_command"] = FREECAD_BTN_COMMANDS[idx]

        s["nav_style"] = FREECAD_NAV_STYLES[self.fc_nav_combo.currentIndex()]
        orbit_values = list(FREECAD_ORBIT_STYLES.values())
        s["orbit_style"] = orbit_values[self.fc_orbit_combo.currentIndex()]
        return s

    def apply_settings(self):
        """Write settings to FreeCAD user.cfg."""
        if not self._fc.is_available():
            return False
        return self._fc.write(self.get_settings())

# ── Blender Page ──────────────────────────────────────────────────────

class BlenderPage(QWidget):
    """Blender NDOF settings editor."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._building = True
        self._bc = BlenderConfig()
        self._setup_ui()
        self._load_settings()
        self._building = False

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 8, 0)

        # Startup script status
        card, cl = make_card("SYNC SCRIPT")
        self.script_status = QLabel()
        self.script_status.setWordWrap(True)
        cl.addWidget(self.script_status)

        self.install_btn = QPushButton("Install Startup Script")
        self.install_btn.clicked.connect(self._install_script)
        cl.addWidget(self.install_btn)
        self._update_script_status()
        layout.addWidget(card)

        # Sensitivity
        card, cl = make_card("SENSITIVITY")
        fl = QFormLayout()
        fl.setSpacing(10)

        self.bl_sensitivity_w, self.bl_sensitivity_s, _ = make_slider(0.0, 4.0, 1.0, 2)
        self.bl_sensitivity_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Sensitivity:", self.bl_sensitivity_w)

        self.bl_orbit_w, self.bl_orbit_s, _ = make_slider(0.0, 4.0, 1.0, 2)
        self.bl_orbit_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Orbit Sensitivity:", self.bl_orbit_w)

        self.bl_deadzone_w, self.bl_deadzone_s, _ = make_slider(0.0, 1.0, 0.1, 2)
        self.bl_deadzone_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Deadzone:", self.bl_deadzone_w)

        cl.addLayout(fl)
        layout.addWidget(card)

        # Behavior
        card, cl = make_card("BEHAVIOR")
        fl = QFormLayout()
        fl.setSpacing(8)

        self.bl_lock_horizon = make_toggle("Lock Horizon")
        self.bl_lock_horizon.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.bl_lock_horizon)

        lock_warn = QLabel("Lock Horizon blocks RX/pitch axis — keep OFF for full 6DOF")
        lock_warn.setStyleSheet(
            "color: #f9e2af; font-size: 11px; background: transparent;")
        lock_warn.setWordWrap(True)
        fl.addRow("", lock_warn)

        self.bl_swap_yz = make_toggle("Swap Y/Z Panning")
        self.bl_swap_yz.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.bl_swap_yz)

        self.bl_zoom_invert = make_toggle("Invert Zoom")
        self.bl_zoom_invert.stateChanged.connect(self._emit_changed)
        fl.addRow("", self.bl_zoom_invert)

        cl.addLayout(fl)
        layout.addWidget(card)

        # Invert axes
        card, cl = make_card("INVERT AXES")
        fl = QFormLayout()
        fl.setSpacing(8)

        self.bl_rot_inverts = []
        for axis in ["X", "Y", "Z"]:
            cb = make_toggle(f"Rotation {axis}")
            cb.stateChanged.connect(self._emit_changed)
            fl.addRow("", cb)
            self.bl_rot_inverts.append(cb)

        self.bl_pan_inverts = []
        for axis in ["X", "Y", "Z"]:
            cb = make_toggle(f"Pan {axis}")
            cb.stateChanged.connect(self._emit_changed)
            fl.addRow("", cb)
            self.bl_pan_inverts.append(cb)

        cl.addLayout(fl)
        layout.addWidget(card)

        layout.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _emit_changed(self):
        if not self._building:
            self.changed.emit()

    def _update_script_status(self):
        if self._bc.is_script_installed():
            self.script_status.setText("Startup script is installed.")
            self.script_status.setStyleSheet("color: #a6e3a1; background: transparent;")
            self.install_btn.setText("Reinstall Startup Script")
        else:
            self.script_status.setText(
                "Startup script not installed. Blender won't pick up settings "
                "until you install it.")
            self.script_status.setStyleSheet("color: #f9e2af; background: transparent;")
            self.install_btn.setText("Install Startup Script")

    def _install_script(self):
        if self._bc.install_startup_script():
            self._update_script_status()
            QMessageBox.information(self, "Installed",
                                   f"Script installed to:\n{BLENDER_STARTUP_DIR / BLENDER_SYNC_SCRIPT}")
        else:
            QMessageBox.warning(self, "Error",
                                "Could not find blender_spacemouse_sync.py next to this script.")

    def _load_settings(self):
        s = self._bc.read()
        self.bl_sensitivity_s.setValue(int(s["ndof_sensitivity"] * 100))
        self.bl_orbit_s.setValue(int(s["ndof_orbit_sensitivity"] * 100))
        self.bl_deadzone_s.setValue(int(s["ndof_deadzone"] * 100))
        self.bl_lock_horizon.setChecked(s["ndof_lock_horizon"])
        self.bl_swap_yz.setChecked(s["ndof_pan_yz_swap_axis"])
        self.bl_zoom_invert.setChecked(s["ndof_zoom_invert"])

        rot_keys = ["ndof_rotx_invert_axis", "ndof_roty_invert_axis", "ndof_rotz_invert_axis"]
        for i, key in enumerate(rot_keys):
            self.bl_rot_inverts[i].setChecked(s.get(key, False))

        pan_keys = ["ndof_panx_invert_axis", "ndof_pany_invert_axis", "ndof_panz_invert_axis"]
        for i, key in enumerate(pan_keys):
            self.bl_pan_inverts[i].setChecked(s.get(key, False))

    def get_settings(self):
        """Return dict of Blender NDOF settings."""
        s = {
            "ndof_sensitivity": self.bl_sensitivity_s.value() / 100.0,
            "ndof_orbit_sensitivity": self.bl_orbit_s.value() / 100.0,
            "ndof_deadzone": self.bl_deadzone_s.value() / 100.0,
            "ndof_lock_horizon": self.bl_lock_horizon.isChecked(),
            "ndof_pan_yz_swap_axis": self.bl_swap_yz.isChecked(),
            "ndof_zoom_invert": self.bl_zoom_invert.isChecked(),
        }
        for i, axis in enumerate(["x", "y", "z"]):
            s[f"ndof_rot{axis}_invert_axis"] = self.bl_rot_inverts[i].isChecked()
            s[f"ndof_pan{axis}_invert_axis"] = self.bl_pan_inverts[i].isChecked()
        return s

    def apply_settings(self):
        """Write settings to blender-ndof.json."""
        self._bc.write(self.get_settings())

# ── Live Preview Bar ──────────────────────────────────────────────────

class LivePreviewBar(QWidget):
    """Compact horizontal live preview bar for the bottom of the window."""

    def __init__(self):
        super().__init__()
        self.setObjectName("live-bar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(6)

        lbl = QLabel("Live:")
        lbl.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl)

        self.bars = []
        short_names = ["TX", "TY", "TZ", "RX", "RY", "RZ"]
        for name in short_names:
            nl = QLabel(name)
            nl.setStyleSheet("color: #6c7086; font-size: 10px; min-width: 18px;")
            layout.addWidget(nl)
            bar = QProgressBar()
            bar.setRange(-350, 350)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setMinimumWidth(40)
            layout.addWidget(bar, 1)
            self.bars.append(bar)

        layout.addSpacing(8)

        lbl = QLabel("Buttons:")
        lbl.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl)

        self.btn_labels = []
        for i in range(2):
            bl = QLabel("\u25cb")  # circle
            bl.setStyleSheet("font-size: 14px; color: #45475a;")
            layout.addWidget(bl)
            self.btn_labels.append(bl)

        layout.addSpacing(12)

        self.profile_label = QLabel("Profile: default")
        self.profile_label.setStyleSheet("color: #5294e2; font-weight: bold; font-size: 11px;")
        layout.addWidget(self.profile_label)

        # Status dot
        self.status_dot = QLabel("\u25cf")
        self.status_dot.setStyleSheet("font-size: 12px; color: #45475a;")
        self.status_dot.setToolTip("Daemon: checking...")
        layout.addWidget(self.status_dot)

    def update_axes(self, values):
        for i, val in enumerate(values):
            if i < len(self.bars):
                self.bars[i].setValue(val)

    def update_button(self, bnum, pressed):
        if 0 <= bnum < len(self.btn_labels):
            if pressed:
                self.btn_labels[bnum].setText("\u25cf")
                self.btn_labels[bnum].setStyleSheet("font-size: 14px; color: #a6e3a1;")
            else:
                self.btn_labels[bnum].setText("\u25cb")
                self.btn_labels[bnum].setStyleSheet("font-size: 14px; color: #45475a;")

    def set_profile(self, name):
        self.profile_label.setText(f"Profile: {name}")

    def set_daemon_status(self, connected):
        if connected:
            self.status_dot.setStyleSheet("font-size: 12px; color: #a6e3a1;")
            self.status_dot.setToolTip("Daemon: connected")
        else:
            self.status_dot.setStyleSheet("font-size: 12px; color: #f38ba8;")
            self.status_dot.setToolTip("Daemon: not connected")

# ── Settings Window ───────────────────────────────────────────────────

class SettingsWindow(QMainWindow):
    """Main settings window with sidebar navigation."""

    def __init__(self, config_data, on_save_callback):
        super().__init__()
        self.on_save = on_save_callback
        self.setWindowTitle("SpaceMouse Control")
        self.setMinimumSize(820, 600)
        self.resize(920, 680)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top area: sidebar + content
        top = QHBoxLayout()
        top.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(140)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 12, 8, 12)
        sb_layout.setSpacing(4)

        title = QLabel("SpaceMouse")
        title.setStyleSheet("color: #5294e2; font-size: 15px; font-weight: bold; padding: 4px;")
        sb_layout.addWidget(title)
        subtitle = QLabel("Control")
        subtitle.setStyleSheet("color: #6c7086; font-size: 12px; padding: 0 4px 12px 4px;")
        sb_layout.addWidget(subtitle)

        self._page_buttons = []
        pages = [("Desktop", 0), ("FreeCAD", 1), ("Blender", 2)]
        for label, idx in pages:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sb_layout.addWidget(btn)
            self._page_buttons.append(btn)

        sb_layout.addStretch()

        # General settings at bottom of sidebar
        self.autostart_cb = make_toggle("Autostart")
        sb_layout.addWidget(self.autostart_cb)

        top.addWidget(sidebar)

        # Content stack
        self.stack = QStackedWidget()

        self.desktop_page = DesktopPage(config_data)
        self.desktop_page.changed.connect(self._mark_dirty)
        self.stack.addWidget(self.desktop_page)

        self.freecad_page = FreeCADPage()
        self.freecad_page.changed.connect(self._mark_dirty)
        self.stack.addWidget(self.freecad_page)

        self.blender_page = BlenderPage()
        self.blender_page.changed.connect(self._mark_dirty)
        self.stack.addWidget(self.blender_page)

        # Content wrapper with padding
        content_wrapper = QWidget()
        cw_layout = QVBoxLayout(content_wrapper)
        cw_layout.setContentsMargins(16, 12, 16, 8)
        cw_layout.setSpacing(8)
        cw_layout.addWidget(self.stack, 1)

        # Apply button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("apply-btn")
        self.apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(self.apply_btn)
        cw_layout.addLayout(btn_row)

        top.addWidget(content_wrapper, 1)
        main_layout.addLayout(top, 1)

        # Live preview bar
        self.live_bar = LivePreviewBar()
        main_layout.addWidget(self.live_bar)

        # Select first page
        self._page_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)

        # Status timer
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(3000)
        self._update_status()

        self._dirty = False

    def _switch_page(self, idx):
        # Save current desktop page state before switching away
        if self.stack.currentIndex() == 0:
            self.desktop_page.save_current_profile()
        self.stack.setCurrentIndex(idx)

    def _mark_dirty(self):
        self._dirty = True
        self.setWindowTitle("SpaceMouse Control *")

    def _apply(self):
        page_idx = self.stack.currentIndex()

        if page_idx == 0:
            # Desktop: save daemon config
            config = self.desktop_page.get_all_config()
            config["settings"] = {"autostart": self.autostart_cb.isChecked()}
            self.on_save(config)

        elif page_idx == 1:
            # FreeCAD
            if FreeCADConfig.is_running():
                QMessageBox.warning(self, "FreeCAD Running",
                    "FreeCAD is running and will overwrite user.cfg on exit.\n"
                    "Please close FreeCAD first.")
                return
            if self.freecad_page.apply_settings():
                QMessageBox.information(self, "Applied",
                    "FreeCAD settings saved to user.cfg.\n"
                    "Restart FreeCAD for changes to take effect.")
            else:
                QMessageBox.warning(self, "Error",
                    "Could not write FreeCAD user.cfg.")

        elif page_idx == 2:
            # Blender
            self.blender_page.apply_settings()
            QMessageBox.information(self, "Applied",
                "Blender NDOF settings saved.\n"
                "Restart Blender to apply.")

        self._dirty = False
        self.setWindowTitle("SpaceMouse Control")

    def _update_status(self):
        resp = send_daemon_cmd("STATUS")
        self.live_bar.set_daemon_status(resp is not None)

    def set_spnav_reader(self, reader):
        reader.axes_updated.connect(self.live_bar.update_axes)
        reader.button_pressed.connect(self.live_bar.update_button)

    def set_profile_name(self, name):
        self.live_bar.set_profile(name)

    def update_config(self, config):
        self.desktop_page.update_config(config)

    def sync_settings(self, settings_state):
        self.autostart_cb.setChecked(settings_state.get("autostart", True))

# ── Tray Icon ─────────────────────────────────────────────────────────

def create_tray_icon_pixmap(text="SM"):
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(82, 148, 226))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 12, 12)
    painter.setPen(QColor(255, 255, 255))
    font = QFont("Sans", 18, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap

# ── Main Application ──────────────────────────────────────────────────

class SpaceMouseApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("SpaceMouse Control")
        self.app.setStyleSheet(DARK_THEME)

        self.config = self._load_config()
        self._cleaned_up = False

        settings = self.config.get("settings", {})
        self._autostart = settings.get("autostart", True)

        self.settings_window = SettingsWindow(self.config, self._on_save)
        self.settings_window.sync_settings({"autostart": self._autostart})

        # System tray
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon(create_tray_icon_pixmap("SM")))
        self.tray.setToolTip("SpaceMouse: default")
        self.tray.activated.connect(self._on_tray_activated)

        self._paused = False
        self.window_monitor = None

        menu = QMenu()
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)
        self.tray.show()

        # SpaceMouse reader
        self.spnav_reader = SpnavReader()
        self.settings_window.set_spnav_reader(self.spnav_reader)
        self.spnav_reader.start()

        # Window monitor
        self._start_window_monitor()

        signal.signal(signal.SIGTERM, self._sigterm_handler)
        signal.signal(signal.SIGINT, self._sigterm_handler)
        atexit.register(self._cleanup)

    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"profiles": {"default": {
            "deadzone": 15, "scroll_speed": 3.0, "scroll_exponent": 2.0,
            "zoom_speed": 2.0, "sensitivity": 1.0,
            "desktop_switch_threshold": 200, "desktop_switch_cooldown_ms": 500,
            "axis_mapping": {"tx": "scroll_h", "ty": "scroll_v", "tz": "zoom",
                             "rx": "none", "ry": "desktop_switch", "rz": "none"},
            "button_mapping": {"0": "overview", "1": "show_desktop"},
            "invert_scroll_x": False, "invert_scroll_y": False
        }}}

    def _cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.spnav_reader.stop()
        self._stop_window_monitor()

    def _sigterm_handler(self, signum, frame):
        self._cleanup()
        self.tray.hide()
        self.app.quit()

    def _on_save(self, config):
        self.config = config
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)

        send_daemon_cmd("RELOAD")

        settings = config.get("settings", {})
        new_autostart = settings.get("autostart", self._autostart)
        if new_autostart != self._autostart:
            self._autostart = new_autostart
            action = "enable" if new_autostart else "disable"
            subprocess.run(
                ["systemctl", "--user", action, "spacemouse-config.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(
                ["systemctl", "--user", action, "spacemouse-desktop.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)

        if self.window_monitor:
            profiles = config.get("profiles", {})
            self.window_monitor.update_profiles(profiles)

        menu = QMenu()
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)

    def _rebuild_tray_menu(self, menu):
        profiles = self.config.get("profiles", {})
        for name in profiles:
            action = QAction(f"Profile: {name}", menu)
            action.setData(name)
            action.triggered.connect(lambda _c=False, n=name: self._switch_profile(n))
            menu.addAction(action)

        menu.addSeparator()

        pause_action = QAction(
            "Resume Daemon" if self._paused else "Pause Daemon", menu)
        pause_action.triggered.connect(self._toggle_pause)
        menu.addAction(pause_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit (stop all)", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

    def _start_window_monitor(self):
        profiles = self.config.get("profiles", {"default": self.config})
        self.window_monitor = WindowMonitor(profiles)
        self.window_monitor.window_changed.connect(self._on_window_changed)
        self.window_monitor.start()

    def _stop_window_monitor(self):
        if self.window_monitor:
            self.window_monitor.stop()
            self.window_monitor = None

    def _switch_profile(self, name):
        send_daemon_cmd(f"PROFILE {name}")
        self.tray.setToolTip(f"SpaceMouse: {name}")
        self.settings_window.set_profile_name(name)

    def _toggle_pause(self):
        if self._paused:
            self._paused = False
            subprocess.Popen(
                ["systemctl", "--user", "start", "spacemouse-desktop.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._start_window_monitor()
            self.tray.setToolTip("SpaceMouse: default")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("SM")))
        else:
            self._paused = True
            self._stop_window_monitor()
            subprocess.Popen(
                ["systemctl", "--user", "stop", "spacemouse-desktop.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.tray.setToolTip("SpaceMouse: PAUSED")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("||")))
        menu = QMenu()
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_settings()

    def _show_settings(self):
        self.settings_window.sync_settings({"autostart": self._autostart})
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _on_window_changed(self, wm_class, profile_name):
        self.tray.setToolTip(f"SpaceMouse: {profile_name} ({wm_class})")
        self.settings_window.set_profile_name(profile_name)

    def _quit(self):
        self._cleanup()
        subprocess.run(
            ["systemctl", "--user", "stop", "spacemouse-desktop.service"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        self.tray.hide()
        self.app.quit()

    def run(self):
        return self.app.exec()


if __name__ == "__main__":
    app = SpaceMouseApp()
    sys.exit(app.run())
