# FreeCAD SpaceMouse Fixes — Technical Reference

This document covers the technical details of all FreeCAD SpaceMouse patches. For the step-by-step installation guide, see the [README](../README.md#freecad).

---

## Overview

| Fix | Issue/PR | Status | Files |
|-----|----------|--------|-------|
| Event coalescing | [PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) | **Merged** | `GuiNativeEventLinux.cpp` |
| Batched camera updates | [PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) | **Merged** | `NavigationStyle.cpp` |
| Per-axis deadzone | [PR #28110](https://github.com/FreeCAD/FreeCAD/pull/28110) | **Merged** | `GuiNativeEventLinux.cpp/.h` |
| Button selection sync | [PR #28181](https://github.com/FreeCAD/FreeCAD/pull/28181) | In merge queue | `DlgCustomizeSpaceball.cpp` |
| Checkable action invoke | [PR #28181](https://github.com/FreeCAD/FreeCAD/pull/28181) | In merge queue | `MainWindow.cpp`, `NavlibCmds.cpp` |
| Disconnect detection | [#17809](https://github.com/FreeCAD/FreeCAD/issues/17809) | PR planned | `GuiNativeEventLinux.cpp/.h` |

All six fixes are applied by a single patcher: `freecad-patches/apply-spacemouse-fix.py`

---

## Availability

| Version | Performance (PR #28110) | Button fixes (PR #28181) | Disconnect fix (#17809) |
|---------|------------------------|--------------------------|------------------------|
| FreeCAD 1.0.x | Not included | Not included | Not included |
| FreeCAD 1.1.x (incl. RC3) | Not included | Not included | Not included |
| Weekly builds (after 2026-03-07) | **Included** | Not yet | Not yet |
| FreeCAD 1.2 | **Included** | **Planned** (milestone 1.2) | PR planned |

For FreeCAD 1.0.x and 1.1.x: use the patcher to get all fixes.

---

## Fix 1: Event Coalescing (PR #28110)

**File:** `src/Gui/3Dconnexion/GuiNativeEventLinux.cpp`

### Problem

The SpaceMouse sends motion data at 125–250 Hz. FreeCAD's `pollSpacenav()` drains **all** pending events from the socket and posts **each one individually** as a separate Qt event. When spacenavd buffers 5 events while FreeCAD is busy rendering, all 5 arrive at once — each triggering a full scene redraw.

### Fix

Instead of posting every event individually, the drain loop keeps only the **latest** motion state and posts it **once** per poll cycle. SpaceMouse events represent the current puck deflection (not accumulated deltas), so the latest event always contains the complete state.

---

## Fix 2: Batched Camera Updates (PR #28110)

**File:** `src/Gui/Navigation/NavigationStyle.cpp`

### Problem

Inside `processMotionEvent()`, changing `camera->orientation` and `camera->position` each triggers a **separate** Coin3D scene redraw notification. That's 2 redraws per event — at 250 Hz, up to 500 redraws per second.

### Fix

Camera property changes are wrapped in `enableNotify(false)` / `enableNotify(true)` + `touch()`, so orientation and position updates trigger a **single** Coin3D redraw instead of two.

### Combined result (Fix 1 + 2)

- ~60 redraws/sec instead of ~500 (matches display refresh rate)
- Smooth, responsive rotation, panning, and zooming
- Instant stop when the puck is released (no drift)
- Zero behavior changes — same rotation/translation math as upstream

---

## Fix 3: Per-Axis Deadzone (PR #28110)

**Files:** `src/Gui/3Dconnexion/GuiNativeEventLinux.cpp` + `GuiNativeEventLinux.h`

### Problem

All axis values are passed through unfiltered. Users with sensitive devices or slight puck drift have no way to set individual deadzone thresholds per axis.

### Fix

A `DeadzoneCache` member of `GuiNativeEvent` reads per-axis deadzone thresholds from `user.cfg` (`BaseApp/Spaceball/Motion/{Axis}Deadzone`) once at startup and auto-updates via `ParameterGrp::ObserverType` when values change — no polling overhead. After coalescing, each axis value below its threshold is zeroed out before posting.

### Configuration

Set via FreeCAD's Parameter Editor (`Tools → Edit parameters`):

**Path:** `BaseApp/Spaceball/Motion`

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `PanLRDeadzone` | Integer | 0–350 | Pan left/right deadzone |
| `PanUDDeadzone` | Integer | 0–350 | Pan up/down deadzone |
| `ZoomDeadzone` | Integer | 0–350 | Zoom deadzone |
| `TiltDeadzone` | Integer | 0–350 | Tilt (RX) deadzone |
| `RollDeadzone` | Integer | 0–350 | Roll (RY) deadzone |
| `SpinDeadzone` | Integer | 0–350 | Spin (RZ) deadzone |

Values represent raw axis thresholds — axes below their deadzone value are zeroed out. Set to `0` to disable (default). A value of `100–150` works well for filtering drift.

---

## Fix 4: Button Selection Sync (PR #28181)

**File:** `src/Gui/Dialogs/DlgCustomizeSpaceball.cpp`

**Fixes:** [#17812](https://github.com/FreeCAD/FreeCAD/issues/17812)

### Problem

In FreeCAD's Spaceball button customization dialog, `ButtonView::selectButton()` updates the visual selection but not `currentIndex()`. When `goChangedCommand()` is called, it reads the command from `currentIndex()` — which still points to the previously selected button. This causes button assignments to be written to the wrong button.

### Fix

Add `this->setCurrentIndex(idx)` to keep `currentIndex()` in sync with the visual selection:

```cpp
void ButtonView::selectButton(int number)
{
    QModelIndex idx = this->model()->index(number, 0);
    this->selectionModel()->select(idx, QItemSelectionModel::ClearAndSelect);
    this->setCurrentIndex(idx);
    this->scrollTo(idx, QAbstractItemView::EnsureVisible);
}
```

---

## Fix 5: Checkable Action Invoke (PR #28181)

**Files:** `src/Gui/MainWindow.cpp`, `src/Gui/3Dconnexion/navlib/NavlibCmds.cpp`

**Fixes:** [#10073](https://github.com/FreeCAD/FreeCAD/issues/10073)

### Problem

SpaceBall button handlers use `runCommandByName()`, which internally calls `invoke(0)`. For checkable commands like `Std_OrthographicCamera` and `Std_PerspectiveCamera`, the `activated()` method has a guard:

```cpp
void StdOrthographicCamera::activated(int iMsg)
{
    if (iMsg == 1) {  // Only executes when iMsg == 1
        // ... switch camera
    }
}
```

Since `invoke(0)` passes `iMsg = 0`, the guard is never satisfied and the command does nothing.

### Fix

Replace `runCommandByName()` with `getCommandByName()` + `invoke(1)` in the two SpaceBall button handlers:

```cpp
Command* cmd = Application::Instance->commandManager().getCommandByName(
    commandName.c_str());
if (cmd) {
    cmd->invoke(1);
}
```

**Important:** This fix is applied only in the SpaceBall handlers (`MainWindow.cpp` for Linux/spnav, `NavlibCmds.cpp` for Windows/macOS NavLib). `runCommandByName()` itself is NOT changed — it has ~60 call sites where `invoke(0)` is correct.

Both fixes are cross-platform (Linux, Windows, macOS).

---

## Fix 6: Disconnect Detection (#17809)

**Files:** `src/Gui/3Dconnexion/GuiNativeEventLinux.cpp` + `GuiNativeEventLinux.h`

**Fixes:** [#17809](https://github.com/FreeCAD/FreeCAD/issues/17809)

### Problem

When spacenavd stops (crash, `systemctl stop`, USB disconnect), the Unix socket fd enters an EOF state. The kernel reports the fd as "readable" (EOF is readable for select/epoll). `QSocketNotifier` fires continuously, calling `pollSpacenav()` in a tight loop. `spnav_poll_event()` returns 0 (identical to "no events"), so libspnav doesn't detect the dead connection. One CPU core goes to 100%.

```
QSocketNotifier fires → pollSpacenav() → spnav_poll_event() returns 0
→ function returns → QSocketNotifier fires again immediately → 100% CPU
```

The root cause is in libspnav: `spnav_poll_event()` does not distinguish between "no events available" and "connection dead (EOF)" — both return 0. The socket is not closed internally.

### Fix

After an empty poll cycle (QSocketNotifier fired but `spnav_poll_event()` returned 0), verify the connection with a non-consuming `recv(MSG_PEEK)`:

```cpp
if (!gotEvent) {
    int fd = spnav_fd();
    if (fd >= 0) {
        char buf;
        ssize_t ret = recv(fd, &buf, 1, MSG_PEEK | MSG_DONTWAIT);
        if (ret == 0 || (ret < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {
            Base::Console().warning("Lost connection to spacenav daemon\n");
            spnavNotifier->setEnabled(false);
            spnav_close();
            spnavNotifier = nullptr;
        }
    }
}
```

- `MSG_PEEK` — looks at data without consuming it (doesn't interfere with libspnav)
- `MSG_DONTWAIT` — non-blocking, returns immediately
- `recv` returns `0` on EOF (remote side closed) → spacenavd is dead
- `recv` returns `-1` with `EAGAIN` → socket is alive, no data (normal)

The `QSocketNotifier*` is stored as a member variable (`spnavNotifier`) instead of a local variable, and the destructor only calls `spnav_close()` if the connection is still active.

No reconnect timer — the user restarts FreeCAD after restarting spacenavd. This is the minimal, clean fix for the 100% CPU bug.

This fix is Linux-only (Windows/macOS use NavLib SDK).

---

## The Patcher

`freecad-patches/apply-spacemouse-fix.py` applies all six fixes to any FreeCAD source tree. It uses pattern matching — no line numbers, no version-specific code. Already-applied fixes are detected and skipped.

```bash
# Standalone download (no dependencies, just Python 3)
curl -O https://raw.githubusercontent.com/Maik-0000FF/SpaceMouse_3dconnexion/main/freecad-patches/apply-spacemouse-fix.py

# Check what can be patched (dry-run)
python3 apply-spacemouse-fix.py --check /path/to/freecad-source

# Apply all fixes
python3 apply-spacemouse-fix.py /path/to/freecad-source
```

---

## Build Methods

### Method A: Arch Linux Package (Recommended)

See the [README installation guide](../README.md#build-patched-freecad-arch-linux).

### Method B: Build from Source

If you're not on Arch, or want to keep the patched version separate from your system FreeCAD:

```bash
# Clone + patch + build
./scripts/freecad-build-patched.sh --clone 1.0.2

# Rebuild existing source
./scripts/freecad-build-patched.sh

# Run the patched version
./freecad-build/build/bin/FreeCAD
```

The system FreeCAD (`/usr/bin/freecad`) remains untouched with this method.

### Method C: Manual Patching (Any Version)

```bash
python3 freecad-patches/apply-spacemouse-fix.py /path/to/freecad-source
```

Then build FreeCAD as you normally would.

---

## Troubleshooting

### SpaceMouse not detected in FreeCAD

```bash
systemctl status spacenavd        # Check daemon is running
ls -la /var/run/spnav.sock        # Check socket exists
spacemouse-test --check           # Run diagnostic tool
```

### Navigation works but axes are wrong

Run `./scripts/freecad-spacemouse-patch.sh` to set FlipYZ and axis enables correctly.
You can also adjust per-axis settings in FreeCAD: **Edit > Preferences > Spaceball > Motion**.

### FreeCAD crashes on startup after patching

The patches only change event handling, not core functionality. If FreeCAD crashes, it's likely a build configuration issue:

```bash
cd freecad-pacman-build
makepkg -sfCi      # -C cleans build dir first
```

### Patch doesn't apply cleanly

The patcher finds code patterns automatically and works across FreeCAD versions. If it fails, the code may have been significantly refactored. Use `--check` to diagnose:

```bash
python3 apply-spacemouse-fix.py --check /path/to/freecad-source
```

---

## Compatibility

| FreeCAD Version | Status |
|-----------------|--------|
| 1.0.x | Tested, all 6 fixes work |
| 1.1rc2/rc3 | Tested, all 6 fixes work |
| 1.2.x (main) | PR #28110 merged, PR #28181 in merge queue |

| Distribution | Method |
|-------------|--------|
| Arch Linux | Method A (pacman package) recommended |
| Ubuntu/Debian | Method B (source build) or Method C (manual patch) |
| Fedora | Method B or Method C |
| Flatpak/Snap | Not directly patchable — use Method B |

| Device | Status |
|--------|--------|
| SpaceNavigator (046d:c626) | Tested |
| Any spacenavd-supported device | Should work |

---

## Technical Background

On Windows and macOS, FreeCAD uses the 3Dconnexion NavLib SDK which handles all input smoothing, interpolation, and event management internally. The camera is updated via `SetCameraMatrix()` which simply sets the final camera state — no event queuing issues.

On Linux, FreeCAD uses the legacy spacenavd/libspnav path (`GuiNativeEventLinux.cpp`), which was written in 2018 and never optimized for the high event rates that SpaceMouse devices produce. NavLib support is explicitly disabled for Linux in FreeCAD's CMake configuration (`FREECAD_3DCONNEXION_SUPPORT` is Win/Mac only).

### Failed Approaches

1. Custom `processMotionEvent` with deadzone/smoothing/curves — root cause was the pipeline, not processMotionEvent
2. `SoFieldSensor` + focalDistance Python addon — worked but conflicted with C++ patches
3. BBox center as rotation pivot — `SoGetBoundingBoxAction` too expensive at 60Hz
4. `SoMotion3Event` interception via `SoEventCallback` — events never reach scene graph
5. Separate spnav connection — `spnav_open()` allows only ONE connection per process
6. Timer-based reconnect for #17809 — too complex for FreeCAD's minimal spnav design
7. Global `invoke(1)` in `runCommandByName()` for #10073 — ~60 call sites, ActionGroup commands use `iMsg` as index

### Relevant FreeCAD Issues

- [#10073](https://github.com/FreeCAD/FreeCAD/issues/10073) — SpaceBall buttons don't toggle camera
- [#17809](https://github.com/FreeCAD/FreeCAD/issues/17809) — 100% CPU when spacenavd stops
- [#17812](https://github.com/FreeCAD/FreeCAD/issues/17812) — Wrong button assignment in preferences
- [#9543](https://github.com/FreeCAD/FreeCAD/issues/9543) — SpaceMouse rotation center
- [#6214](https://github.com/FreeCAD/FreeCAD/issues/6214) — 3D view jumps on switch
- [#19366](https://github.com/FreeCAD/FreeCAD/issues/19366) — Reset button design issue
