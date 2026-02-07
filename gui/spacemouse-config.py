#!/usr/bin/env python3
"""
SpaceMouse Configuration GUI

PySide6 application with:
- System tray icon showing active profile
- Settings window with per-application profile editor
- Live SpaceMouse axis preview
- Automatic active window detection via KWin D-Bus
- UNIX socket communication with spacemouse-desktop daemon
"""

import sys
import os
import json
import socket
import subprocess
import signal
import atexit
import ctypes
import ctypes.util
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QGroupBox,
    QLabel, QComboBox, QSlider, QSpinBox, QDoubleSpinBox,
    QCheckBox, QPushButton, QLineEdit, QProgressBar,
    QFormLayout, QSplitter, QMessageBox, QMenu, QInputDialog,
    QSystemTrayIcon, QStyle
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont

# ── Constants ──────────────────────────────────────────────────────────

CONFIG_PATH = Path.home() / ".config" / "spacemouse" / "config.json"
SOCK_PATH = f"/run/user/{os.getuid()}/spacemouse-cmd.sock"

AXIS_ACTIONS = ["none", "scroll_h", "scroll_v", "zoom", "desktop_switch"]
AXIS_ACTION_LABELS = ["None", "Horizontal Scroll", "Vertical Scroll", "Zoom", "Desktop Switch"]

BTN_ACTIONS = ["none", "overview", "show_desktop"]
BTN_ACTION_LABELS = ["None", "Overview (Expose)", "Show Desktop"]

AXIS_NAMES = ["TX (Left/Right)", "TY (Push/Pull)", "TZ (Up/Down)",
              "RX (Pitch)", "RY (Yaw/Twist)", "RZ (Roll)"]

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
    axes_updated = Signal(list)  # [tx, ty, tz, rx, ry, rz]
    button_pressed = Signal(int, bool)  # bnum, press

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
                self.msleep(16)  # ~60fps
                continue
            if ev.type == 1:  # SPNAV_EVENT_MOTION
                self.axes_updated.emit([
                    ev.motion.x, ev.motion.y, ev.motion.z,
                    ev.motion.rx, ev.motion.ry, ev.motion.rz
                ])
            elif ev.type == 2:  # SPNAV_EVENT_BUTTON
                self.button_pressed.emit(ev.button.bnum, bool(ev.button.press))

        self._lib.spnav_close()

    def stop(self):
        self._running = False
        self.wait(2000)

# ── Window Monitor Thread ─────────────────────────────────────────────

class WindowMonitor(QThread):
    """Monitors active window via KWin scripting and switches daemon profile.

    Uses a persistent KWin JavaScript that hooks workspace.windowActivated
    and prints the resourceClass to the journal.  This thread follows the
    journal stream (journalctl -f) for event-driven, zero-polling detection.
    """
    window_changed = Signal(str, str)  # wm_class, profile_name

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
        """Write JS file and load it into KWin via D-Bus."""
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
        """Find profile matching the given WM class."""
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

# ── Profile Editor Widget ─────────────────────────────────────────────

