# spacemouse-linux

Open-source driver stack and desktop integration for 3Dconnexion SpaceMouse devices on Linux.

Provides a high-performance C daemon for translating 6DOF input into desktop actions (scroll, zoom, virtual desktop switching), per-application profile support with automatic window detection, and a PySide6 configuration GUI with system tray integration.

## Features

- **Per-application profiles** with automatic window detection via KWin D-Bus
- **System tray GUI** (PySide6/Qt6) for visual profile configuration
- **High-performance C daemon** using direct uinput for sub-millisecond scroll/zoom latency
- **6-axis mapping**: configurable action per axis (scroll, zoom, desktop switch)
- **Button mapping**: KDE Overview, Show Desktop, or disabled per profile
- **Nonlinear response curve** with configurable exponent and deadzone
- **Native 3D app support**: Blender and FreeCAD profiles automatically disable the daemon to avoid input conflicts
- **UNIX command socket** for scripting and IPC
- **Backward-compatible config**: supports both legacy flat format and new multi-profile JSON
- **Presets included**: Default, Blender, FreeCAD, Browser, File Manager

## Supported Devices

| Device | Vendor:Product | Status |
|--------|---------------|--------|
| SpaceNavigator | 046d:c626 | Tested |
| SpaceMouse Compact | 256f:c635 | Supported |
| SpaceMouse Wireless | 256f:c62e/c62f | Supported |
| SpaceMouse Pro (Wireless) | 256f:c631/c632 | Supported |
| SpaceMouse Enterprise | 256f:c633 | Supported |
| SpaceExplorer | 046d:c627 | Supported |
| SpacePilot Pro | 046d:c625 | Supported |

All devices supported by spacenavd should work.

## Architecture

```
SpaceMouse (USB HID)
        |
  Linux Kernel HID
        |
  spacenavd (reads device, provides UNIX socket API)
        |
  libspnav socket
        |
   +----+----+-------------------+
   |         |                   |
Blender   FreeCAD     spacemouse-desktop daemon
(native)  (native)         |
                      +----+----+
                      |         |
                   uinput    D-Bus/KWin
                (scroll/zoom) (desktop switch)
                      |
               spacemouse-config GUI
              (PySide6 system tray)
```

## Requirements

- Arch Linux (or Arch-based)
- spacenavd (AUR)
- libspnav
- json-c
- dbus
- PySide6 (for GUI)

## Installation

```bash
git clone https://github.com/YOUR_USER/spacemouse-linux.git
cd spacemouse-linux
chmod +x install.sh
./install.sh
```

The installer handles everything: package installation (via yay/paru), udev rules, spacenavd setup, compilation, systemd services, and GUI deployment.

## Usage

### Quick Start

After installation, the SpaceMouse works immediately:

- **Desktop**: tilt to scroll, lift/push for zoom, twist to switch workspaces
- **Blender/FreeCAD**: native 3D navigation (daemon auto-disables)
- **Tray icon**: click to open settings, right-click for quick profile switching

### Diagnostic Tool

```bash
spacemouse-test --check   # Run all system checks
spacemouse-test --live    # Real-time axis and button monitor
spacemouse-test --led     # LED toggle test
```

### Command Socket

The daemon exposes a UNIX socket for scripting:

```bash
# Query status
echo "STATUS" | socat - UNIX:/run/user/$(id -u)/spacemouse-cmd.sock

# Switch profile
echo "PROFILE blender" | socat - UNIX:/run/user/$(id -u)/spacemouse-cmd.sock

# Reload config
echo "RELOAD" | socat - UNIX:/run/user/$(id -u)/spacemouse-cmd.sock
```

### Profile Configuration

Edit `~/.config/spacemouse/config.json` or use the GUI.

Available axis actions: `none`, `scroll_h`, `scroll_v`, `zoom`, `desktop_switch`
Available button actions: `none`, `overview`, `show_desktop`

