# FreeCAD SpaceMouse Fix for Linux

A minimal patch that fixes jerky, unusable SpaceMouse/SpaceNavigator navigation in FreeCAD on Linux.

## The Problem

If you use a 3Dconnexion SpaceMouse with FreeCAD on Linux, you've probably noticed that the 3D navigation is extremely choppy and laggy — rotating and panning feels broken compared to Blender, where the same device works perfectly.

This is **not** a driver issue. The SpaceMouse hardware, spacenavd, and libspnav all work fine. The bug is inside FreeCAD itself.

## Root Cause

FreeCAD's SpaceMouse event handling on Linux has two performance bugs that have existed since 2018:

### Bug 1: No Event Coalescing

The SpaceMouse sends motion data at 125-250 Hz. FreeCAD's `pollSpacenav()` function drains **all** pending events from the socket and posts **each one individually** as a separate Qt event. When spacenavd buffers 5 events while FreeCAD is busy rendering, all 5 arrive at once — each triggering its own full scene redraw.

Blender doesn't have this problem because it accumulates NDOF input and processes it once per frame.

**File:** `src/Gui/3Dconnexion/GuiNativeEventLinux.cpp`

### Bug 2: Double Redraws Per Event

Inside `processMotionEvent()`, changing `camera->orientation` and `camera->position` each triggers a **separate** Coin3D scene redraw notification. That's 2 redraws per event — at 250 Hz, that's up to 500 redraws per second.

**File:** `src/Gui/NavigationStyle.cpp` (or `src/Gui/Navigation/NavigationStyle.cpp` in some versions)

### Combined Effect

At full SpaceMouse deflection: 250 events/sec x 2 redraws each = **500 redraws/sec**. The renderer can't keep up, frames get dropped, and the navigation feels jerky and unresponsive.

## The Fix

The patch is only **+13 lines** across 2 files:

### Fix 1: Event Coalescing

Instead of posting every spnav event individually, the drain loop now keeps only the **latest** motion state and posts it **once** per poll cycle. SpaceMouse events represent the current puck deflection (not accumulated deltas), so the latest event always contains the complete current state.

### Fix 2: Batched Camera Updates

Camera property changes are wrapped in `enableNotify(false)` / `enableNotify(true)` + `touch()`, so orientation and position updates trigger a **single** Coin3D redraw instead of two.

### Result

- ~60 redraws/sec instead of ~500 (matches display refresh rate)
- Smooth, responsive rotation, panning, and zooming
- Instant stop when the puck is released (no drift)
- Zero behavior changes — same rotation/translation math as upstream

---

## Installation

### Prerequisites

You need a working spacenavd setup:

```bash
# Arch Linux
sudo pacman -S libspnav
yay -S spacenavd    # or: paru -S spacenavd

# Enable and start the daemon
sudo systemctl enable --now spacenavd
```

Verify your SpaceMouse is detected:

```bash
# Check USB device
lsusb | grep -i 3dconnexion

# Check spacenavd is running
systemctl status spacenavd
```

### Step 1: Configure FreeCAD for SpaceMouse

FreeCAD needs specific settings in `user.cfg` to work with spacenavd. This script sets them automatically:

```bash
./scripts/freecad-spacemouse-patch.sh
```

**What it does:**
- Enables `LegacySpaceMouseDevices` (required for spacenavd on Linux)
- Sets Blender navigation style with Trackball orbit
- Enables all 6 axes (pan, zoom, tilt, roll, spin)
- Enables FlipYZ for intuitive zoom direction
- Maps buttons to Fit All and Home View

> **Note:** FreeCAD must have been started at least once before running this script (it needs an existing `user.cfg`).

To undo all changes: `./scripts/freecad-spacemouse-patch.sh --restore`

### Step 2: Build Patched FreeCAD

Choose **one** of the methods below.

---

#### Method A: Arch Linux Package (Recommended)

This builds a proper pacman package that replaces the system FreeCAD. It's managed by pacman like any other package.

**1. Install build dependencies:**

```bash
# If FreeCAD is not currently installed, install it first to pull in all dependencies
sudo pacman -S freecad

# Install additional build tools
sudo pacman -S base-devel cmake ninja git
```

**2. Build the package:**

Open a terminal and run:

```bash
cd freecad-pacman-build
makepkg -sf -s
```

What the flags mean:
- `-s` = automatically install missing build dependencies (will ask for your sudo password)
- `-f` = overwrite any previous build output

This downloads the FreeCAD source code, applies all patches (including the SpaceMouse fix), and compiles everything. **This takes 15-45 minutes** depending on your CPU. You'll see lots of compiler output — that's normal. Just wait until it finishes.

When it's done, you'll see a file like `freecad-1.0.2-8-x86_64.pkg.tar.zst` in the directory.

**3. Install the package:**