class ProfileEditor(QWidget):
    """Editor for a single profile's settings."""
    changed = Signal()

    def __init__(self, name, data, is_default=False, default_data=None):
        super().__init__()
        self.profile_name = name
        self.is_default = is_default
        self._default_data = default_data or {}
        self._building = True
        self._setup_ui(data)
        self._building = False

    def _default_suffix(self, key, fmt=None):
        """Return a suffix string showing the default profile's value for this key."""
        if self.is_default or key not in self._default_data:
            return ""
        val = self._default_data[key]
        if fmt:
            return f"  (default: {fmt.format(val)})"
        return f"  (default: {val})"

    def _make_combo(self, actions, labels, current, default_action=None):
        """Create a combobox with consistent width. Shows actual config value."""
        combo = QComboBox()
        combo.setMinimumWidth(220)
        for i, label in enumerate(labels):
            suffix = ""
            if not self.is_default and default_action and actions[i] == default_action:
                suffix = " (default)"
            combo.addItem(label + suffix)
        if current in actions:
            combo.setCurrentIndex(actions.index(current))
        if not self.is_default and default_action and default_action in actions:
            default_label = labels[actions.index(default_action)]
            combo.setToolTip(f"Default: {default_label}")
        combo.currentIndexChanged.connect(self._on_changed)
        return combo

    def _setup_ui(self, data):
        layout = QVBoxLayout(self)

        # WM Class matching (not for default)
        if not self.is_default:
            grp = QGroupBox("Window Matching")
            fl = QFormLayout(grp)
            self.wm_class_edit = QLineEdit()
            self.wm_class_edit.setPlaceholderText("e.g. blender, Blender")
            wm_classes = data.get("match_wm_class", [])
            self.wm_class_edit.setText(", ".join(wm_classes))
            self.wm_class_edit.textChanged.connect(self._on_changed)
            fl.addRow("WM Class (comma-separated):", self.wm_class_edit)
            layout.addWidget(grp)

        # Axis mapping
        grp = QGroupBox("Axis Mapping")
        fl = QFormLayout(grp)
        amap = data.get("axis_mapping", {})
        default_amap = self._default_data.get("axis_mapping", {})
        axis_keys = ["tx", "ty", "tz", "rx", "ry", "rz"]
        self.axis_combos = []
        for i, key in enumerate(axis_keys):
            current = amap.get(key, "none")
            default_action = default_amap.get(key, "none")
            combo = self._make_combo(AXIS_ACTIONS, AXIS_ACTION_LABELS, current, default_action)
            fl.addRow(f"{AXIS_NAMES[i]}:", combo)
            self.axis_combos.append(combo)
        layout.addWidget(grp)

        # Button mapping
        grp = QGroupBox("Button Mapping")
        fl = QFormLayout(grp)
        bmap = data.get("button_mapping", {})
        default_bmap = self._default_data.get("button_mapping", {})
        self.btn_combos = []
        for i in range(2):
            current = bmap.get(str(i), "none")
            default_action = default_bmap.get(str(i), "none")
            combo = self._make_combo(BTN_ACTIONS, BTN_ACTION_LABELS, current, default_action)
            fl.addRow(f"Button {i + 1}:", combo)
            self.btn_combos.append(combo)
        layout.addWidget(grp)

        # Sensitivity
        grp = QGroupBox("Sensitivity")
        fl = QFormLayout(grp)

        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setRange(0.1, 10.0)
        self.sensitivity_spin.setSingleStep(0.1)
        self.sensitivity_spin.setValue(data.get("sensitivity", 1.0))
        self.sensitivity_spin.setSuffix(self._default_suffix("sensitivity", "{:.1f}"))
        self.sensitivity_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Sensitivity:", self.sensitivity_spin)

        self.deadzone_spin = QSpinBox()
        self.deadzone_spin.setRange(0, 100)
        self.deadzone_spin.setValue(data.get("deadzone", 15))
        self.deadzone_spin.setSuffix(self._default_suffix("deadzone"))
        self.deadzone_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Deadzone:", self.deadzone_spin)

        self.scroll_speed_spin = QDoubleSpinBox()
        self.scroll_speed_spin.setRange(0, 20)
        self.scroll_speed_spin.setSingleStep(0.5)
        self.scroll_speed_spin.setValue(data.get("scroll_speed", 3.0))
        self.scroll_speed_spin.setSuffix(self._default_suffix("scroll_speed", "{:.1f}"))
        self.scroll_speed_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Scroll Speed:", self.scroll_speed_spin)

        self.scroll_exp_spin = QDoubleSpinBox()
        self.scroll_exp_spin.setRange(0.5, 5.0)
        self.scroll_exp_spin.setSingleStep(0.1)
        self.scroll_exp_spin.setValue(data.get("scroll_exponent", 2.0))
        self.scroll_exp_spin.setSuffix(self._default_suffix("scroll_exponent", "{:.1f}"))
        self.scroll_exp_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Scroll Exponent:", self.scroll_exp_spin)

        self.zoom_speed_spin = QDoubleSpinBox()
        self.zoom_speed_spin.setRange(0, 20)
        self.zoom_speed_spin.setSingleStep(0.5)
        self.zoom_speed_spin.setValue(data.get("zoom_speed", 2.0))
        self.zoom_speed_spin.setSuffix(self._default_suffix("zoom_speed", "{:.1f}"))
        self.zoom_speed_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Zoom Speed:", self.zoom_speed_spin)

        layout.addWidget(grp)

        # Desktop switch
        grp = QGroupBox("Desktop Switching")
        fl = QFormLayout(grp)

        self.dswitch_thresh_spin = QSpinBox()
        self.dswitch_thresh_spin.setRange(0, 500)
        self.dswitch_thresh_spin.setValue(data.get("desktop_switch_threshold", 200))
        self.dswitch_thresh_spin.setSuffix(self._default_suffix("desktop_switch_threshold"))
        self.dswitch_thresh_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Threshold:", self.dswitch_thresh_spin)

        self.dswitch_cool_spin = QSpinBox()
        self.dswitch_cool_spin.setRange(100, 2000)
        self.dswitch_cool_spin.setSingleStep(50)
        self.dswitch_cool_spin.setValue(data.get("desktop_switch_cooldown_ms", 500))
        self.dswitch_cool_spin.setSuffix(self._default_suffix("desktop_switch_cooldown_ms"))
        self.dswitch_cool_spin.valueChanged.connect(self._on_changed)
        fl.addRow("Cooldown (ms):", self.dswitch_cool_spin)

        layout.addWidget(grp)

        # Inversion
        grp = QGroupBox("Inversion")
        hl = QHBoxLayout(grp)
        self.invert_x_cb = QCheckBox("Invert Horizontal Scroll")
        self.invert_x_cb.setChecked(data.get("invert_scroll_x", False))
        self.invert_x_cb.stateChanged.connect(self._on_changed)
        hl.addWidget(self.invert_x_cb)
        self.invert_y_cb = QCheckBox("Invert Vertical Scroll")
        self.invert_y_cb.setChecked(data.get("invert_scroll_y", False))
        self.invert_y_cb.stateChanged.connect(self._on_changed)
        hl.addWidget(self.invert_y_cb)
        layout.addWidget(grp)

        layout.addStretch()

    def _on_changed(self):
        if not self._building:
            self.changed.emit()

    def get_data(self):
        """Return profile data as dict."""
        data = {}
        if not self.is_default:
            wm_text = self.wm_class_edit.text().strip()
            if wm_text:
                data["match_wm_class"] = [s.strip() for s in wm_text.split(",") if s.strip()]

        axis_keys = ["tx", "ty", "tz", "rx", "ry", "rz"]
        data["axis_mapping"] = {}
        for i, key in enumerate(axis_keys):
            data["axis_mapping"][key] = AXIS_ACTIONS[self.axis_combos[i].currentIndex()]

        data["button_mapping"] = {}
        for i in range(2):
            data["button_mapping"][str(i)] = BTN_ACTIONS[self.btn_combos[i].currentIndex()]

        data["sensitivity"] = self.sensitivity_spin.value()
        data["deadzone"] = self.deadzone_spin.value()
        data["scroll_speed"] = self.scroll_speed_spin.value()
        data["scroll_exponent"] = self.scroll_exp_spin.value()
        data["zoom_speed"] = self.zoom_speed_spin.value()
        data["desktop_switch_threshold"] = self.dswitch_thresh_spin.value()
        data["desktop_switch_cooldown_ms"] = self.dswitch_cool_spin.value()
        data["invert_scroll_x"] = self.invert_x_cb.isChecked()
        data["invert_scroll_y"] = self.invert_y_cb.isChecked()
        return data

