# FreeCAD SpaceMouse Fix — Technical Reference

This document covers the technical details of the FreeCAD SpaceMouse patch. For the step-by-step installation guide, see the [README](../README.md#freecad-spacemouse-fix).

---

## Root Cause

FreeCAD's SpaceMouse event handling on Linux has two performance bugs (present since 2018):

### Bug 1: No Event Coalescing

The SpaceMouse sends motion data at 125–250 Hz. FreeCAD's `pollSpacenav()` drains **all** pending events from the socket and posts **each one individually** as a separate Qt event. When spacenavd buffers 5 events while FreeCAD is busy rendering, all 5 arrive at once — each triggering a full scene redraw.

**File:** `src/Gui/3Dconnexion/GuiNativeEventLinux.cpp`

### Bug 2: Double Redraws Per Event

Inside `processMotionEvent()`, changing `camera->orientation` and `camera->position` each triggers a **separate** Coin3D scene redraw notification. That's 2 redraws per event — at 250 Hz, up to 500 redraws per second.

**File:** `src/Gui/NavigationStyle.cpp` (or `src/Gui/Navigation/NavigationStyle.cpp` in some versions)

### Combined Effect

At full deflection: 250 events/sec × 2 redraws = **500 redraws/sec**. The renderer can't keep up, frames get dropped, and navigation feels jerky.

---

## What the Patch Changes

The patch is **+13 lines** across 2 files:

### Fix 1: Event Coalescing

Instead of posting every event individually, the drain loop keeps only the **latest** motion state and posts it **once** per poll cycle. SpaceMouse events represent the current puck deflection (not accumulated deltas), so the latest event always contains the complete state.

```diff
 void Gui::GuiNativeEvent::pollSpacenav()
 {
     spnav_event ev;
+    bool hasMotion = false;
     while (spnav_poll_event(&ev)) {
         switch (ev.type) {
             case SPNAV_EVENT_MOTION: {
                 motionDataArray[0] = -ev.motion.x;
                 // ... axis mapping unchanged ...
                 motionDataArray[5] = -ev.motion.ry;
-                mainApp->postMotionEvent(motionDataArray);
+                hasMotion = true;
                 break;
             }
             // button handling unchanged
         }
     }
+    if (hasMotion) {
+        mainApp->postMotionEvent(motionDataArray);
+    }
 }
```

### Fix 2: Batched Camera Updates

Camera property changes are wrapped in `enableNotify(false)` / `enableNotify(true)` + `touch()`, so orientation and position updates trigger a **single** Coin3D redraw instead of two.

```diff
+    newRotation.multVec(dir, dir);
+    SbVec3f finalPosition = newPosition + (dir * translationFactor);
+
+    camera->enableNotify(false);
     camera->orientation.setValue(newRotation);
-    camera->orientation.getValue().multVec(dir, dir);
-    camera->position = newPosition + (dir * translationFactor);
+    camera->position = finalPosition;
+    camera->enableNotify(true);
+    camera->touch();
```

### Result

- ~60 redraws/sec instead of ~500 (matches display refresh rate)
- Smooth, responsive rotation, panning, and zooming
- Instant stop when the puck is released (no drift)
- Zero behavior changes — same rotation/translation math as upstream

---

## Alternative Build Methods

### Method A: Arch Linux Package (Recommended)

See the [README installation guide](../README.md#step-2-build-patched-freecad).

---

### Method B: Build from Source

If you're not on Arch, or want to keep the patched version separate from your system FreeCAD:

**1. Clone FreeCAD source:**

```bash
./scripts/freecad-build-patched.sh --clone 1.0.2
```

Replace `1.0.2` with your desired version tag.

**2. Build:**

```bash
./scripts/freecad-build-patched.sh
```

**3. Run the patched version:**

```bash
./freecad-build/build/bin/FreeCAD
```

> The system FreeCAD (`/usr/bin/freecad`) remains untouched with this method.

---

### Method C: Manual Patching (Any Version)

If you already have a FreeCAD source tree (any version):

```bash
python3 freecad-patches/apply-spacemouse-fix.py /path/to/freecad-source
```

This script automatically finds the files to patch regardless of directory structure. It searches for the exact code patterns rather than relying on file paths or line numbers.

To check if the patch can be applied without modifying anything:

```bash
python3 freecad-patches/apply-spacemouse-fix.py --check /path/to/freecad-source
```

Then build FreeCAD as you normally would.

---

## Troubleshooting

### SpaceMouse not detected in FreeCAD

```bash
# Check spacenavd is running
systemctl status spacenavd

# Check the socket exists
ls -la /var/run/spnav.sock

# Run the diagnostic tool
spacemouse-test --check
```

### Navigation works but axes are wrong

Run `./scripts/freecad-spacemouse-patch.sh` to set FlipYZ and axis enables correctly.
You can also adjust per-axis settings in FreeCAD: **Edit > Preferences > Spaceball > Motion**.

### FreeCAD crashes on startup after patching

The patch only changes event handling, not core functionality. If FreeCAD crashes, it's likely a build configuration issue:

```bash
cd freecad-pacman-build
makepkg -sfCi      # -C cleans build dir first
```

### Patch doesn't apply cleanly

Use the Python patch script instead of the `.patch` file — it finds the correct code patterns automatically:

```bash
python3 freecad-patches/apply-spacemouse-fix.py /path/to/freecad-source
```

If this also fails, the code may have been significantly refactored. The changes are simple enough to apply by hand — see the diffs above.

---

## Compatibility

| FreeCAD Version | Status |
|-----------------|--------|
| 1.0.x | Tested, works |
| 0.21.x | Should work (same code since 2018) |
| 1.1.x / 1.2.x | Should work (affected code unchanged) |

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

Relevant FreeCAD issues:
- [#9543](https://github.com/FreeCAD/FreeCAD/issues/9543) — SpaceMouse rotation center
- [#27132](https://github.com/FreeCAD/FreeCAD/issues/27132) — SpaceMouse broken in FreeCAD 1.1/1.2
