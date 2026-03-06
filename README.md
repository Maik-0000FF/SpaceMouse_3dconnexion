# SpaceMouse Linux Driver

> **This project is under active development.** Contributions and feedback are welcome — feel free to open an issue or pull request.

Use your 3Dconnexion SpaceMouse as a desktop input device on Linux.
Tilt to scroll, push/pull to zoom, twist to switch virtual desktops — and it works natively inside Blender and FreeCAD for 3D navigation.

## What You Need

- **Arch Linux** (or Arch-based like EndeavourOS, Manjaro)
- **3Dconnexion SpaceMouse** connected via USB
- **yay** or **paru** (AUR helper) — if you don't have one, [install yay](https://github.com/Jguer/yay#installation)

## Installation

```bash
git clone https://github.com/Maik-0000FF/SpaceMouse_3dconnexion.git
cd SpaceMouse_3dconnexion
./install.sh
```

The installer takes care of everything: installing packages, setting up permissions, compiling the driver, and starting the background services. You'll be asked for your password when it needs administrator access.

After installation, **plug in your SpaceMouse** (or unplug and replug it) and it's ready to use.

## How It Works

Once installed, the SpaceMouse works on your desktop like this:

- **Tilt left/right** → horizontal scroll
- **Tilt forward/back** → vertical scroll
- **Push down / pull up** → zoom (Ctrl+scroll)
- **Twist left/right** → switch virtual desktops
- **Left button** → KDE Overview
- **Right button** → Show Desktop

When you switch to **Blender** or **FreeCAD**, the desktop driver steps aside automatically and the app's native 3D navigation takes over — no manual switching needed.

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

FreeCAD on Linux has a bug that makes SpaceMouse navigation jerky and unusable ([PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) submitted upstream). You need to build a patched version — it's just 3 commands.

**Choose your version** by editing `freecad-pacman-build/PKGBUILD` — change `_build_version` at the top:

| Setting | Version | Description |
|---------|---------|-------------|
| `_build_version="stable"` | 1.0.2 | Latest stable release |
| `_build_version="rc"` | 1.1rc2 | Release candidate (newer features) |

### 1. Build and install the patched FreeCAD

```bash
cd freecad-pacman-build
makepkg -sfi
```

This downloads the source, applies the fix, compiles, and installs as a normal Arch package. Takes **15–45 minutes** depending on your CPU.

> After a system update (`pacman -Syu`), FreeCAD gets replaced with the stock version. Just run `cd freecad-pacman-build && makepkg -sfi` again.

### 2. Start FreeCAD once, then close it

This creates the config files that the next step needs.

### 3. Configure the SpaceMouse

```bash
./scripts/freecad-spacemouse-patch.sh
```

> **Important:** Always close FreeCAD before running this. FreeCAD overwrites its config on exit.

### 4. Open FreeCAD — done

If it feels too fast or too slow, open **SpaceMouse Control** → **FreeCAD** page and adjust the sensitivity slider (with FreeCAD closed).

> For technical details, see [docs/FREECAD_SPACEMOUSE_FIX.md](docs/FREECAD_SPACEMOUSE_FIX.md).

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

### FreeCAD SpaceMouse is jerky/stuttering

You're running an unpatched FreeCAD. Rebuild:

```bash
cd freecad-pacman-build && makepkg -sfi
```

### Tray icon not showing

```bash
systemctl --user restart spacemouse-config
```

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

Any 6DOF device supported by spacenavd should work. LED control currently only works for the SpaceNavigator — other models may use different HID report formats. If you have a different model, please [open an issue](https://github.com/Maik-0000FF/SpaceMouse_3dconnexion/issues).

## License

GPLv3 — See [LICENSE](LICENSE) for details.

## Status

This project is **actively maintained**. Current focus: desktop navigation and 3D app integration.

- FreeCAD upstream patch ([PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110)) — under review
- AUR package for the driver itself
- Multi-device support (SpaceMouse Pro buttons)

Found a bug or have a feature request? [Open an issue](https://github.com/Maik-0000FF/SpaceMouse_3dconnexion/issues).

## Acknowledgments

- [spacenavd](https://github.com/FreeSpacenav/spacenavd) — Open-source SpaceMouse device daemon
- [libspnav](https://github.com/FreeSpacenav/libspnav) — Client library for SpaceMouse input