# ── Live Preview Widget ───────────────────────────────────────────────

class LivePreview(QGroupBox):
    """Shows real-time SpaceMouse axis values as progress bars."""

    def __init__(self):
        super().__init__("Live Axis Preview")
        layout = QFormLayout(self)
        self.bars = []
        for name in AXIS_NAMES:
            bar = QProgressBar()
            bar.setRange(-350, 350)
            bar.setValue(0)
            bar.setFormat("%v")
            bar.setTextVisible(True)
            layout.addRow(name + ":", bar)
            self.bars.append(bar)

        self.btn_labels = []
        for i in range(2):
            lbl = QLabel("[ ]")
            lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
            layout.addRow(f"Button {i+1}:", lbl)
            self.btn_labels.append(lbl)

    def update_axes(self, values):
        for i, val in enumerate(values):
            if i < len(self.bars):
                self.bars[i].setValue(val)

    def update_button(self, bnum, pressed):
        if 0 <= bnum < len(self.btn_labels):
            self.btn_labels[bnum].setText("[X]" if pressed else "[ ]")
            self.btn_labels[bnum].setStyleSheet(
                "font-weight: bold; font-size: 14px; color: green;" if pressed
                else "font-weight: bold; font-size: 14px;")

# ── Settings Window ───────────────────────────────────────────────────

