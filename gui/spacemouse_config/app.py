"""Application entrypoint — tray, signal handling, profile coordination."""

import atexit
import json
import os
import signal
import subprocess
import sys
import tempfile

from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .constants import CONFIG_DIR, CONFIG_PATH, DARK_THEME
from .helpers import create_tray_icon_pixmap, send_daemon_cmd, set_spacemouse_led
from .monitors import SpnavReader, WindowMonitor
from .settings_window import SettingsWindow


class SpaceMouseApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("SpaceMouse Control")

        # Create chevron arrow for combo boxes
        self._arrow_path = os.path.join(tempfile.gettempdir(), "spacemouse-combo-arrow.png")
        pixmap = QPixmap(12, 8)
        pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(0xa6, 0xad, 0xc8))
        pen.setWidthF(1.8)
        p.setPen(pen)
        p.drawLine(1, 2, 6, 6)
        p.drawLine(6, 6, 11, 2)
        p.end()
        pixmap.save(self._arrow_path)

        theme = DARK_THEME.replace(
            "image: none;\n    width: 0;\n    height: 0;",
            f"image: url({self._arrow_path});\n    width: 12px;\n    height: 8px;")
        self.app.setStyleSheet(theme)

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

        self._paused = settings.get("disabled", False)
        self.window_monitor = None

        menu = QMenu()
        self._rebuild_tray_menu(menu)
        self.tray.setContextMenu(menu)
        self.tray.show()

        # SpaceMouse reader (starts suspended — only active when GUI is visible).
        # Reads via libspnav→spacenavd; the C daemon reads /dev/input directly,
        # so both can coexist without conflict.
        self.spnav_reader = SpnavReader()
        self.spnav_reader.set_suspended(True)
        self.settings_window.set_spnav_reader(self.spnav_reader)
        self.spnav_reader.start()

        # Daemon runs as a long-lived systemd service. We control it via
        # PROFILE commands on its UNIX socket — never start or stop the process.
        if self._paused:
            send_daemon_cmd("PROFILE _passthrough")
            set_spacemouse_led(False)
            self.tray.setToolTip("SpaceMouse: DISABLED")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("||")))

        # Profile switching follows window focus and pause state:
        # - Disabled         → daemon stays on _passthrough regardless
        # - Desktop app focus → daemon switches to its matching profile (default)
        # - 3D app focus     → daemon switches to that app's passthrough profile
        # - GUI focus        → daemon switches to _passthrough (no actions while editing)
        self._saved_profile = "default"
        self._gui_has_focus = False
        self.settings_window.window_shown.connect(self._on_gui_shown)
        self.settings_window.window_hidden.connect(self._on_gui_hidden)
        self.settings_window.window_focused.connect(self._on_gui_focused)
        self.settings_window.window_unfocused.connect(self._on_gui_unfocused)

        # Window monitor (also needed when disabled for LED control)
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
        toggle_action = QAction(
            "Enable" if self._paused else "Disable", menu)
        toggle_action.triggered.connect(self._toggle_pause)
        menu.addAction(toggle_action)

        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self._show_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
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

    def _is_passthrough_profile(self, profile_name):
        """Check if a profile has all axes and buttons set to none (3D app passthrough)."""
        profiles = self.config.get("profiles", {})
        prof = profiles.get(profile_name, {})
        am = prof.get("axis_mapping", {})
        bm = prof.get("button_mapping", {})
        if not am:
            return False
        return (all(v == "none" for v in am.values()) and
                all(v == "none" for v in bm.values()))

    def _save_disabled_state(self):
        """Persist disabled state to config.json."""
        self.config.setdefault("settings", {})["disabled"] = self._paused
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)

    def _toggle_pause(self):
        if self._paused:
            # Enable: restore daemon to whatever the current focus dictates.
            self._paused = False
            target = "_passthrough" if self._gui_has_focus else self._saved_profile
            send_daemon_cmd(f"PROFILE {target}")
            set_spacemouse_led(True)
            self.tray.setToolTip(f"SpaceMouse: {self._saved_profile}")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("SM")))
        else:
            # Disable: daemon to passthrough (still drains events, but no actions).
            # 3D apps (Blender/FreeCAD) keep working via their own libspnav path.
            self._paused = True
            send_daemon_cmd("PROFILE _passthrough")
            set_spacemouse_led(False)
            self.tray.setToolTip("SpaceMouse: DISABLED")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("||")))
        self._save_disabled_state()
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
        self._saved_profile = profile_name
        self.settings_window.set_profile_name(profile_name)

        is_3d_app = self._is_passthrough_profile(profile_name)

        # GUI focus path is owned by _on_gui_focused — do not touch the daemon here
        if self._gui_has_focus:
            return

        # Live preview stays active while the window is visible (suspension is
        # tied to visibility, not focus) so the user can test actions and watch
        # the bars update at the same time.

        if self._paused:
            # Disabled: daemon stays on _passthrough; just update LED + tooltip
            set_spacemouse_led(is_3d_app)
            self.tray.setToolTip(
                f"SpaceMouse: DISABLED ({wm_class})" if is_3d_app
                else "SpaceMouse: DISABLED")
        else:
            send_daemon_cmd(f"PROFILE {profile_name}")
            set_spacemouse_led(True)
            self.tray.setToolTip(f"SpaceMouse: {profile_name} ({wm_class})")

    def _on_gui_shown(self):
        """GUI window shown — take spnav for live preview, daemon to passthrough."""
        self._gui_has_focus = True
        send_daemon_cmd("PROFILE _passthrough")
        self.spnav_reader.set_suspended(False)
        self.settings_window._status_timer.start(3000)

    def _on_gui_hidden(self):
        """GUI window hidden — release spnav, restore daemon profile if enabled."""
        self._gui_has_focus = False
        self.spnav_reader.set_suspended(True)
        self.settings_window._status_timer.stop()
        if not self._paused:
            send_daemon_cmd(f"PROFILE {self._saved_profile}")

    def _on_gui_focused(self):
        """GUI got activation — take spnav for live preview, daemon to passthrough."""
        self._gui_has_focus = True
        send_daemon_cmd("PROFILE _passthrough")
        self.spnav_reader.set_suspended(False)

    def _on_gui_unfocused(self):
        """GUI lost activation — restore the saved profile so the daemon resumes
        normal behavior. Required even when _on_window_changed also fires: that
        callback skips the daemon switch when the new window resolves to the
        same profile name as before, leaving the daemon stuck on _passthrough."""
        self._gui_has_focus = False
        if not self._paused:
            send_daemon_cmd(f"PROFILE {self._saved_profile}")

    def _quit(self):
        self._cleanup()
        self.tray.hide()
        self.app.quit()

    def run(self):
        return self.app.exec()




def main():
    app = SpaceMouseApp()
    sys.exit(app.run())
