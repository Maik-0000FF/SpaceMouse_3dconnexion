"""Application entrypoint — tray, signal handling, profile coordination."""

import atexit
import json
import os
import signal
import subprocess
import sys
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .constants import CONFIG_DIR, CONFIG_PATH, DARK_THEME
from .helpers import (
    create_tray_icon_pixmap,
    send_daemon_cmd,
    set_spacemouse_led,
    wait_for_daemon_socket,
)
from .monitors import SpnavReader, make_window_monitor
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
        pen = QPen(QColor(0xA6, 0xAD, 0xC8))
        pen.setWidthF(1.8)
        p.setPen(pen)
        p.drawLine(1, 2, 6, 6)
        p.drawLine(6, 6, 11, 2)
        p.end()
        pixmap.save(self._arrow_path)

        theme = DARK_THEME.replace(
            "image: none;\n    width: 0;\n    height: 0;",
            f"image: url({self._arrow_path});\n    width: 12px;\n    height: 8px;",
        )
        self.app.setStyleSheet(theme)

        self.config = self._load_config()
        self._cleaned_up = False

        settings = self.config.get("settings", {})
        self._autostart = settings.get("autostart", True)
        self._bg_test_enabled = settings.get("bg_test", False)
        self._bg_test_proc = None
        self._paused = settings.get("disabled", False)

        self.settings_window = SettingsWindow(
            self.config,
            self._on_save,
            on_bg_test_change=self._on_bg_test_change,
            on_actions_change=self._on_actions_change,
        )
        self.settings_window.sync_settings(self._settings_snapshot())

        # System tray
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon(create_tray_icon_pixmap("SM")))
        self.tray.setToolTip("SpaceMouse: default")
        self.tray.activated.connect(self._on_tray_activated)

        self.window_monitor = None

        # Build the tray menu ONCE and keep references alive on self. Two
        # reasons this can't be a local:
        #   * QSystemTrayIcon.setContextMenu does not take Qt ownership, so
        #     the menu would be garbage-collected the moment __init__ returns.
        #     KDE survives this by caching the DBusMenu, GNOME/AppIndicator
        #     does not — first action fires, every later one silently fails.
        #   * Recreating the menu on every state change re-exports the
        #     DBusMenu path; AppIndicator does not re-attach to the new path,
        #     so menu interactions stop working entirely on GNOME.
        # Instead, build once and flip action text in _update_tray_menu().
        self._tray_menu = QMenu()
        self._toggle_action = QAction("Disable", self._tray_menu)
        self._toggle_action.triggered.connect(self._toggle_pause)
        self._tray_menu.addAction(self._toggle_action)

        self._settings_action = QAction("Settings...", self._tray_menu)
        self._settings_action.triggered.connect(self._show_settings)
        self._tray_menu.addAction(self._settings_action)

        self._tray_menu.addSeparator()

        self._quit_action = QAction("Quit", self._tray_menu)
        self._quit_action.triggered.connect(self._quit)
        self._tray_menu.addAction(self._quit_action)

        self._update_tray_menu()
        self.tray.setContextMenu(self._tray_menu)
        self.tray.show()

        # SpaceMouse reader (starts suspended — only active when GUI is visible).
        # Reads via libspnav→spacenavd; the C daemon reads /dev/input directly,
        # so both can coexist without conflict.
        self.spnav_reader = SpnavReader()
        self.spnav_reader.set_suspended(True)
        self.settings_window.set_spnav_reader(self.spnav_reader)
        self.spnav_reader.start()

        # Ensure the daemon is running. Quit from the tray stops the service,
        # so a fresh GUI launch needs to bring it back — otherwise PROFILE
        # commands below would hit an empty socket. `systemctl start` is a
        # no-op if the unit is already active. Wait for the daemon to bind
        # its command socket before sending PROFILE — without this the
        # disabled-state restore races the daemon's startup and silently
        # falls back to the daemon's default profile.
        subprocess.run(
            ["systemctl", "--user", "start", "spacemouse-desktop.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        wait_for_daemon_socket()

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

        # Optional second libspnav reader (spacemouse-test --live) while a
        # 3D app is focused. spacenavd's event-pacing behaves erratically
        # with a single client on some GNOME-Wayland setups, causing visible
        # stutter in Blender/FreeCAD; a second reader keeps the pipeline
        # warm and makes the navigation smooth. Off by default, opt-in via
        # the sidebar toggle.
        self._apply_bg_test_state()

        signal.signal(signal.SIGTERM, self._sigterm_handler)
        signal.signal(signal.SIGINT, self._sigterm_handler)
        atexit.register(self._cleanup)

        # Tray may be invisible on GNOME (no StatusNotifierWatcher unless the
        # AppIndicator extension is installed). If so, show a one-shot install
        # hint and open the settings window so the app stays reachable.
        self._check_tray_available()

    def _check_tray_available(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            return

        settings = self.config.setdefault("settings", {})
        if not settings.get("tray_warning_shown", False):
            QMessageBox.warning(
                None,
                "SpaceMouse Control — system tray not available",
                "Your desktop does not expose a system tray, so the "
                "SpaceMouse Control icon will not be visible.\n\n"
                "On GNOME, install the 'AppIndicator and KStatusNotifierItem "
                "Support' extension, then log out and back in:\n"
                "  • Fedora:  sudo dnf install gnome-shell-extension-appindicator\n"
                "  • Debian/Ubuntu:  sudo apt install gnome-shell-extension-appindicator3\n"
                "  • Arch (AUR):  yay -S gnome-shell-extension-appindicator\n"
                "  • Manual:  https://extensions.gnome.org/extension/615/appindicator-support/\n\n"
                "Until then the settings window will open on every launch so "
                "the app stays reachable. The background daemon works "
                "regardless.",
            )
            settings["tray_warning_shown"] = True
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.config, f, indent=2)

        self._show_settings()

    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "profiles": {
                "default": {
                    "deadzone": 15,
                    "scroll_speed": 3.0,
                    "scroll_exponent": 2.0,
                    "zoom_speed": 2.0,
                    "sensitivity": 1.0,
                    "desktop_switch_threshold": 200,
                    "desktop_switch_cooldown_ms": 500,
                    "axis_mapping": {
                        "tx": "scroll_h",
                        "ty": "scroll_v",
                        "tz": "zoom",
                        "rx": "none",
                        "ry": "desktop_switch",
                        "rz": "none",
                    },
                    "button_mapping": {"0": "overview", "1": "show_desktop"},
                    "invert_scroll_x": False,
                    "invert_scroll_y": False,
                }
            }
        }

    def _cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.spnav_reader.stop()
        self._stop_window_monitor()
        self._stop_bg_test_proc()

    def _on_bg_test_change(self, enabled):
        # Persist the sidebar "Smooth 3D nav" toggle to config.json without
        # touching the profiles dict (Desktop page owns those). Skipped if
        # the value did not actually flip — avoids redundant disk writes.
        if enabled == self._bg_test_enabled:
            return
        self._bg_test_enabled = enabled
        self.config.setdefault("settings", {})["bg_test"] = enabled
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)
        self._apply_bg_test_state()

    def _apply_bg_test_state(self):
        # On some GNOME-Wayland setups spacenavd's event pacing degrades when
        # only one libspnav client is connected — the lone client (Blender or
        # FreeCAD) gets choppy SpaceMouse input. A second silent reader on the
        # same socket keeps the pipeline warm and the navigation smooth. The
        # workaround is opt-in (sidebar toggle) because not every system
        # exhibits the problem.
        should_run = (
            self._bg_test_enabled
            and not self._gui_has_focus
            and self._saved_profile in ("blender", "freecad")
        )
        if should_run and self._bg_test_proc is None:
            self._start_bg_test_proc()
        elif not should_run and self._bg_test_proc is not None:
            self._stop_bg_test_proc()

    def _start_bg_test_proc(self):
        # spacemouse-test --live is just a libspnav reader that prints axis
        # values to stdout. We discard the output and only need the side
        # effect of having a second client attached to spacenavd. Falling
        # back silently if the binary isn't on PATH — the toggle is best-
        # effort, no need to scare the user with a popup.
        try:
            self._bg_test_proc = subprocess.Popen(
                ["spacemouse-test", "--live"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, FileNotFoundError):
            self._bg_test_proc = None

    def _stop_bg_test_proc(self):
        if self._bg_test_proc is None:
            return
        proc = self._bg_test_proc
        self._bg_test_proc = None
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                pass
        except (OSError, ProcessLookupError):
            pass

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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            subprocess.run(
                ["systemctl", "--user", action, "spacemouse-desktop.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )

        if self.window_monitor:
            profiles = config.get("profiles", {})
            self.window_monitor.update_profiles(profiles)

        self._update_tray_menu()

    def _update_tray_menu(self):
        """Refresh tray-action labels in place. Never recreate the QMenu — see
        the comment in __init__ on why that breaks AppIndicator on GNOME."""
        self._toggle_action.setText("Enable" if self._paused else "Disable")

    def _start_window_monitor(self):
        profiles = self.config.get("profiles", {"default": self.config})
        self.window_monitor = make_window_monitor(profiles)
        if self.window_monitor is None:
            # No portable backend for this session (GNOME-Wayland, Sway,
            # Hyprland today). Daemon stays on its default profile;
            # profile switching via the tray menu still works.
            return
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
        return all(v == "none" for v in am.values()) and all(v == "none" for v in bm.values())

    def _save_disabled_state(self):
        """Persist disabled state to config.json."""
        self.config.setdefault("settings", {})["disabled"] = self._paused
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)

    def _settings_snapshot(self):
        # Single source of truth for the values the SettingsWindow mirrors:
        # autostart and the experimental bg_test toggle live on app side
        # and need to be pushed back into the UI whenever they change.
        return {
            "autostart": self._autostart,
            "bg_test": self._bg_test_enabled,
            "disabled": self._paused,
        }

    def _toggle_pause(self):
        self._set_paused(not self._paused)

    def _on_actions_change(self, enabled):
        # Sidebar "Actions" toggle: ON means desktop actions enabled
        # (i.e. _paused = False), OFF means paused.
        self._set_paused(not enabled)

    def _set_paused(self, paused):
        if paused == self._paused:
            return
        self._paused = paused
        if paused:
            # Disable: daemon to passthrough (still drains events, but no actions).
            # 3D apps (Blender/FreeCAD) keep working via their own libspnav path.
            send_daemon_cmd("PROFILE _passthrough")
            set_spacemouse_led(False)
            self.tray.setToolTip("SpaceMouse: DISABLED")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("||")))
        else:
            # Enable: restore daemon to whatever the current focus dictates.
            target = "_passthrough" if self._gui_has_focus else self._saved_profile
            send_daemon_cmd(f"PROFILE {target}")
            set_spacemouse_led(True)
            self.tray.setToolTip(f"SpaceMouse: {self._saved_profile}")
            self.tray.setIcon(QIcon(create_tray_icon_pixmap("SM")))
        self._save_disabled_state()
        self._update_tray_menu()
        # Keep the sidebar toggle in sync when state was changed from the
        # tray menu. sync_settings → setChecked re-emits stateChanged, but
        # _set_paused early-returns on no-change so no loop.
        self.settings_window.sync_settings(self._settings_snapshot())

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_settings()

    def _show_settings(self):
        self.settings_window.sync_settings(self._settings_snapshot())
        # Clear any minimised state — on Wayland the window can come back
        # invisible after a previous close+show cycle if WindowMinimized was
        # left set, since the compositor decides where to put it.
        state = self.settings_window.windowState()
        if state & Qt.WindowState.WindowMinimized:
            self.settings_window.setWindowState(state & ~Qt.WindowState.WindowMinimized)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()
        # Wayland blocks programmatic focus; request activation via the
        # window handle so xdg-activation kicks in where supported.
        handle = self.settings_window.windowHandle()
        if handle is not None:
            handle.requestActivate()

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
                f"SpaceMouse: DISABLED ({wm_class})" if is_3d_app else "SpaceMouse: DISABLED"
            )
        else:
            send_daemon_cmd(f"PROFILE {profile_name}")
            set_spacemouse_led(True)
            self.tray.setToolTip(f"SpaceMouse: {profile_name} ({wm_class})")

        self._apply_bg_test_state()

    def _on_gui_shown(self):
        """GUI window shown — take spnav for live preview, daemon to passthrough."""
        self._gui_has_focus = True
        send_daemon_cmd("PROFILE _passthrough")
        self.spnav_reader.set_suspended(False)
        self.settings_window._status_timer.start(3000)
        self._apply_bg_test_state()

    def _on_gui_hidden(self):
        """GUI window hidden — release spnav, restore daemon profile if enabled."""
        self._gui_has_focus = False
        self.spnav_reader.set_suspended(True)
        self.settings_window._status_timer.stop()
        if not self._paused:
            send_daemon_cmd(f"PROFILE {self._saved_profile}")
        self._apply_bg_test_state()

    def _on_gui_focused(self):
        """GUI got activation — take spnav for live preview, daemon to passthrough."""
        self._gui_has_focus = True
        send_daemon_cmd("PROFILE _passthrough")
        self.spnav_reader.set_suspended(False)
        self._apply_bg_test_state()

    def _on_gui_unfocused(self):
        """GUI lost activation — restore the saved profile so the daemon resumes
        normal behavior. Required even when _on_window_changed also fires: that
        callback skips the daemon switch when the new window resolves to the
        same profile name as before, leaving the daemon stuck on _passthrough."""
        self._gui_has_focus = False
        if not self._paused:
            send_daemon_cmd(f"PROFILE {self._saved_profile}")
        self._apply_bg_test_state()

    def _quit(self):
        self._cleanup()
        set_spacemouse_led(False)
        subprocess.run(
            ["systemctl", "--user", "stop", "spacemouse-desktop.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        self.tray.hide()
        self.app.quit()

    def run(self):
        return self.app.exec()


def main():
    app = SpaceMouseApp()
    sys.exit(app.run())