class SettingsWindow(QMainWindow):
    """Main settings window with profile list and editor."""

    def __init__(self, config_data, on_save_callback, settings_state=None):
        super().__init__()
        self.on_save = on_save_callback
        self._settings_state = settings_state or {"auto_focus": True, "autostart": True}
        self.setWindowTitle("SpaceMouse Configuration")
        self.setMinimumSize(900, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Left: profile list + general settings
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # General settings group
        gen_grp = QGroupBox("General")
        gen_layout = QVBoxLayout(gen_grp)
        self.autostart_cb = QCheckBox("Start automatically at login")
        self.autostart_cb.setChecked(self._settings_state.get("autostart", True))
        gen_layout.addWidget(self.autostart_cb)
        left_layout.addWidget(gen_grp)

        lbl = QLabel("Profiles")
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_layout.addWidget(lbl)

        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.clicked.connect(self._add_profile)
        btn_row.addWidget(self.add_btn)
        self.del_btn = QPushButton("- Delete")
        self.del_btn.clicked.connect(self._del_profile)
        btn_row.addWidget(self.del_btn)
        left_layout.addLayout(btn_row)

        # Live preview
        self.preview = LivePreview()
        left_layout.addWidget(self.preview)

        # Status
        self.status_label = QLabel("Daemon: checking...")
        left_layout.addWidget(self.status_label)

        # Right: editor stack
        self.editor_stack = QStackedWidget()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.editor_stack)
        splitter.setSizes([280, 620])
        main_layout.addWidget(splitter)

        # Bottom buttons
        bottom = QHBoxLayout()
        save_btn = QPushButton("Save && Apply")
        save_btn.setStyleSheet("font-weight: bold; padding: 8px 16px;")
        save_btn.clicked.connect(self._save)
        bottom.addStretch()
        bottom.addWidget(save_btn)
        main_layout.addLayout(bottom)

        # Load profiles
        self.editors = {}
        self._load_profiles(config_data)

        # Status timer
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(2000)
        self._update_status()

    def _load_profiles(self, config_data):
        """Populate profile list and editors from config data."""
        profiles = config_data.get("profiles", {"default": config_data})
        if "default" not in profiles:
            profiles["default"] = {}

        self.profile_list.clear()
        while self.editor_stack.count() > 0:
            w = self.editor_stack.widget(0)
            if w:
                self.editor_stack.removeWidget(w)
        self.editors.clear()

        default_data = profiles.get("default", {})

        # Default first
        for name in ["default"] + [n for n in profiles if n != "default"]:
            data = profiles[name]
            is_default = (name == "default")
            item = QListWidgetItem(name)
            if is_default:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.profile_list.addItem(item)
            editor = ProfileEditor(name, data, is_default,
                                   default_data=None if is_default else default_data)
            editor.changed.connect(self._on_editor_changed)
            self.editor_stack.addWidget(editor)
            self.editors[name] = editor

        if self.profile_list.count() > 0:
            self.profile_list.setCurrentRow(0)

    def _on_profile_selected(self, row):
        if 0 <= row < self.editor_stack.count():
            self.editor_stack.setCurrentIndex(row)
        self.del_btn.setEnabled(row > 0)

    def _on_editor_changed(self):
        self.setWindowTitle("SpaceMouse Configuration *")

    def _add_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile",
            "Profile name (e.g. firefox, krita):")
        if not ok or not name.strip():
            return
        name = name.strip().lower().replace(" ", "_")
        if name in self.editors:
            QMessageBox.warning(self, "Error", f"Profile '{name}' already exists.")
            return

        # Copy values from the default profile as starting point
        default_data = {}
        if "default" in self.editors:
            default_data = self.editors["default"].get_data()
        data = dict(default_data)
        data["match_wm_class"] = [name]

        item = QListWidgetItem(name)
        self.profile_list.addItem(item)
        editor = ProfileEditor(name, data, False, default_data=default_data)
        editor.changed.connect(self._on_editor_changed)
        self.editor_stack.addWidget(editor)
        self.editors[name] = editor
        self.profile_list.setCurrentRow(self.profile_list.count() - 1)

    def _del_profile(self):
        row = self.profile_list.currentRow()
        if row <= 0:
            return
        item = self.profile_list.item(row)
        name = item.text()
        reply = QMessageBox.question(self, "Delete Profile",
            f"Delete profile '{name}'?")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.profile_list.takeItem(row)
        widget = self.editor_stack.widget(row)
        if widget:
            self.editor_stack.removeWidget(widget)
        del self.editors[name]
        self.profile_list.setCurrentRow(0)

    def _save(self):
        config = {
            "settings": {
                "autostart": self.autostart_cb.isChecked(),
            },
            "profiles": {},
        }
        for i in range(self.profile_list.count()):
            name = self.profile_list.item(i).text()
            editor = self.editors[name]
            config["profiles"][name] = editor.get_data()

        self.on_save(config)
        self.setWindowTitle("SpaceMouse Configuration")

    def _update_status(self):
        resp = send_daemon_cmd("STATUS")
        if resp:
            self.status_label.setText(f"Daemon: {resp.splitlines()[0]}")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("Daemon: not connected")
            self.status_label.setStyleSheet("color: red;")

    def sync_settings(self, settings_state):
        """Update settings checkboxes to match current state."""
        self._settings_state = settings_state
        self.autostart_cb.setChecked(settings_state.get("autostart", True))

    def set_spnav_reader(self, reader):
        reader.axes_updated.connect(self.preview.update_axes)
        reader.button_pressed.connect(self.preview.update_button)

