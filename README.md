# SpaceMouse Linux Driver

> **This project is under active development.** New features, fixes, and improvements are being added regularly. Contributions and feedback are welcome — feel free to open an issue or pull request.

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

A **system tray icon** appears in your taskbar. Click it to open **SpaceMouse Control** — a unified settings app with three pages:

- **Desktop** — sensitivity, axis mapping, button actions, per-application profiles
- **FreeCAD** — SpaceMouse sensitivity, axis enable/invert, navigation style (writes directly to FreeCAD's config)
- **Blender** — NDOF sensitivity, deadzone, axis inversion, Lock Horizon toggle

A live preview bar at the bottom shows real-time axis movement and button state.

The driver **automatically detects** when you switch to Blender or FreeCAD and gets out of the way so the native 3D navigation takes over.

## Blender

Blender works out of the box — no extra setup needed. When you switch to Blender, the driver disables itself and Blender's built-in SpaceMouse support handles all 3D navigation directly.

To configure Blender's SpaceMouse settings from the unified GUI:

1. Open **SpaceMouse Control** (tray icon) and go to the **Blender** page
2. Adjust sensitivity, deadzone, axis inversion, etc.
3. Click **Apply** — settings are saved to `~/.config/spacemouse/blender-ndof.json`
4. Click **Install Startup Script** (first time only) — this copies a sync script to Blender's startup directory
5. Restart Blender — settings are applied automatically on every launch

> **Tip:** If pitch/tilt doesn't work in Blender, make sure **Lock Horizon** is OFF in the Blender page (Blender enables it by default, which blocks the pitch axis).

## FreeCAD

FreeCAD on Linux has a bug that makes SpaceMouse navigation jerky and unusable. The normal FreeCAD from `pacman` does **not** work with the SpaceMouse — you need to build a patched version. This sounds complicated, but it's just 3 commands.

You don't need to install FreeCAD from `pacman` first — the build command below downloads, patches, and installs everything in one step. It builds **FreeCAD 1.0.2** (the version is set in the build config).

Follow these steps **in order**:

### 1. Build and install the patched FreeCAD

From the repo directory, run:

```bash
cd freecad-pacman-build
makepkg -sfi
```

This downloads the FreeCAD source code, applies the SpaceMouse fix, compiles it, and installs it as a normal Arch package. The build takes **15–45 minutes** depending on your CPU. You'll be asked for your password once at the end.

> After a system update (`pacman -Syu`), FreeCAD gets replaced with the broken stock version. Just run `cd freecad-pacman-build && makepkg -sfi` again to fix it.

### 2. Start FreeCAD once, then close it

Open FreeCAD from your app menu (or type `freecad` in a terminal). This creates the config files that the next step needs. Close FreeCAD again.

### 3. Configure the SpaceMouse

```bash
./scripts/freecad-spacemouse-patch.sh
```

This tells FreeCAD how to use the SpaceMouse: enables the correct device mode, sets the navigation style to Blender-style (orbit, pan, zoom), enables all 6 axes, and assigns the two buttons (Fit All + Home View).

> **Important:** Always close FreeCAD before running this command. FreeCAD overwrites its own config file when you close it — if it's still open, your changes will be lost.

### 4. Open FreeCAD — done

Start FreeCAD. The SpaceMouse should now work smoothly: tilt to orbit, push/pull to pan, twist to zoom.

If it feels too fast or too slow, open **SpaceMouse Control** (tray icon) → **FreeCAD** page and adjust the **Global Sensitivity** slider. Click **Apply** (with FreeCAD closed).

> For technical details about what the patch fixes and alternative build methods (source build, manual patching for non-Arch distros), see [docs/FREECAD_SPACEMOUSE_FIX.md](docs/FREECAD_SPACEMOUSE_FIX.md).

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

### FreeCAD SpaceMouse is jerky/stuttering

This means you're running an **unpatched** FreeCAD. The standard Arch package has a bug that causes 500 redraws/sec — no amount of config changes will fix it. You must build the patched version:

```bash
cd freecad-pacman-build && makepkg -sfi
```

If it was working before but broke after a system update, rebuild with the same command — `pacman -Syu` replaces the patched FreeCAD with the stock version.

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

## Status

This project is **actively maintained**. Planned and in-progress work:

- More per-application profiles (Krita, Inkscape, video editors)
- FreeCAD upstream patch submission
- AUR package for the driver itself
- Multi-device support (SpaceMouse Pro buttons)

Found a bug or have a feature request? [Open an issue](https://github.com/Maik-0000FF/SpaceMouse_3dconnexion/issues).

## Acknowledgments

- [spacenavd](https://github.com/FreeSpacenav/spacenavd) — Open-source SpaceMouse device daemon
- [libspnav](https://github.com/FreeSpacenav/libspnav) — Client library for SpaceMouse input
