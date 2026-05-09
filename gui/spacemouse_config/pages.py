"""Three settings pages: Desktop daemon profiles, FreeCAD, Blender."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QMessageBox, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from .backends import BlenderConfig, FreeCADConfig
from .constants import (AXIS_ACTIONS, AXIS_KEYS, BTN_ACTIONS, FREECAD_BTN_COMMANDS,
                        FREECAD_BTN_LABELS, FREECAD_NAV_LABELS, FREECAD_NAV_STYLES)
from .helpers import make_card, make_slider
from .widgets import AxesCard, ToggleSwitch, make_toggle


# ── DesktopPage ───────────────────────────────────────────────────────

class DesktopPage(QWidget):
    """Daemon profile editor — switches between all daemon profiles."""
    changed = Signal()

    PROTECTED_PROFILES = {"default"}  # cannot be deleted

    def __init__(self, config_data):
        super().__init__()
        self._building = True
        self._config = config_data
        self._current_profile = "default"
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

        # ── Card 0: PROFILE selector ──
        card, cl = make_card("PROFILE")
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.profile_combo = QComboBox()
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        prow.addWidget(self.profile_combo, 1)
        new_btn = QPushButton("+ New")
        new_btn.clicked.connect(self._on_new_profile)
        prow.addWidget(new_btn)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete_profile)
        prow.addWidget(self.delete_btn)
        cl.addLayout(prow)
        layout.addWidget(card)

        # ── Card 0b: MATCH APPS ──
        card, cl = make_card("MATCH APPS (when this profile is auto-selected)")
        fl = QFormLayout()
        fl.setSpacing(8)
        self.wm_class_edit = QLineEdit()
        self.wm_class_edit.setPlaceholderText("comma-separated WM class names, e.g. firefox, Firefox")
        self.wm_class_edit.textChanged.connect(self._emit_changed)
        fl.addRow("WM Classes:", self.wm_class_edit)
        bm_row = QHBoxLayout()
        self.browser_mode_toggle = ToggleSwitch()
        self.browser_mode_toggle.stateChanged.connect(self._emit_changed)
        bm_row.addWidget(self.browser_mode_toggle)
        bm_row.addWidget(QLabel("Browser Mode (smart actions send Space/Arrows)"))
        bm_row.addStretch()
        fl.addRow("", bm_row)
        cl.addLayout(fl)
        layout.addWidget(card)

        # ── Card 1: SENSITIVITY & SPEED ──
        card, cl = make_card("SENSITIVITY & SPEED")
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
        fl.addRow("Global Deadzone:", self.deadzone_w)

        cl.addLayout(fl)
        layout.addWidget(card)

        # ── Card 3: AXES (AxesCard) ──
        desktop_axis_labels = [
            "TX (Left/Right)", "TY (Push/Pull)", "TZ (Up/Down)",
            "RX (Pitch)", "RY (Roll)", "RZ (Yaw/Twist)",
        ]
        self.axes_card = AxesCard(
            desktop_axis_labels,
            show_action=True,
            action_items=AXIS_ACTION_LABELS,
            show_invert=True,
            show_deadzone=True,
            deadzone_enabled=True,
            deadzone_max=100,
            extra_toggles=[
                ("Invert Horizontal Scroll", False),
                ("Invert Vertical Scroll", False),
            ],
        )
        self.axes_card.changed.connect(self._emit_changed)
        layout.addWidget(self.axes_card)

        # ── Card 4: BUTTONS ──
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

        # ── Card 5: DESKTOP SWITCHING ──
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

        self._refresh_profile_combo()
        self._load_profile()

    def _emit_changed(self):
        if not self._building:
            self.changed.emit()

    def _refresh_profile_combo(self):
        profiles = self._config.get("profiles", {})
        names = list(profiles.keys())
        if "default" not in names:
            names.insert(0, "default")
        self._building = True
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        if self._current_profile in names:
            self.profile_combo.setCurrentText(self._current_profile)
        else:
            self._current_profile = "default"
            self.profile_combo.setCurrentText("default")
        self.profile_combo.blockSignals(False)
        self.delete_btn.setEnabled(self._current_profile not in self.PROTECTED_PROFILES)
        self._building = False

    def _on_profile_changed(self, name):
        if self._building or not name:
            return
        # Save current widget state into the previously selected profile
        self._save_current_profile()
        self._current_profile = name
        self.delete_btn.setEnabled(name not in self.PROTECTED_PROFILES)
        self._building = True
        self._load_profile()
        self._building = False

    def _on_new_profile(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok or not name:
            return
        name = name.strip()
        if not name or name.startswith("_") or name == "default":
            QMessageBox.warning(self, "Invalid Name",
                                "Name cannot be empty, start with '_', or be 'default'.")
            return
        profiles = self._config.setdefault("profiles", {})
        if name in profiles:
            QMessageBox.warning(self, "Exists", f"Profile '{name}' already exists.")
            return
        # Save current first, then create empty new profile
        self._save_current_profile()
        profiles[name] = {
            "match_wm_class": [],
            "axis_mapping": {k: "none" for k in AXIS_KEYS},
            "button_mapping": {"0": "none", "1": "none"},
        }
        self._current_profile = name
        self._refresh_profile_combo()
        self._load_profile()
        self._emit_changed()

    def _on_delete_profile(self):
        if self._current_profile in self.PROTECTED_PROFILES:
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{self._current_profile}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        profiles = self._config.setdefault("profiles", {})
        profiles.pop(self._current_profile, None)
        self._current_profile = "default"
        self._refresh_profile_combo()
        self._load_profile()
        self._emit_changed()

    def _save_current_profile(self):
        """Capture current widget state into self._config for the active profile."""
        profiles = self._config.setdefault("profiles", {})
        profiles[self._current_profile] = self._get_profile_data()

    def _load_profile(self):
        profiles = self._config.get("profiles", {})
        data = profiles.get(self._current_profile, {})

        # Match Apps + Browser Mode
        wm = data.get("match_wm_class", [])
        self.wm_class_edit.setText(", ".join(wm) if isinstance(wm, list) else "")
        self.browser_mode_toggle.setChecked(bool(data.get("browser_keys", False)))

        self.sensitivity_s.setValue(int(data.get("sensitivity", 1.0) * 10))
        self.scroll_speed_s.setValue(int(data.get("scroll_speed", 3.0) * 10))
        self.zoom_speed_s.setValue(int(data.get("zoom_speed", 2.0) * 10))
        self.scroll_exp_s.setValue(int(data.get("scroll_exponent", 2.0) * 10))
        self.deadzone_s.setValue(data.get("deadzone", 15))

        # Axes card
        amap = data.get("axis_mapping", {})
        for i, key in enumerate(AXIS_KEYS):
            action = amap.get(key, "none")
            idx = AXIS_ACTIONS.index(action) if action in AXIS_ACTIONS else 0
            self.axes_card.action_combos[i].setCurrentIndex(idx)

        # Per-axis deadzone
        adz = data.get("axis_deadzone", {})
        for i, key in enumerate(AXIS_KEYS):
            self.axes_card.deadzone_sliders[i].setValue(adz.get(key, 0))

        # Invert toggles (axes card has no per-axis invert in config yet,
        # but the toggle is there for future use — default all off)
        for toggle in self.axes_card.invert_toggles:
            toggle.setChecked(False)

        # Extra toggles: [0] = Invert H Scroll, [1] = Invert V Scroll
        self.axes_card.extra_toggle_widgets[0].setChecked(data.get("invert_scroll_x", False))
        self.axes_card.extra_toggle_widgets[1].setChecked(data.get("invert_scroll_y", False))

        bmap = data.get("button_mapping", {})
        for i in range(2):
            action = bmap.get(str(i), "none")
            idx = BTN_ACTIONS.index(action) if action in BTN_ACTIONS else 0
            self.btn_combos[i].setCurrentIndex(idx)

        self.dswitch_thresh_s.setValue(data.get("desktop_switch_threshold", 200))
        self.dswitch_cool_s.setValue(data.get("desktop_switch_cooldown_ms", 500))

    def _get_profile_data(self):
        """Return current UI state as profile data dict."""
        data = {}
        # Match Apps + Browser Mode
        wm = [s.strip() for s in self.wm_class_edit.text().split(",") if s.strip()]
        if wm:
            data["match_wm_class"] = wm
        if self.browser_mode_toggle.isChecked():
            data["browser_keys"] = True
        data["sensitivity"] = self.sensitivity_s.value() / 10.0
        data["scroll_speed"] = self.scroll_speed_s.value() / 10.0
        data["zoom_speed"] = self.zoom_speed_s.value() / 10.0
        data["scroll_exponent"] = self.scroll_exp_s.value() / 10.0
        data["deadzone"] = self.deadzone_s.value()

        data["axis_mapping"] = {}
        for i, key in enumerate(AXIS_KEYS):
            data["axis_mapping"][key] = AXIS_ACTIONS[self.axes_card.action_combos[i].currentIndex()]

        data["axis_deadzone"] = {}
        for i, key in enumerate(AXIS_KEYS):
            data["axis_deadzone"][key] = self.axes_card.deadzone_sliders[i].value()

        data["button_mapping"] = {}
        for i in range(2):
            data["button_mapping"][str(i)] = BTN_ACTIONS[self.btn_combos[i].currentIndex()]

        data["invert_scroll_x"] = self.axes_card.extra_toggle_widgets[0].isChecked()
        data["invert_scroll_y"] = self.axes_card.extra_toggle_widgets[1].isChecked()
        data["desktop_switch_threshold"] = self.dswitch_thresh_s.value()
        data["desktop_switch_cooldown_ms"] = self.dswitch_cool_s.value()
        return data

    def get_all_config(self):
        """Return full daemon config dict with the current profile saved."""
        self._save_current_profile()
        return self._config

    def update_config(self, config):
        """Replace config data and refresh UI."""
        self._config = config
        self._building = True
        self._refresh_profile_combo()
        self._load_profile()
        self._building = False


# ── FreeCADPage ───────────────────────────────────────────────────────

class FreeCADPage(QWidget):
    """FreeCAD SpaceMouse settings editor."""
    changed = Signal()

    _FC_AXIS_KEYS = ["panlr", "panud", "zoom", "tilt", "roll", "spin"]

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

        # ── Card 1: FREECAD (app-specific warnings) ──
        card, cl = make_card("FREECAD")
        if not self._fc.is_available():
            warn = QLabel("FreeCAD user.cfg not found. Start FreeCAD once to generate it.")
            warn.setStyleSheet(
                "color: #f9e2af; background-color: #3a3636; "
                "border-radius: 6px; padding: 8px;")
            warn.setWordWrap(True)
            cl.addWidget(warn)

        self.running_warn = QLabel(
            "FreeCAD is running \u2014 it overwrites user.cfg on exit.\n"
            "Close FreeCAD before applying changes.")
        self.running_warn.setStyleSheet(
            "color: #f38ba8; background-color: #3a2a2a; "
            "border-radius: 6px; padding: 8px;")
        self.running_warn.setWordWrap(True)
        self.running_warn.setVisible(False)
        cl.addWidget(self.running_warn)
        layout.addWidget(card)

        # ── Card 2: SENSITIVITY & SPEED ──
        card, cl = make_card("SENSITIVITY & SPEED")
        fl = QFormLayout()
        fl.setSpacing(10)
        self.sensitivity_w, self.sensitivity_s, _ = make_slider(-50, 50, -15, 0)
        self.sensitivity_s.valueChanged.connect(self._emit_changed)
        fl.addRow("Global Sensitivity:", self.sensitivity_w)
        cl.addLayout(fl)
        layout.addWidget(card)

        # ── Card 3: AXES (AxesCard) ──
        fc_axis_labels = [
            "TX \u2014 PanLR", "TY \u2014 PanUD", "TZ \u2014 Zoom",
            "RX \u2014 Tilt", "RY \u2014 Spin", "RZ \u2014 Roll",
        ]
        self.axes_card = AxesCard(
            fc_axis_labels,
            show_action=False,
            show_enable=True,
            show_invert=True,
            show_deadzone=True,
            deadzone_enabled=True,
            deadzone_max=100,
            extra_toggles=[
                ("Flip Y/Z", True),
                ("Dominant Mode", False),
            ],
        )
        self.axes_card.changed.connect(self._emit_changed)
        layout.addWidget(self.axes_card)

        # ── Card 4: BUTTONS ──
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

        # ── Card 5: NAVIGATION ──
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

        for i, key in enumerate(self._FC_AXIS_KEYS):
            self.axes_card.enable_toggles[i].setChecked(settings.get(f"{key}_enable", True))
            self.axes_card.invert_toggles[i].setChecked(settings.get(f"{key}_reverse", False))
            self.axes_card.deadzone_sliders[i].setValue(settings.get(f"{key}_deadzone", 0))

        # Extra toggles: [0] = Flip Y/Z, [1] = Dominant
        self.axes_card.extra_toggle_widgets[0].setChecked(settings.get("flip_yz", True))
        self.axes_card.extra_toggle_widgets[1].setChecked(settings.get("dominant", False))

        for i, combo in enumerate(self.fc_btn_combos):
            cmd = settings.get(f"btn{i}_command", "")
            idx = FREECAD_BTN_COMMANDS.index(cmd) if cmd in FREECAD_BTN_COMMANDS else 0
            combo.setCurrentIndex(idx)

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
            "flip_yz": self.axes_card.extra_toggle_widgets[0].isChecked(),
            "dominant": self.axes_card.extra_toggle_widgets[1].isChecked(),
        }
        for i, key in enumerate(self._FC_AXIS_KEYS):
            s[f"{key}_enable"] = self.axes_card.enable_toggles[i].isChecked()
            s[f"{key}_reverse"] = self.axes_card.invert_toggles[i].isChecked()
            s[f"{key}_deadzone"] = self.axes_card.deadzone_sliders[i].value()

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


# ── BlenderPage ───────────────────────────────────────────────────────

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

        # ── Card 1: BLENDER SYNC (app-specific) ──
        card, cl = make_card("BLENDER SYNC")
        self.script_status = QLabel()
        self.script_status.setWordWrap(True)
        cl.addWidget(self.script_status)

        self.install_btn = QPushButton("Install Startup Script")
        self.install_btn.clicked.connect(self._install_script)
        cl.addWidget(self.install_btn)
        self._update_script_status()
        layout.addWidget(card)

        # ── Card 2: SENSITIVITY & SPEED ──
        card, cl = make_card("SENSITIVITY & SPEED")
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
        fl.addRow("Global Deadzone:", self.bl_deadzone_w)

        cl.addLayout(fl)
        layout.addWidget(card)

        # ── Card 3: AXES (AxesCard) ──
        bl_axis_labels = [
            "TX \u2014 Pan X", "TY \u2014 Pan Y", "TZ \u2014 Pan Z",
            "RX \u2014 Rot X", "RY \u2014 Rot Y", "RZ \u2014 Rot Z",
        ]
        self.axes_card = AxesCard(
            bl_axis_labels,
            show_action=False,
            show_enable=True,
            show_invert=True,
            show_deadzone=False,
            extra_toggles=[
                ("Lock Horizon", False),
                ("Swap Y/Z Panning", False),
                ("Invert Zoom", False),
            ],
        )
        self.axes_card.changed.connect(self._emit_changed)
        layout.addWidget(self.axes_card)

        # Lock Horizon warning (below axes card)
        lock_warn = QLabel(
            "Lock Horizon blocks the RX/pitch axis \u2014 keep OFF for full 6DOF")
        lock_warn.setStyleSheet(
            "color: #f9e2af; font-size: 11px; background: transparent; padding: 0 12px;")
        lock_warn.setWordWrap(True)
        layout.addWidget(lock_warn)

        # ── Card 4: BUTTONS ──
        card, cl = make_card("BUTTONS")
        info = QLabel("Blender buttons are configured via Blender's Keymap Editor")
        info.setStyleSheet("color: #a6adc8; font-style: italic; background: transparent;")
        info.setWordWrap(True)
        cl.addWidget(info)
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

        # Enable toggles: all enabled by default (Blender has no per-axis enable,
        # stored in our JSON for UI consistency)
        enable_keys = [
            "ndof_panx_enable", "ndof_pany_enable", "ndof_panz_enable",
            "ndof_rotx_enable", "ndof_roty_enable", "ndof_rotz_enable",
        ]
        for i, key in enumerate(enable_keys):
            self.axes_card.enable_toggles[i].setChecked(s.get(key, True))

        # Invert toggles: pan[0-2] and rot[3-5]
        pan_keys = ["ndof_panx_invert_axis", "ndof_pany_invert_axis", "ndof_panz_invert_axis"]
        rot_keys = ["ndof_rotx_invert_axis", "ndof_roty_invert_axis", "ndof_rotz_invert_axis"]
        for i, key in enumerate(pan_keys):
            self.axes_card.invert_toggles[i].setChecked(s.get(key, False))
        for i, key in enumerate(rot_keys):
            self.axes_card.invert_toggles[i + 3].setChecked(s.get(key, False))

        # Extra toggles: [0] = Lock Horizon, [1] = Swap Y/Z, [2] = Invert Zoom
        self.axes_card.extra_toggle_widgets[0].setChecked(s.get("ndof_lock_horizon", False))
        self.axes_card.extra_toggle_widgets[1].setChecked(s.get("ndof_pan_yz_swap_axis", False))
        self.axes_card.extra_toggle_widgets[2].setChecked(s.get("ndof_zoom_invert", False))

    def get_settings(self):
        """Return dict of Blender NDOF settings."""
        s = {
            "ndof_sensitivity": self.bl_sensitivity_s.value() / 100.0,
            "ndof_orbit_sensitivity": self.bl_orbit_s.value() / 100.0,
            "ndof_deadzone": self.bl_deadzone_s.value() / 100.0,
            "ndof_lock_horizon": self.axes_card.extra_toggle_widgets[0].isChecked(),
            "ndof_pan_yz_swap_axis": self.axes_card.extra_toggle_widgets[1].isChecked(),
            "ndof_zoom_invert": self.axes_card.extra_toggle_widgets[2].isChecked(),
        }
        for i, axis in enumerate(["x", "y", "z"]):
            s[f"ndof_pan{axis}_invert_axis"] = self.axes_card.invert_toggles[i].isChecked()
            s[f"ndof_rot{axis}_invert_axis"] = self.axes_card.invert_toggles[i + 3].isChecked()
            s[f"ndof_pan{axis}_enable"] = self.axes_card.enable_toggles[i].isChecked()
            s[f"ndof_rot{axis}_enable"] = self.axes_card.enable_toggles[i + 3].isChecked()
        return s

    def apply_settings(self):
        """Write settings to blender-ndof.json."""
        self._bc.write(self.get_settings())
