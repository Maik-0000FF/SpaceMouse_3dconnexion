# SpaceMouse Linux Control

[![CI](https://github.com/Maik-0000FF/SpaceMouse_3dconnexion/actions/workflows/ci.yml/badge.svg)](https://github.com/Maik-0000FF/SpaceMouse_3dconnexion/actions/workflows/ci.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
![version](https://img.shields.io/badge/version-0.1.0-blue)

> **Under active development.** Contributions and feedback are welcome.

Userspace control daemon and GUI for 3Dconnexion SpaceMouse devices on Linux. Sits on top of the existing driver stack (Linux evdev + spacenavd + libspnav) and turns 6DOF input into desktop actions: tilt to scroll, push/pull to zoom, twist to switch virtual desktops. Blender and FreeCAD continue to use their native 3D navigation — this project does not interfere with that path.

The current version (`0.1.0`) is reported by `spacemouse-desktop --version`, `spacemouse-test --version` and `spacemouse_config.__version__`.

## What You Need

- **3Dconnexion SpaceMouse** connected via USB
- **A supported distribution.** Build, packaging and the install script are continuously verified in CI on:

  | Distribution | Notes |
  |---|---|
  | **Arch Linux** (incl. EndeavourOS, Manjaro) | `libspnav` and `pyside6` from `extra`; `spacenavd` from the AUR — needs `yay` or `paru` ([install yay](https://github.com/Jguer/yay#installation)) |
  | **Fedora** (latest) | everything from the official repos (no RPM Fusion needed) |
  | **Debian 13 (trixie)** | everything from apt `main` |
  | **Debian 12 (bookworm)** / **Ubuntu 24.04 LTS** / **Ubuntu 24.10** | works, but PySide6 isn't in apt — the installer falls back to a pip venv automatically. (`python3-pyside6.qtwidgets` first lands in Ubuntu 25.10.) |
  | **openSUSE Tumbleweed / Leap** | everything from the official repos |

- **A desktop environment.** **KDE Plasma (Wayland)** is the primary target and the only one where the full feature set works. The control daemon itself is desktop-agnostic — see the table below.

### Feature support per desktop

The daemon and GUI both fall back gracefully when a backend isn't available, so nothing crashes on other desktops; the affected features just become no-ops.

| Feature | KDE Plasma | GNOME (X11) | GNOME (Wayland) | XFCE 4.18+ | Sway | Hyprland | COSMIC |
|---|---|---|---|---|---|---|---|
| Scroll, zoom (tilt + push/pull) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Blender / FreeCAD native 3D navigation | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| GUI with system-tray icon | ✓ | ⚠ via [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/) | ⚠ via [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/) | ✓ | ✓ via swaybar | ⚠ needs waybar / eww | ✓ via COSMIC panel applet |
| Manual profile switching from the GUI | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Auto profile switch when Blender / FreeCAD is focused | ✓ KWin script | ✓ xprop | ✓ via bundled focus-bridge extension | ✓ xprop | ✓ swaymsg | ✓ socket2 | ✗ no portable API |
| Twist → virtual desktop switch | ✓ KWin D-Bus | ✓ key combo | ✓ key combo | ✓ key combo | ✓ swaymsg | ✓ hyprctl | ✓ key combo |
| Left btn → Overview / Right btn → Show Desktop | ✓ KGlobalAccel | ✓ key combo | ✓ key combo | ✓ key combo | ✓ key combo | ✓ key combo | ✓ key combo |

**GNOME-Wayland note:** auto profile switching needs a Shell extension because GNOME exposes no portable window-listing protocol and `org.gnome.Shell.Eval` has been policy-disabled since GNOME 41. The installer ships and enables a small bundled extension (`spacemouse-focus@maik-0000ff`, source under [`gnome-extension/`](gnome-extension/)) that publishes the focused window's `wm_class` on the session bus. The GUI polls it every 400 ms and switches profiles when Blender or FreeCAD gains focus. **Log out and back in once after install** so GNOME-Wayland loads the new extension — Mutter cannot live-load extensions on Wayland for security reasons. The third-party [Window Calls](https://extensions.gnome.org/extension/4974/window-calls/) extension is also recognised as a fallback for users who already had it installed.

> The extension's `shell-version` field in `gnome-extension/spacemouse-focus@maik-0000ff/metadata.json` currently lists GNOME 45–50. When a new major GNOME release ships, append its version number to that array, otherwise GNOME Shell refuses to load the extension.

## Installation

```bash
git clone https://github.com/Maik-0000FF/SpaceMouse_3dconnexion.git
cd SpaceMouse_3dconnexion
./install.sh
```

The installer takes care of everything: installing packages, setting up permissions, compiling the daemon and tools, and starting the background services. You'll be asked for your password when it needs administrator access.

After installation, **plug in your SpaceMouse** (or unplug and replug it) and it's ready to use.

## How It Works

Once installed, the SpaceMouse works on your desktop like this:

- **Tilt left/right** → horizontal scroll
- **Tilt forward/back** → vertical scroll
- **Push down / pull up** → zoom (Ctrl+scroll)
- **Twist left/right** → switch virtual desktops
- **Left button** → KDE Overview
- **Right button** → Show Desktop

When you switch to **Blender** or **FreeCAD**, the desktop daemon steps aside automatically and the app's native 3D navigation takes over — no manual switching needed.

A **system tray icon** appears in your taskbar. Click it to open **SpaceMouse Control** — a settings app with three pages:

- **Desktop** — sensitivity, axis mapping, deadzone, button actions
- **FreeCAD** — SpaceMouse sensitivity, axis enable/invert, per-axis deadzone, navigation style
- **Blender** — NDOF sensitivity, deadzone, axis inversion, Lock Horizon toggle

| Desktop | FreeCAD | Blender |
|---------|---------|---------|
| ![Desktop](docs/screenshot-desktop.png) | ![FreeCAD](docs/screenshot-freecad.png) | ![Blender](docs/screenshot-blender.png) |

A live preview bar at the bottom shows real-time axis movement and button state. While the settings window is focused, desktop actions are automatically disabled so the SpaceMouse doesn't interfere while you configure it.

FreeCAD and Blender connect directly to spacenavd — they don't need the GUI or daemon running. You can close SpaceMouse Control completely and 3D navigation keeps working. Settings are written to each app's config file and persist across restarts.

## Blender

Blender works out of the box — no extra setup needed.

To configure Blender's SpaceMouse settings from the GUI:

1. Open **SpaceMouse Control** (tray icon) → **Blender** page
2. Adjust sensitivity, deadzone, axis inversion, etc.
3. Click **Apply**
4. Click **Install Startup Script** (first time only)
5. Restart Blender — settings are applied automatically on every launch

> **Tip:** If pitch/tilt doesn't work in Blender, make sure **Lock Horizon** is OFF (Blender enables it by default, which blocks the pitch axis).

## FreeCAD

To configure SpaceMouse inside FreeCAD, use the **FreeCAD** page in **SpaceMouse Control** (tray icon → Settings).

FreeCAD on Linux has had several SpaceMouse-related bugs. Most fixes are now in 1.1.1 and the 1.2 development branch, but jerky navigation (PR #28110) is still missing from the 1.1 series, and the reset-button bug (PR #28956) is open. If you're affected, see [`freecad/`](freecad/) for a patcher and Arch build that apply the fixes locally — completely separate from the control daemon here.

## Uninstall

```bash
./uninstall.sh
```

## Troubleshooting

### SpaceMouse not detected

1. Check that the device is plugged in: `lsusb | grep -i 3dconnexion`
2. Check that the system daemon is running: `systemctl status spacenavd`
3. Run the built-in diagnostic: `spacemouse-test --check`

If spacenavd isn't running:

```bash
sudo systemctl enable --now spacenavd
```

### FreeCAD SpaceMouse bugs (jerky navigation, 100% CPU, broken buttons)

These are upstream FreeCAD issues, unrelated to this project. See [`freecad/`](freecad/) for the patcher and patched Arch build.

### Tray icon not showing

```bash
systemctl --user restart spacemouse-config
```

On GNOME the tray icon will not appear at all unless the `AppIndicator and KStatusNotifierItem Support` extension is installed — GNOME has no built-in StatusNotifierWatcher. Install it and log out and back in:

```bash
sudo dnf install gnome-shell-extension-appindicator        # Fedora
sudo apt install gnome-shell-extension-appindicator3       # Debian/Ubuntu
yay -S gnome-shell-extension-appindicator                  # Arch (AUR)
sudo zypper install gnome-shell-extension-appindicator     # openSUSE
```

Manual install: https://extensions.gnome.org/extension/615/appindicator-support/

Until the extension is in place, the GUI auto-opens the settings window on every launch so the app stays reachable. The background daemon (profile switching, scroll/zoom) works regardless of whether the tray is visible.

### Buttons don't respond

Open the tray icon settings and check that button actions are set (default: Left = Overview, Right = Show Desktop).

## Advanced

### Diagnostics

```bash
spacemouse-test --check   # System checks (USB, spacenavd, uinput)
spacemouse-test --live    # Real-time axis and button monitor
spacemouse-test --led     # LED toggle test
```

### Supported devices

| Device | Status |
|--------|--------|
| SpaceNavigator (046d:c626) | Tested (fully working, including LED control) |
| SpaceMouse Compact | Should work (untested) |
| SpaceMouse Wireless | Should work (untested) |
| SpaceMouse Pro (Wireless) | Should work (untested) |
| SpaceMouse Enterprise | Should work (untested) |

Any 6DOF device supported by spacenavd should work. LED control currently only works for the SpaceNavigator — other models may use different HID report formats.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE) for the full text. The project links against `libdbus-1` (LGPL), `libspnav` (BSD-3-Clause) and `json-c` (MIT), all compatible with GPL-3.0 distribution.

## Trademarks

*SpaceMouse* and *3Dconnexion* are trademarks of 3Dconnexion GmbH. This project is **not affiliated with, endorsed by, or sponsored by 3Dconnexion**. The name is used only to identify the hardware this software supports.

## Acknowledgments

The actual SpaceMouse driver stack on Linux is the work of [John Tsiombikas](https://nuclear.mutantstargoat.com/) and the FreeSpacenav community — without it none of this would exist:

- [spacenavd](https://github.com/FreeSpacenav/spacenavd) — system daemon that owns the device
- [libspnav](https://github.com/FreeSpacenav/libspnav) — client library used by spacenavd-aware apps (Blender, FreeCAD, the diagnostic tool here)

This project is a userspace layer on top of that stack: a control daemon that maps 6DOF input to desktop actions, plus a configuration GUI.