# ── Tray Icon ─────────────────────────────────────────────────────────

def create_tray_icon_pixmap(text="SM"):
    """Create a simple text-based tray icon."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(50, 120, 200))
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
        self.app.setApplicationName("SpaceMouse Config")

        # Load config
        self.config = self._load_config()
        self._cleaned_up = False

        # Extract persistent settings
        settings = self.config.get("settings", {})
        self._autostart = settings.get("autostart", True)

        # Settings window (created but hidden)
        self.settings_window = SettingsWindow(
            self.config, self._on_save,
            settings_state={"autostart": self._autostart})

        # System tray
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon(create_tray_icon_pixmap("SM")))
        self.tray.setToolTip("SpaceMouse: default")
        self.tray.activated.connect(self._on_tray_activated)

        # State
        self._paused = False
        self.window_monitor = None

        # Tray menu
        menu = QMenu()
        self._profile_actions = []
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)
        self.tray.show()

        # SpaceMouse reader
        self.spnav_reader = SpnavReader()
        self.settings_window.set_spnav_reader(self.spnav_reader)
        self.spnav_reader.start()

        # Window monitor (always active for click-focus profile switching)
        self._start_window_monitor()

        # Signal handling for clean shutdown
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
            "zoom_speed": 2.0, "desktop_switch_threshold": 200,
            "desktop_switch_cooldown_ms": 500,
            "axis_mapping": {"tx": "scroll_h", "ty": "scroll_v", "tz": "zoom",
                           "rx": "none", "ry": "desktop_switch", "rz": "none"},
            "button_mapping": {"0": "overview", "1": "show_desktop"},
            "invert_scroll_x": False, "invert_scroll_y": False
        }}}

    def _cleanup(self):
        """Stop threads and KWin scripts. Idempotent."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.spnav_reader.stop()
        self._stop_window_monitor()

    def _sigterm_handler(self, signum, frame):
        """Handle SIGTERM/SIGINT for clean shutdown."""
        self._cleanup()
        self.tray.hide()
        self.app.quit()

    def _on_save(self, config):
        """Save config to disk and reload daemon."""
        self.config = config
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)

        # Reload daemon
        send_daemon_cmd("RELOAD")

        # Handle autostart change
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

        # Update window monitor profiles
        if self.window_monitor:
            profiles = config.get("profiles", {})
            self.window_monitor.update_profiles(profiles)

        # Rebuild tray menu
        menu = QMenu()
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)

    def _rebuild_tray_menu(self, menu):
        profiles = self.config.get("profiles", {})
        self._profile_actions = []
        for name in profiles:
            action = QAction(f"Profile: {name}", menu)
            action.setData(name)
            action.triggered.connect(lambda _c=False, n=name: self._switch_profile(n))
            menu.addAction(action)
            self._profile_actions.append(action)

        menu.addSeparator()

        # Pause/Resume daemon
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

    def _refresh_tray_menu(self):
        menu = QMenu()
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)

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

    def _toggle_pause(self):
        """Pause or resume the daemon."""
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
        self._refresh_tray_menu()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_settings()

    def _show_settings(self):
        self.settings_window.sync_settings({
            "autostart": self._autostart,
        })
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _on_window_changed(self, wm_class, profile_name):
        self.tray.setToolTip(f"SpaceMouse: {profile_name} ({wm_class})")

    def _quit(self):
        """Stop everything: window monitor, spnav reader, daemon, GUI.

        Does NOT stop spacemouse-config.service from within itself —
        a clean exit (code 0) with Restart=on-failure won't restart.
        """
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