Each profile supports:
- `match_wm_class`: window class names for automatic switching
- `deadzone`: input threshold (0-100)
- `scroll_speed`, `scroll_exponent`, `zoom_speed`: response tuning
- `desktop_switch_threshold`, `desktop_switch_cooldown_ms`: workspace switch tuning
- `axis_mapping`: per-axis action assignment
- `button_mapping`: per-button action assignment
- `invert_scroll_x`, `invert_scroll_y`: axis inversion

### Why Blender/FreeCAD Presets Use "none"

Blender and FreeCAD link against libspnav and read SpaceMouse input directly from spacenavd for native 3D viewport navigation (orbit, pan, zoom). The desktop daemon receives the same events in parallel. If the daemon were to also emit scroll or zoom actions, it would cause double-input conflicts.

The correct preset for 3D applications sets all axes and buttons to `none`, which makes the daemon completely transparent while the 3D app handles all 6DOF input natively.

### Integrating with Custom Applications

```c
#include <spnav.h>

int main(void) {
    spnav_event ev;
    spnav_open();
    spnav_client_name("my_app");
    while (spnav_wait_event(&ev)) {
        if (ev.type == SPNAV_EVENT_MOTION)
            printf("T(%d %d %d) R(%d %d %d)\n",
                ev.motion.x, ev.motion.y, ev.motion.z,
                ev.motion.rx, ev.motion.ry, ev.motion.rz);
    }
    spnav_close();
}
// Compile: gcc -o myapp myapp.c -lspnav
```

See `src/spnav_example.c` for a complete example.

## Services

```bash
# Driver daemon (system-level)
sudo systemctl status spacenavd

# Desktop navigation daemon (user-level)
systemctl --user status spacemouse-desktop

# GUI tray application (user-level)
systemctl --user status spacemouse-config
```

## Uninstall

```bash
./uninstall.sh
```

## FreeCAD SpaceMouse Fix

FreeCAD on Linux has notoriously jerky, unusable SpaceMouse navigation. This repo includes a patch that fixes the root cause. See **[docs/FREECAD_SPACEMOUSE_FIX.md](docs/FREECAD_SPACEMOUSE_FIX.md)** for the full guide.

**Quick start** (Arch Linux):

```bash
# 1. Configure FreeCAD user.cfg for SpaceMouse
./scripts/freecad-spacemouse-patch.sh

# 2. Build and install patched FreeCAD as Arch package
cd freecad-pacman-build
makepkg -sf -s
sudo pacman -U freecad-*.pkg.tar.zst
```

The patch is minimal (+13 lines, 2 files) and fixes a performance bug in FreeCAD's event pipeline that has existed since 2018.

## Project Structure

```
spacemouse-linux/
├── src/
│   ├── spacemouse-desktop.c    C daemon (profiles, uinput, D-Bus, cmd socket)
│   ├── spacemouse-test.c       Diagnostic tool
│   ├── spnav_example.c         libspnav client example
│   └── Makefile
├── gui/
│   ├── spacemouse-config.py    PySide6 GUI (tray, profiles, window detection)
│   └── spacemouse-config.desktop
├── config/
│   ├── 99-spacemouse.rules     udev rules
│   ├── spnavrc                 spacenavd configuration
│   └── spacemouse-desktop.conf Default profile presets
├── systemd/
│   ├── spacemouse-desktop.service
│   └── spacemouse-config.service
├── freecad-patches/
│   └── spacemouse-smooth-navigation.patch   FreeCAD SpaceMouse fix
├── freecad-pacman-build/
│   └── PKGBUILD                             Arch package with patch
├── scripts/
│   ├── freecad-spacemouse-patch.sh          FreeCAD user.cfg configurator
│   ├── freecad-pacman-build.sh              Arch package build script
│   └── freecad-build-patched.sh             Source build script
├── docs/
│   └── FREECAD_SPACEMOUSE_FIX.md            Full guide for FreeCAD fix
├── install.sh
├── uninstall.sh
└── LICENSE
```

## License

GPLv3 - See [LICENSE](LICENSE) for details.

## Acknowledgments

- [spacenavd](https://github.com/FreeSpacenav/spacenavd) - The underlying device daemon
- [libspnav](https://github.com/FreeSpacenav/libspnav) - Client library for 6DOF input
