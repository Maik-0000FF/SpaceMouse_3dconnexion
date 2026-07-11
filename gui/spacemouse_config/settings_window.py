"""SettingsWindow — main settings UI with sidebar + apply/save dialog."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .constants import COLOR_ACCENT, COLOR_TEXT_MUTED
from .helpers import (
    create_tray_icon_pixmap,
    make_save_discard_cancel_box,
    query_device_info,
    send_daemon_cmd,
)
from .pages import BlenderPage, DesktopPage, FreeCADPage
from .widgets import LivePreviewBar, make_toggle


class SettingsWindow(QMainWindow):
    """Main settings window with sidebar navigation."""

    window_shown = Signal()
    window_hidden = Signal()
    window_focused = Signal()
    window_unfocused = Signal()

    def __init__(
        self,
        config_data,
        on_save_callback,
        on_bg_test_change=None,
        on_actions_change=None,
    ):
        super().__init__()
        self.on_save = on_save_callback
        self.on_bg_test_change = on_bg_test_change
        self.on_actions_change = on_actions_change
        self.setWindowTitle("SpaceMouse Control")
        self.setWindowIcon(QIcon(create_tray_icon_pixmap("SM")))
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
        title.setStyleSheet(
            f"color: {COLOR_ACCENT}; font-size: 15px; font-weight: bold; padding: 4px;"
        )
        sb_layout.addWidget(title)
        subtitle = QLabel("Control")
        subtitle.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 12px; padding: 0 4px 12px 4px;"
        )
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

        # Mirror of the tray Enable/Disable action. Toggle ON = SpaceMouse
        # desktop actions active (scroll, zoom, workspace switching). OFF
        # = daemon stays on _passthrough so 3D apps still receive events
        # but no desktop input is generated. Immediate-effect — clicking
        # flips the daemon state without needing Apply.
        self.actions_cb = make_toggle("Actions")
        self.actions_cb.setToolTip(
            "Enable or disable SpaceMouse desktop actions (scroll, zoom, "
            "workspace switching). Mirrors the tray Enable/Disable menu "
            "item. 3D apps keep receiving events either way."
        )
        self.actions_cb.stateChanged.connect(
            lambda state: self.on_actions_change and self.on_actions_change(state == 1)
        )
        sb_layout.addWidget(self.actions_cb)

        # Workaround for spacenavd's single-client event-pacing on some
        # GNOME-Wayland setups: spawn a silent second libspnav reader
        # (spacemouse-test --live) while Blender or FreeCAD is focused.
        # Off by default; turn on if 3D navigation feels choppy with only
        # one app open and goes smooth as soon as a second client appears.
        # Immediate-effect — clicking flips the spawn without Apply.
        self.bg_test_cb = make_toggle("Smooth 3D nav")
        self.bg_test_cb.setToolTip(
            "Keep a second libspnav reader alive while Blender or FreeCAD "
            "is focused. Mitigates choppy SpaceMouse navigation caused by "
            "spacenavd's event pacing when only one libspnav client is "
            "connected (often seen on GNOME-Wayland). Off by default."
        )
        bg_cb = self.on_bg_test_change
        if bg_cb is not None:
            # Bind bg_cb as a default arg so Pyright keeps the narrowed
            # not-None type inside the lambda body.
            self.bg_test_cb.stateChanged.connect(lambda state, cb=bg_cb: cb(state == 1))
        sb_layout.addWidget(self.bg_test_cb)

        top.addWidget(sidebar)

        # Content stack
        self.stack = QStackedWidget()

        self.desktop_page = DesktopPage(config_data)
        # Desktop is fully live-apply: every change writes config.json and
        # triggers a daemon RELOAD. No Apply button, no dirty state.
        self.desktop_page.changed.connect(self._save_desktop)
        self.desktop_page.changed.connect(self._sync_deadzones)
        # Drag-time preview: redraw the red deadzone band in the live bar
        # while the slider moves, without writing to disk / RELOADing the
        # daemon. The save path is sliderReleased and runs separately.
        self.desktop_page.deadzone_s.valueChanged.connect(self._sync_deadzones)
        for s in self.desktop_page.axes_card.deadzone_sliders:
            s.valueChanged.connect(self._sync_deadzones)
        self.stack.addWidget(self.desktop_page)

        # FreeCAD / Blender keep the manual Apply flow: edits mark dirty,
        # Apply commits the page's settings to its backend (user.cfg / JSON).
        self.freecad_page = FreeCADPage()
        self.freecad_page.changed.connect(self._mark_dirty)
        self.freecad_page.changed.connect(self._sync_deadzones)
        self.freecad_page.unchanged.connect(self._mark_clean)
        self.stack.addWidget(self.freecad_page)

        self.blender_page = BlenderPage()
        self.blender_page.changed.connect(self._mark_dirty)
        self.blender_page.changed.connect(self._sync_deadzones)
        self.stack.addWidget(self.blender_page)

        # Content wrapper with padding
        content_wrapper = QWidget()
        cw_layout = QVBoxLayout(content_wrapper)
        cw_layout.setContentsMargins(16, 12, 16, 8)
        cw_layout.setSpacing(8)
        cw_layout.addWidget(self.stack, 1)

        # Apply button — visible only on FreeCAD/Blender pages.
        # Desktop is live-apply, so the button would be a no-op there.
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

        # Autostart is part of the daemon config — push it through the
        # same live-apply path as the rest of the Desktop page.
        self.autostart_cb.stateChanged.connect(self._save_desktop)

        # Select first page
        self._page_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)
        self._sync_deadzones()
        self._refresh_apply_button()

        # Status timer (stopped by default — started when window becomes visible)
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status)

        self._dirty = False
        self._last_device_key = None

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        self._sync_deadzones()
        self._refresh_apply_button()

    def _refresh_apply_button(self):
        """Apply only makes sense on FreeCAD (0=Desktop is live-apply)
        and Blender pages. Hide it on Desktop so it doesn't tease a
        no-op action."""
        self.apply_btn.setVisible(self.stack.currentIndex() != 0)

    def _mark_dirty(self):
        self._dirty = True
        self.setWindowTitle("SpaceMouse Control *")

    def _mark_clean(self):
        self._dirty = False
        self.setWindowTitle("SpaceMouse Control")

    def _save_desktop(self):
        """Persist desktop-page widget state + autostart on every change."""
        config = self.desktop_page.get_all_config()
        config.setdefault("settings", {})["autostart"] = self.autostart_cb.isChecked()
        self.on_save(config)

    def _sync_deadzones(self):
        """Push current page's deadzone values to the live preview bar."""
        idx = self.stack.currentIndex()
        if idx == 0:
            # Desktop: per-axis deadzone from AxesCard, fallback to global
            global_dz = self.desktop_page.deadzone_s.value()
            values = []
            for s in self.desktop_page.axes_card.deadzone_sliders:
                v = s.value()
                values.append(v if v > 0 else global_dz)
            self.live_bar.set_deadzones(values)
        elif idx == 1:
            # FreeCAD: per-axis deadzone from AxesCard
            values = [s.value() for s in self.freecad_page.axes_card.deadzone_sliders]
            self.live_bar.set_deadzones(values)
        elif idx == 2:
            # Blender: global deadzone only (no per-axis support)
            global_dz = self.blender_page.bl_deadzone_s.value()
            self.live_bar.set_deadzones([global_dz] * 6)

    def _apply(self):
        """Commit the FreeCAD or Blender page. Desktop is live-apply, so
        the Apply button is hidden there and this method is unreachable."""
        page_idx = self.stack.currentIndex()

        if page_idx == 1:
            if self.freecad_page.warn_if_running():
                # if FreeCAD is running, warn_if_running showed a warning. do nothing.
                return
            elif self.freecad_page.apply_settings():
                self._mark_clean()
                QMessageBox.information(
                    self,
                    "Applied",
                    "FreeCAD settings saved to user.cfg.\n"
                    "Restart FreeCAD for changes to take effect.",
                )
            else:
                QMessageBox.warning(self, "Error", "Could not write FreeCAD user.cfg.")

        elif page_idx == 2:
            self.blender_page.apply_settings()
            self._mark_clean()
            QMessageBox.information(
                self, "Applied", "Blender NDOF settings saved.\nRestart Blender to apply."
            )

    def _update_status(self):
        # Two synchronous daemon IPCs per tick (STATUS + DEVICE), both on
        # the Qt main thread with the 1 s socket timeout in send_daemon_cmd.
        # Acceptable at the current 2 s tick rate; revisit if the timer
        # rate goes up or more poll-style commands are added.
        resp = send_daemon_cmd("STATUS")
        self.live_bar.set_daemon_status(resp is not None)
        self.refresh_device_info()

    def refresh_device_info(self):
        """Pull DEVICE info from the daemon and apply it to GUI state.

        Cheap to call repeatedly: a change is detected via (vid, pid)
        so the desktop-page row pre-seeding fires once per hot-plug,
        not on every poll. Daemon-unreachable leaves the GUI as-is.
        """
        info = query_device_info()
        key = (info["vid"], info["pid"]) if info else None
        if key == self._last_device_key:
            return
        self._last_device_key = key
        if info is None:
            self.live_bar.set_device_name(None)
            return
        self.live_bar.set_device_name(info["name"])
        if info["button_count"] > 0:
            self.desktop_page.ensure_button_rows(info["button_count"])

    def set_spnav_reader(self, reader):
        reader.axes_updated.connect(self.live_bar.update_axes)
        reader.button_pressed.connect(self.live_bar.update_button)
        reader.button_pressed.connect(self.desktop_page.on_button_press)

    def set_profile_name(self, name):
        self.live_bar.set_profile(name)

    def update_config(self, config):
        self.desktop_page.update_config(config)

    def sync_settings(self, settings_state):
        # Block stateChanged so the programmatic setChecked() does not
        # cascade into _save_desktop → on_save before the host app has
        # finished its own construction. Paired with the
        # ``self.window_monitor = None`` pre-init in app.SpaceMouseApp
        # __init__ — that one guards the desktop_page.changed cascade
        # during SettingsWindow construction; this one guards the
        # sync_settings() call right after.
        for cb, value in (
            (self.autostart_cb, settings_state.get("autostart", True)),
            (self.bg_test_cb, settings_state.get("bg_test", False)),
        ):
            blocked = cb.blockSignals(True)
            cb.setChecked(value)
            cb.blockSignals(blocked)
        if "disabled" in settings_state:
            blocked = self.actions_cb.blockSignals(True)
            self.actions_cb.setChecked(not settings_state["disabled"])
            self.actions_cb.blockSignals(blocked)

    def showEvent(self, event):
        super().showEvent(event)
        self.window_shown.emit()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.window_hidden.emit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.ActivationChange:
            if self.isActiveWindow():
                self.window_focused.emit()
            else:
                self.window_unfocused.emit()

    def closeEvent(self, event):
        if self._dirty:
            msg = make_save_discard_cancel_box(
                self=self,
                windowTitle="Unsaved Changes",
                text="You have unsaved changes.",
                informativeText="Do you want to save before closing?",
            )
            result = msg.exec()
            if result == QMessageBox.StandardButton.Save:
                self._apply()
            elif result == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.ignore()
        self.hide()
