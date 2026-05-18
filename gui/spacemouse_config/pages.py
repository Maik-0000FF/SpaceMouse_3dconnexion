"""Three settings pages: Desktop daemon profiles, FreeCAD, Blender."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .add_app_dialog import AddAppDialog
from .backends import BlenderConfig, FreeCADConfig
from .chip_list import ChipList
from .constants import (
    AXIS_ACTION_LABELS,
    AXIS_ACTIONS,
    AXIS_KEYS,
    BTN_ACTION_LABELS,
    BTN_ACTIONS,
    COLOR_ACCENT,
    COLOR_BG_ERROR,
    COLOR_BG_WARN,
    COLOR_ERROR,
    COLOR_OK,
    COLOR_TEXT_DIM,
    COLOR_WARN,
    COLOR_WARN_ALT,
    DEFAULT_BUTTON_ROWS,
    FREECAD_BTN_COMMANDS,
    FREECAD_BTN_LABELS,
    FREECAD_NAV_LABELS,
    FREECAD_NAV_STYLES,
    FREECAD_ORBIT_STYLES,
    MAX_BUTTONS,
)
from .helpers import NoScrollComboBox, make_card, make_slider
from .widgets import AxesCard

# ── DesktopPage ───────────────────────────────────────────────────────


class DesktopPage(QWidget):
    """Edits the ``default`` desktop profile plus the ``passthrough``
    profile's match list (3D apps the daemon should leave alone)."""

    changed = Signal()

    def __init__(self, config_data):
        super().__init__()
        self._building = True
        self._config = config_data
        # Tracks the connected device's hardware button count so we
        # only flag bnums beyond it as orphans (and offer a Remove
        # affordance for those). 0 = unknown device → fall back to
        # offering Remove on every non-default row.
        self._device_button_count = 0
        self._setup_ui()
        self._load_state()
        self._building = False

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 8, 0)

        # ── Card 0: 3D APPS (passthrough match list) ──
        card, cl = make_card("3D APPS — desktop settings do not apply here")
        intro = QLabel(
            "These apps bring their own SpaceMouse support. The desktop "
            "settings below are NOT applied to them — the daemon stays "
            "silent and each app handles SpaceMouse input itself via "
            "libspnav."
        )
        intro.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px; padding-bottom: 4px;")
        intro.setWordWrap(True)
        cl.addWidget(intro)

        self.wm_class_chips = ChipList()
        cl.addWidget(self.wm_class_chips)

        btn_row = QHBoxLayout()
        manage_btn = QPushButton("Manage apps…")
        manage_btn.clicked.connect(self._on_manage_apps)
        btn_row.addWidget(manage_btn)
        btn_row.addStretch()
        cl.addLayout(btn_row)

        layout.addWidget(card)

        # ── Card 1: SENSITIVITY & SPEED ──
        card, cl = make_card("SENSITIVITY & SPEED")
        fl = QFormLayout()
        fl.setSpacing(10)

        self.sensitivity_w, self.sensitivity_s, _ = make_slider(0.1, 10.0, 1.0, 1)
        self.sensitivity_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Sensitivity:", self.sensitivity_w)

        self.scroll_speed_w, self.scroll_speed_s, _ = make_slider(0.1, 5.0, 3.0, 1)
        self.scroll_speed_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Scroll Speed:", self.scroll_speed_w)

        self.zoom_speed_w, self.zoom_speed_s, _ = make_slider(0.1, 5.0, 2.0, 1)
        self.zoom_speed_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Zoom Speed:", self.zoom_speed_w)

        self.scroll_exp_w, self.scroll_exp_s, _ = make_slider(0.5, 5.0, 2.0, 1)
        self.scroll_exp_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Scroll Curve:", self.scroll_exp_w)

        self.deadzone_w, self.deadzone_s, _ = make_slider(0, 200, 0, 0)
        self.deadzone_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Global Deadzone:", self.deadzone_w)

        cl.addLayout(fl)
        layout.addWidget(card)

        # ── Card 3: AXES (AxesCard) ──
        desktop_axis_labels = [
            "TX (Left/Right)",
            "TY (Push/Pull)",
            "TZ (Up/Down)",
            "RX (Pitch)",
            "RY (Roll)",
            "RZ (Yaw/Twist)",
        ]
        self.axes_card = AxesCard(
            desktop_axis_labels,
            show_action=True,
            action_items=AXIS_ACTION_LABELS,
            show_invert=True,
            show_deadzone=True,
            deadzone_enabled=True,
            deadzone_max=200,
        )
        self.axes_card.changed.connect(self._emit_changed)
        layout.addWidget(self.axes_card)

        # ── Card 4: BUTTONS ──
        card, cl = make_card("BUTTONS")
        hint = QLabel(
            "Press a button on the SpaceMouse to detect it. Bound buttons "
            "appear here automatically — assign an action from the dropdown."
        )
        hint.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px; padding-bottom: 4px;")
        hint.setWordWrap(True)
        cl.addWidget(hint)

        self.btn_rows_layout = QGridLayout()
        self.btn_rows_layout.setHorizontalSpacing(6)
        self.btn_rows_layout.setVerticalSpacing(8)
        # Two button-row blocks per grid row. Each block uses 3 cols:
        # label / combo / remove. Column 3 is a fixed gap between the
        # two blocks, column 7 absorbs the trailing slack so the filled
        # cells stay compact instead of stretching to the card width.
        self.btn_rows_layout.setColumnMinimumWidth(3, 24)
        self.btn_rows_layout.setColumnStretch(7, 1)
        cl.addLayout(self.btn_rows_layout)
        # bnum → {label, combo, remove_btn, container} for active rows only.
        self.btn_rows = {}
        self._highlight_timers = {}
        layout.addWidget(card)

        # ── Card 5: DESKTOP SWITCHING ──
        card, cl = make_card("DESKTOP SWITCHING")
        fl = QFormLayout()
        fl.setSpacing(8)
        self.dswitch_thresh_w, self.dswitch_thresh_s, _ = make_slider(0, 500, 200, 0)
        self.dswitch_thresh_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Threshold:", self.dswitch_thresh_w)

        self.dswitch_cool_w, self.dswitch_cool_s, _ = make_slider(100, 2000, 500, 0, " ms")
        self.dswitch_cool_s.sliderReleased.connect(self._emit_changed)
        fl.addRow("Cooldown:", self.dswitch_cool_w)

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

    # ── Button rows ──
    #
    # Each row is a QHBoxLayout, not a wrapper QWidget. The DARK_THEME
    # has a `QWidget { background-color: … }` rule, so a wrapper widget
    # would paint its own panel-coloured rectangle behind the controls,
    # breaking the visual match with AxesCard (which also uses bare
    # HBoxes inside its card).
    def _reset_button_rows(self):
        for timer in self._highlight_timers.values():
            timer.stop()
        self._highlight_timers.clear()
        for bnum in list(self.btn_rows):
            self._discard_row_widgets(self.btn_rows[bnum])
        self.btn_rows.clear()

    @staticmethod
    def _discard_row_widgets(row):
        for key in ("label", "combo", "remove_btn"):
            w = row.get(key)
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _add_button_row(self, bnum, action="none"):
        """Add (or return existing) row for `bnum`. Rows are laid out
        as a two-column grid sorted by bnum — adding triggers a
        relayout so the order stays stable."""
        if bnum in self.btn_rows:
            return self.btn_rows[bnum]
        if not (0 <= bnum < MAX_BUTTONS):
            return None

        label = QLabel(f"Button {bnum + 1}")
        label.setFixedWidth(72)
        combo = NoScrollComboBox()
        combo.addItems(BTN_ACTION_LABELS)
        idx = BTN_ACTIONS.index(action) if action in BTN_ACTIONS else 0
        combo.setCurrentIndex(idx)
        combo.setFixedWidth(160)
        combo.currentIndexChanged.connect(self._emit_changed)

        remove_btn = QPushButton("Remove")
        remove_btn.setToolTip(
            "Remove this orphaned button row — the connected device does not expose this button"
        )
        remove_btn.clicked.connect(lambda _, b=bnum: self._remove_button_row(b))

        self.btn_rows[bnum] = {
            "label": label,
            "combo": combo,
            "remove_btn": remove_btn,
        }
        self._update_remove_visibility(bnum)
        self._relayout_buttons()
        return self.btn_rows[bnum]

    def _is_orphan(self, bnum):
        """A row is an orphan iff its bnum is not on the connected
        device. Default rows are never orphans. With an unknown device
        (button_count == 0) anything outside the defaults is treated
        as orphan so the user has a way to clean it up."""
        if bnum in DEFAULT_BUTTON_ROWS:
            return False
        if self._device_button_count <= 0:
            return True
        return bnum >= self._device_button_count

    def _update_remove_visibility(self, bnum=None):
        targets = (bnum,) if bnum is not None else tuple(self.btn_rows)
        for b in targets:
            row = self.btn_rows.get(b)
            if row is None:
                continue
            row["remove_btn"].setVisible(self._is_orphan(b))

    def _remove_button_row(self, bnum):
        row = self.btn_rows.get(bnum)
        if row is None or bnum in DEFAULT_BUTTON_ROWS:
            return
        self._discard_row_widgets(row)
        timer = self._highlight_timers.pop(bnum, None)
        if timer:
            timer.stop()
        del self.btn_rows[bnum]
        self._relayout_buttons()
        self._emit_changed()

    def _relayout_buttons(self):
        """Re-pack the two-column grid sorted by bnum so add/remove
        does not leave holes.

        Each visible button row claims 3 grid columns (label, combo,
        remove). Two button rows share one grid row → 6 grid columns
        total. takeAt() releases the layout items without destroying
        their widgets so we can re-place them sorted.
        """
        for i in reversed(range(self.btn_rows_layout.count())):
            self.btn_rows_layout.takeAt(i)
        for idx, bnum in enumerate(sorted(self.btn_rows)):
            row = self.btn_rows[bnum]
            grid_row = idx // 2
            # Left block: cols 0..2. Right block: cols 4..6 (col 3 is the gap).
            base_col = 0 if idx % 2 == 0 else 4
            self.btn_rows_layout.addWidget(row["label"], grid_row, base_col)
            self.btn_rows_layout.addWidget(row["combo"], grid_row, base_col + 1)
            self.btn_rows_layout.addWidget(row["remove_btn"], grid_row, base_col + 2)

    def ensure_button_rows(self, count):
        """Reconcile button rows with the connected device's button count.

        Adds rows for bnums 0..count-1 so the user does not have to
        press each button once before seeing it. Trims rows beyond
        ``count`` that are still unassigned (action == ``none``) — but
        keeps user-configured rows even when they overshoot, so a
        temporary device swap does not silently destroy mappings.
        ``DEFAULT_BUTTON_ROWS`` are always preserved regardless.
        Also records the count so the Remove affordance only shows on
        bnums the connected device does not expose.
        """
        if count <= 0:
            return
        count = min(count, MAX_BUTTONS)
        self._device_button_count = count
        # Suppress per-edit emit and fire once at the end.
        was_building = self._building
        self._building = True
        try:
            changed = False
            for bnum in range(count):
                if bnum not in self.btn_rows:
                    self._add_button_row(bnum, "none")
                    changed = True
            for bnum in sorted(self.btn_rows, reverse=True):
                if bnum < count or bnum in DEFAULT_BUTTON_ROWS:
                    continue
                row = self.btn_rows[bnum]
                if BTN_ACTIONS[row["combo"].currentIndex()] != "none":
                    continue
                self._remove_button_row(bnum)
                changed = True
        finally:
            self._building = was_building
        # Count changed → revisit every row so orphan markers stay
        # accurate after device hot-plug.
        self._update_remove_visibility()
        if changed:
            self._emit_changed()

    def on_button_press(self, bnum, pressed):
        """Called from settings_window when a SpaceMouse button event arrives.

        Pressed events on unknown buttons add a new row. Both press and
        release events refresh the visual highlight on the matching combo.
        """
        if not pressed or not (0 <= bnum < MAX_BUTTONS):
            return
        was_new = bnum not in self.btn_rows
        row = self._add_button_row(bnum)
        if row is None:
            return
        if was_new:
            self._emit_changed()
        self._flash_row(bnum)

    def _flash_row(self, bnum):
        row = self.btn_rows.get(bnum)
        if row is None:
            return
        combo = row["combo"]
        combo.setStyleSheet(
            f"QComboBox {{ border: 2px solid {COLOR_ACCENT}; border-radius: 4px; }}"
        )
        prev = self._highlight_timers.pop(bnum, None)
        if prev:
            prev.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda b=bnum: self._unflash_row(b))
        timer.start(700)
        self._highlight_timers[bnum] = timer

    def _unflash_row(self, bnum):
        self._highlight_timers.pop(bnum, None)
        row = self.btn_rows.get(bnum)
        if row is not None:
            row["combo"].setStyleSheet("")

    def _on_manage_apps(self):
        dlg = AddAppDialog(self.wm_class_chips.get_values(), parent=self)
        if dlg.exec():
            new_list = dlg.result_list()
            if new_list != self.wm_class_chips.get_values():
                self.wm_class_chips.set_values(new_list)
                # ChipList.set_values doesn't auto-emit; nudge the cascade.
                self.changed.emit()

    def _load_state(self):
        """Populate widgets from the ``default`` profile + populate the 3D
        APPS chip list from the ``passthrough_apps`` profile's match list.

        Legacy configs (pre-rename) used the bare name ``passthrough`` for
        this same profile; fall back to it so old config.json files keep
        working until the next save migrates them onto the new key.
        """
        profiles = self._config.get("profiles", {})
        default = profiles.get("default", {})
        passthrough = profiles.get("passthrough_apps") or profiles.get("passthrough", {})

        pt_wm = passthrough.get("match_wm_class", [])
        self.wm_class_chips.set_values(pt_wm if isinstance(pt_wm, list) else [])

        self.sensitivity_s.setValue(int(default.get("sensitivity", 1.0) * 10))
        self.scroll_speed_s.setValue(int(default.get("scroll_speed", 3.0) * 10))
        self.zoom_speed_s.setValue(int(default.get("zoom_speed", 2.0) * 10))
        self.scroll_exp_s.setValue(int(default.get("scroll_exponent", 2.0) * 10))
        self.deadzone_s.setValue(default.get("deadzone", 0))

        amap = default.get("axis_mapping", {})
        for i, key in enumerate(AXIS_KEYS):
            action = amap.get(key, "none")
            idx = AXIS_ACTIONS.index(action) if action in AXIS_ACTIONS else 0
            self.axes_card.action_combos[i].setCurrentIndex(idx)

        adz = default.get("axis_deadzone", {})
        for i, key in enumerate(AXIS_KEYS):
            self.axes_card.deadzone_sliders[i].setValue(adz.get(key, 0))

        ainv = default.get("axis_invert", {})
        for i, key in enumerate(AXIS_KEYS):
            self.axes_card.invert_toggles[i].setChecked(bool(ainv.get(key, False)))

        bmap = default.get("button_mapping", {})
        self._reset_button_rows()
        configured = set()
        for key in bmap:
            try:
                bnum = int(key)
            except (TypeError, ValueError):
                continue
            if 0 <= bnum < MAX_BUTTONS:
                configured.add(bnum)
        for bnum in sorted(configured | set(DEFAULT_BUTTON_ROWS)):
            self._add_button_row(bnum, bmap.get(str(bnum), "none"))

        self.dswitch_thresh_s.setValue(default.get("desktop_switch_threshold", 200))
        self.dswitch_cool_s.setValue(default.get("desktop_switch_cooldown_ms", 500))

    def _collect_default_profile(self):
        """Return the desktop-settings widget state as a default profile dict."""
        data = {}
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

        data["axis_invert"] = {}
        for i, key in enumerate(AXIS_KEYS):
            data["axis_invert"][key] = self.axes_card.invert_toggles[i].isChecked()

        data["button_mapping"] = {}
        for bnum in sorted(self.btn_rows):
            row = self.btn_rows[bnum]
            data["button_mapping"][str(bnum)] = BTN_ACTIONS[row["combo"].currentIndex()]

        data["desktop_switch_threshold"] = self.dswitch_thresh_s.value()
        data["desktop_switch_cooldown_ms"] = self.dswitch_cool_s.value()
        return data

    def get_all_config(self):
        """Return full daemon config dict with default + passthrough_apps updated.

        Other profiles a power user may have added directly in config.json
        are preserved as-is. ``passthrough_apps`` is dropped when the chip
        list is empty so an unused profile doesn't sit around in the file.
        Any legacy ``passthrough`` key (pre-rename) is dropped on save so
        both names never coexist on disk. The rebuild only keeps
        ``match_wm_class`` — any custom deadzone/sensitivity/axis fields a
        user hand-edited into a legacy passthrough profile are intentionally
        discarded, since passthrough profiles are all-none by definition and
        those fields are ignored by the daemon anyway.
        """
        profiles = self._config.setdefault("profiles", {})
        profiles["default"] = self._collect_default_profile()
        wm = self.wm_class_chips.get_values()
        if wm:
            profiles["passthrough_apps"] = {
                "match_wm_class": wm,
                "axis_mapping": dict.fromkeys(AXIS_KEYS, "none"),
                "button_mapping": {"0": "none", "1": "none"},
            }
        else:
            profiles.pop("passthrough_apps", None)
        profiles.pop("passthrough", None)
        return self._config

    def update_config(self, config):
        """Replace config data and refresh widgets from it."""
        self._config = config
        self._building = True
        self._load_state()
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
                f"color: {COLOR_WARN}; background-color: {COLOR_BG_WARN}; "
                "border-radius: 6px; padding: 8px;"
            )
            warn.setWordWrap(True)
            cl.addWidget(warn)

        self.running_warn = QLabel(
            "FreeCAD is running \u2014 it overwrites user.cfg on exit.\n"
            "Close FreeCAD before applying changes."
        )
        self.running_warn.setStyleSheet(
            f"color: {COLOR_ERROR}; background-color: {COLOR_BG_ERROR}; "
            "border-radius: 6px; padding: 8px;"
        )
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
            "TX \u2014 PanLR",
            "TY \u2014 PanUD",
            "TZ \u2014 Zoom",
            "RX \u2014 Tilt",
            "RY \u2014 Spin",
            "RZ \u2014 Roll",
        ]
        self.axes_card = AxesCard(
            fc_axis_labels,
            show_action=False,
            show_enable=True,
            show_invert=True,
            show_deadzone=True,
            deadzone_enabled=True,
            deadzone_max=200,
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
            combo = NoScrollComboBox()
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

        self.fc_nav_combo = NoScrollComboBox()
        self.fc_nav_combo.addItems(FREECAD_NAV_LABELS)
        self.fc_nav_combo.currentIndexChanged.connect(self._emit_changed)
        fl.addRow("Navigation Style:", self.fc_nav_combo)

        self.fc_orbit_combo = NoScrollComboBox()
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

        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("Install Startup Script")
        self.install_btn.clicked.connect(self._install_script)
        btn_row.addWidget(self.install_btn)
        self.uninstall_btn = QPushButton("Uninstall")
        self.uninstall_btn.clicked.connect(self._uninstall_script)
        btn_row.addWidget(self.uninstall_btn)
        cl.addLayout(btn_row)
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
            "TX \u2014 Pan X",
            "TY \u2014 Pan Y",
            "TZ \u2014 Pan Z",
            "RX \u2014 Rot X",
            "RY \u2014 Rot Y",
            "RZ \u2014 Rot Z",
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
        lock_warn = QLabel("Lock Horizon blocks the RX/pitch axis \u2014 keep OFF for full 6DOF")
        lock_warn.setStyleSheet(
            f"color: {COLOR_WARN}; font-size: 11px; background: transparent; padding: 0 12px;"
        )
        lock_warn.setWordWrap(True)
        layout.addWidget(lock_warn)

        # ── Card 4: BUTTONS ──
        card, cl = make_card("BUTTONS")
        info = QLabel("Blender buttons are configured via Blender's Keymap Editor")
        info.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-style: italic; background: transparent;")
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
        st = self._bc.script_status()
        # Uninstall only makes sense when at least one copy is actually
        # on disk.
        self.uninstall_btn.setVisible(st["any_installed"])

        if not st["any_installed"]:
            target_versions = ", ".join(v["version"] for v in st["versions"])
            self.script_status.setText(
                "Startup script not installed. Blender won't pick up settings until you install it.\n"
                f"Install target: Blender {target_versions}"
            )
            self.script_status.setStyleSheet(f"color: {COLOR_WARN}; background: transparent;")
            self.install_btn.setText("Install Startup Script")
            return

        from datetime import datetime

        installed = [v for v in st["versions"] if v["installed"]]
        missing = [v for v in st["versions"] if not v["installed"]]
        outdated = [v for v in installed if not v["up_to_date"]]

        def _fmt(v):
            when = datetime.fromtimestamp(v["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
            tag = "outdated" if not v["up_to_date"] else "up to date"
            return f"  Blender {v['version']}: {tag}  ({when})\n    {v['path']}"

        lines = [_fmt(v) for v in installed]
        if missing:
            lines.append("Missing in: " + ", ".join(f"Blender {v['version']}" for v in missing))

        body = "\n".join(lines)
        if outdated or missing:
            # Yellow-orange: partial install or stale copy. "Update"
            # makes the action sound non-destructive on the up-to-date
            # versions (it's a re-copy, but with the exact same bytes).
            self.script_status.setText(f"Startup script status:\n{body}")
            self.script_status.setStyleSheet(f"color: {COLOR_WARN_ALT}; background: transparent;")
            self.install_btn.setText("Update Startup Script")
        else:
            self.script_status.setText(f"Startup script installed and up to date.\n{body}")
            self.script_status.setStyleSheet(f"color: {COLOR_OK}; background: transparent;")
            self.install_btn.setText("Reinstall Startup Script")

    def _install_script(self):
        written = self._bc.install_startup_script()
        if not written:
            QMessageBox.warning(
                self, "Error", "Could not find blender_spacemouse_sync.py next to this script."
            )
            return
        self._update_script_status()
        targets = "\n".join(f"  Blender {v}: {p}" for v, p in written)
        QMessageBox.information(
            self,
            "Installed",
            f"Script installed for {len(written)} Blender version(s):\n{targets}\n\n"
            "Restart Blender for the new version to take effect.",
        )

    def _uninstall_script(self):
        # Show the user exactly which copies will go away.
        st = self._bc.script_status()
        installed = [v for v in st["versions"] if v["installed"]]
        targets = "\n".join(f"  Blender {v['version']}: {v['path']}" for v in installed)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Uninstall Startup Script")
        msg.setText(
            f"Remove the startup script from {len(installed)} Blender version(s)?\n\n"
            f"{targets}\n\n"
            "Blender will fall back to its own NDOF defaults on the next start "
            "and stop picking up settings made here."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.button(QMessageBox.StandardButton.Yes).setText("Yes")
        msg.button(QMessageBox.StandardButton.No).setText("No")
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        removed = self._bc.uninstall_startup_script()
        self._update_script_status()
        if removed:
            removed_list = "\n".join(f"  Blender {v}: {p}" for v, p in removed)
            QMessageBox.information(
                self,
                "Uninstalled",
                f"Startup script removed from {len(removed)} Blender version(s):\n{removed_list}\n\n"
                "Restart Blender to drop the previously applied settings.",
            )
        else:
            QMessageBox.warning(self, "Nothing to remove", "The startup script was not present.")

    def _load_settings(self):
        s = self._bc.read()
        self.bl_sensitivity_s.setValue(int(s["ndof_sensitivity"] * 100))
        self.bl_orbit_s.setValue(int(s["ndof_orbit_sensitivity"] * 100))
        self.bl_deadzone_s.setValue(int(s["ndof_deadzone"] * 100))

        # Enable toggles: all enabled by default (Blender has no per-axis enable,
        # stored in our JSON for UI consistency)
        enable_keys = [
            "ndof_panx_enable",
            "ndof_pany_enable",
            "ndof_panz_enable",
            "ndof_rotx_enable",
            "ndof_roty_enable",
            "ndof_rotz_enable",
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