```bash
sudo pacman -U freecad-1.0.2-8-x86_64.pkg.tar.zst
```

(The exact filename may differ — use tab-completion or `ls *.pkg.tar.zst` to find it.)

**4. Done!** Launch FreeCAD normally:

```bash
freecad
```

> **After a system update** (`pacman -Syu`) that upgrades FreeCAD, simply rebuild:
> ```bash
> cd freecad-pacman-build
> # Update PKGBUILD if needed (check Arch GitLab for new version)
> makepkg -sf -s
> sudo pacman -U freecad-*.pkg.tar.zst
> ```

---

#### Method B: Build from Source

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

#### Method C: Manual Patching (Any Version)

If you already have a FreeCAD source tree (any version):

```bash
python3 freecad-patches/apply-spacemouse-fix.py /path/to/freecad-source
```

This script **automatically finds** the files to patch regardless of directory structure. It works by searching for the exact code patterns rather than relying on file paths or line numbers.

To check if the patch can be applied without modifying anything:

```bash
python3 freecad-patches/apply-spacemouse-fix.py --check /path/to/freecad-source
```

Then build FreeCAD as you normally would.

---

### Step 3: Adjust Sensitivity (Optional)

After launching FreeCAD, if the SpaceMouse feels too fast or too slow, open the Python console (**View > Panels > Python console**) and run:

```python
p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Spaceball/Motion")
p.SetInt("GlobalSensitivity", -15)
```

**Sensitivity scale:**
| Value | Effect |
|-------|--------|
| -50 | Very slow (1% of raw input) |
| -30 | Slow |
| -15 | Moderate (good starting point) |
| 0 | Default (100% raw input) |
| +25 | Fast |
| +50 | Very fast |

The change takes effect immediately — no restart needed. Adjust until it feels right for your workflow.

---

## What the Patch Changes

The patch modifies exactly two files. Here's the complete diff:

### `src/Gui/3Dconnexion/GuiNativeEventLinux.cpp`

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

**Before:** Every motion event posted individually (N events per poll = N Qt events = N redraws).
**After:** Only the latest motion state posted once per poll cycle.

### `src/Gui/NavigationStyle.cpp`

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

**Before:** Two separate Coin3D notifications (orientation + position = 2 redraws).
**After:** Notifications suppressed during update, single `touch()` at the end (1 redraw).

---

## Troubleshooting

### SpaceMouse not detected in FreeCAD

```bash
# Check spacenavd is running
systemctl status spacenavd

# Check the socket exists
ls -la /var/run/spnav.sock

# Test with the diagnostic tool from this repo
spacemouse-test --check
```

### Navigation works but axes are wrong

Run `./scripts/freecad-spacemouse-patch.sh` to set FlipYZ and axis enables correctly.
You can also adjust per-axis settings in FreeCAD: **Edit > Preferences > Spaceball > Motion**.

### FreeCAD crashes on startup after patching

The patch only changes event handling, not core functionality. If FreeCAD crashes, it's likely a build configuration issue. Try:

```bash
# Clean rebuild
cd freecad-pacman-build
makepkg -sfC -s    # -C cleans build dir first
sudo pacman -U freecad-*.pkg.tar.zst
```

### Patch doesn't apply cleanly

Use the Python patch script instead of the `.patch` file — it finds the correct code patterns automatically regardless of FreeCAD version or directory structure:

```bash
python3 freecad-patches/apply-spacemouse-fix.py /path/to/freecad-source
```

If this also fails, the code may have been significantly refactored in your FreeCAD version. The changes are simple enough to apply by hand — see the diff in the section above.

### SpaceMouse works in Blender but not FreeCAD

This is the exact problem this patch fixes. Blender handles NDOF input correctly by design. FreeCAD's Linux event pipeline has the coalescing bug described above.

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

The relevant FreeCAD issues:
- [#9543](https://github.com/FreeCAD/FreeCAD/issues/9543) — SpaceMouse rotation center (open since May 2023)
- [#27132](https://github.com/FreeCAD/FreeCAD/issues/27132) — SpaceMouse broken in FreeCAD 1.1/1.2

---

## Files in This Repo

```
freecad-patches/
  apply-spacemouse-fix.py               Version-independent patch script
  spacemouse-smooth-navigation.patch    Static patch for FreeCAD 1.0.2 (git format)

freecad-pacman-build/
  PKGBUILD                              Arch Linux package build (uses patch script)
  apply-spacemouse-fix.py               Copy of patch script for makepkg
  fix-opencascade-7.9.patch             Arch upstream patch
  boost-1.89.patch                      Arch upstream patch

scripts/
  freecad-spacemouse-patch.sh           Configures FreeCAD user.cfg
  freecad-build-patched.sh              Builds from source with patch
  freecad-pacman-build.sh               Builds Arch package with patch

docs/
  FREECAD_SPACEMOUSE_FIX.md             This file
```
