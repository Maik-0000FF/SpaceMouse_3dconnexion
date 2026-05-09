# FreeCAD SpaceMouse Patches

Self-contained collection of patches and build scripts for fixing FreeCAD's SpaceMouse handling on Linux. Independent from the SpaceMouse driver/GUI in the rest of this repository — once all fixes ship in upstream FreeCAD releases, this directory can be removed without affecting the driver.

## Layout

```
freecad/
├── patches/         apply-spacemouse-fix.py — pattern-based patcher (single source of truth)
├── pacman-build/    Arch PKGBUILD + Arch-compat patches
├── scripts/         build helpers and FreeCAD config setup
└── docs/            SPACEMOUSE_FIX.md — technical reference
```

## Quick reference

| Task | Command |
|------|---------|
| Apply patches to a FreeCAD source tree | `python3 freecad/patches/apply-spacemouse-fix.py /path/to/freecad-source` |
| Dry-run check | `python3 freecad/patches/apply-spacemouse-fix.py --check /path/to/freecad-source` |
| Build patched FreeCAD as Arch package | `cd freecad/pacman-build && makepkg -sfi` |
| Build patched FreeCAD from source | `./freecad/scripts/build-patched.sh --clone 1.0.2` |
| Configure FreeCAD `user.cfg` | `./freecad/scripts/setup.sh` |

See [docs/SPACEMOUSE_FIX.md](docs/SPACEMOUSE_FIX.md) for the technical reference.
