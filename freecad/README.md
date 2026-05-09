# FreeCAD SpaceMouse Patches

Self-contained collection of patches and build scripts for fixing FreeCAD's SpaceMouse handling on Linux. Independent from the SpaceMouse driver/GUI in the rest of this repository — once all fixes ship in upstream FreeCAD releases, this directory can be removed without affecting the driver.

## Why this exists

FreeCAD on Linux has several SpaceMouse bugs. Some have been merged upstream and ship in weekly builds (and FreeCAD 1.2), others are still pending. None of the fixes are in FreeCAD 1.0.x or 1.1.x. This directory provides a patcher and an Arch build that apply the fixes locally.

| Fix | Issue/PR | Status |
|-----|----------|--------|
| Event coalescing (jerky navigation) | [PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) | Merged (weekly 2026-03-11) |
| Batched camera updates | [PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) | Merged (weekly 2026-03-11) |
| Per-axis deadzone | [PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) | Merged (weekly 2026-03-11) |
| Button selection sync | [PR #28181](https://github.com/FreeCAD/FreeCAD/pull/28181) | Merged (weekly 2026-04-01) |
| Checkable action invoke | [PR #28181](https://github.com/FreeCAD/FreeCAD/pull/28181) | Merged (weekly 2026-04-01) |
| Disconnect detection (100% CPU) | [PR #28915](https://github.com/FreeCAD/FreeCAD/pull/28915) | Open (approved) |
| Reset button fix | [#19366](https://github.com/FreeCAD/FreeCAD/issues/19366) | Patcher only |

The patcher detects already-merged fixes and skips them automatically, so it works on any version.

## Layout

```
freecad/
├── patches/         apply-spacemouse-fix.py — pattern-based patcher (single source of truth)
├── pacman-build/    Arch PKGBUILD + Arch-compat patches
├── scripts/         build helpers and FreeCAD config setup
└── docs/            SPACEMOUSE_FIX.md — technical reference
```

## Use the patcher standalone

The patcher is a single Python file with no dependencies — it can be downloaded directly without cloning this repo:

```bash
curl -O https://raw.githubusercontent.com/Maik-0000FF/SpaceMouse_3dconnexion/main/freecad/patches/apply-spacemouse-fix.py

# Dry-run
python3 apply-spacemouse-fix.py --check /path/to/freecad-source

# Apply
python3 apply-spacemouse-fix.py /path/to/freecad-source
```

## Build patched FreeCAD (Arch Linux)

Edit `pacman-build/PKGBUILD` to choose your version (`_build_version="stable"` for 1.1.0, `"weekly"` for the 1.2 development branch), then:

```bash
cd freecad/pacman-build
makepkg -sfi
```

This downloads the source, applies the patcher, compiles, and installs as a normal Arch package. Takes 15–45 minutes depending on your CPU. After a system update overwrites it, just rerun `makepkg -sfi`.

## Build patched FreeCAD (other distros, from source)

```bash
./freecad/scripts/build-patched.sh --clone 1.0.2
```

Binary lands at `freecad-build/build/bin/FreeCAD` — your system FreeCAD stays untouched.

## Configure SpaceMouse inside FreeCAD

Either use the **FreeCAD** page in **SpaceMouse Control** (tray icon → Settings), or run `./freecad/scripts/setup.sh` to write the recommended `user.cfg`. Always close FreeCAD before editing — it overwrites its config on exit.

See [docs/SPACEMOUSE_FIX.md](docs/SPACEMOUSE_FIX.md) for the technical reference behind each fix.
