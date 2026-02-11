# SpaceMouse Linux Driver

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

A **system tray icon** appears in your taskbar. Click it to open the settings GUI, where you can adjust sensitivity, axis behavior, and per-application profiles.

The driver **automatically detects** when you switch to Blender or FreeCAD and gets out of the way so the native 3D navigation takes over.

## Blender

Blender works out of the box — no extra setup needed. When you switch to Blender, the driver disables itself and Blender's built-in SpaceMouse support handles all 3D navigation directly.

> **Tip:** If pitch/tilt doesn't work in Blender, go to **Edit > Preferences > Navigation** and disable **Lock Camera to Horizon** (Blender enables it by default, which blocks the pitch axis).

## FreeCAD SpaceMouse Fix

FreeCAD on Linux has a long-standing bug that makes SpaceMouse navigation extremely jerky and unusable. This repo includes a patch that fixes it.

### Step 1: Configure FreeCAD

First, start FreeCAD at least once (so it creates its config files), then run:

```bash
./scripts/freecad-spacemouse-patch.sh
```

This configures FreeCAD to work properly with the SpaceMouse on Linux (enables the correct device mode, sets navigation style, enables all axes).

### Step 2: Build patched FreeCAD

This builds a patched version of FreeCAD as a proper Arch Linux package:

```bash
cd freecad-pacman-build
makepkg -sfi
```

What the flags mean:
- `-s` = automatically install build dependencies
- `-f` = overwrite any previous build
- `-i` = install the package when done

**This takes 15–45 minutes** depending on your CPU. You'll see lots of compiler output — that's normal. When it finishes, FreeCAD is patched and installed.

### Step 3: Adjust sensitivity (optional)

If the SpaceMouse feels too fast or slow in FreeCAD, open FreeCAD's Python console (**View > Panels > Python console**) and run:

```python
p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Spaceball/Motion")
p.SetInt("GlobalSensitivity", -15)
```

Lower values = slower (try -30 for slow, 0 for fast). The change takes effect immediately.

> For technical details about what the patch changes and alternative build methods (source build, manual patching), see [docs/FREECAD_SPACEMOUSE_FIX.md](docs/FREECAD_SPACEMOUSE_FIX.md).

## Uninstall

```bash
./uninstall.sh
```

This stops the services, removes the binaries, and cleans up configuration files.

## Troubleshooting

### SpaceMouse not detected

1. Check that the device is plugged in: `lsusb | grep -i 3dconnexion`
2. Check that the system daemon is running: `systemctl status spacenavd`
3. Run the built-in diagnostic: `spacemouse-test --check`

If spacenavd isn't running, start it:

```bash
sudo systemctl enable --now spacenavd
```

### FreeCAD still jerky after patching

- Make sure you ran `./scripts/freecad-spacemouse-patch.sh` **before** launching FreeCAD
- Rebuild if a system update replaced FreeCAD: `cd freecad-pacman-build && makepkg -sfi`
- Check that you're running the patched version: `which freecad` should show `/usr/bin/freecad`

### Tray icon not showing

The tray icon runs as a user service. Check its status:

```bash
systemctl --user status spacemouse-config
```

If it's not running, restart it:

```bash
systemctl --user restart spacemouse-config
```

### Navigation works but buttons don't respond

Buttons are mapped by the profile. Open the tray icon settings and check that button actions are set (default: Left = Overview, Right = Show Desktop). In Blender/FreeCAD profiles, buttons are disabled by default to avoid conflicts.

### Desktop scrolling/zoom works but not in a specific app

Some apps need their own profile. Open the tray icon and create a profile with the app's window class. You can find the window class by running `spacemouse-test --check` while the app is focused.

## Advanced

### Diagnostics

```bash
spacemouse-test --check   # System checks (USB, spacenavd, uinput)
spacemouse-test --live    # Real-time axis and button monitor
spacemouse-test --led     # LED toggle test
```

### Profile customization

Profiles are stored in `~/.config/spacemouse/config.json`. You can edit them with the GUI (tray icon) or by hand. Each profile can set deadzone, scroll speed, zoom speed, axis mappings, and which windows it applies to.

### Supported devices

| Device | Status |
|--------|--------|
| SpaceNavigator | Tested |
| SpaceMouse Compact | Supported |
| SpaceMouse Wireless | Supported |
| SpaceMouse Pro (Wireless) | Supported |
| SpaceMouse Enterprise | Supported |
| SpaceExplorer | Supported |
| SpacePilot Pro | Supported |

Any device supported by spacenavd should work.

### Services

The driver runs as three services:

```bash
sudo systemctl status spacenavd            # System daemon (reads USB device)
systemctl --user status spacemouse-desktop  # Desktop navigation (scroll/zoom/desktops)
systemctl --user status spacemouse-config   # Tray icon and settings GUI
```

## License

GPLv3 — See [LICENSE](LICENSE) for details.

## Acknowledgments

- [spacenavd](https://github.com/FreeSpacenav/spacenavd) — Open-source SpaceMouse device daemon
- [libspnav](https://github.com/FreeSpacenav/libspnav) — Client library for SpaceMouse input
