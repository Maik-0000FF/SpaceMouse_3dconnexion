# FreeCAD SpaceMouse Patch — Development Log

## Status: WORKING (2026-02-11)

Two minimal C++ patches fix jerky SpaceMouse navigation on Linux.
The SpaceNavFix Python addon is no longer needed and has been disabled.

## Root Cause

FreeCAD's SpaceMouse event pipeline on Linux has two performance bugs:

1. **No event coalescing** — `pollSpacenav()` posts every spnav event (125-250Hz)
   individually via Qt, each triggering a separate `processMotionEvent()` + Coin3D redraw
2. **Double redraws per event** — `camera->orientation` and `camera->position` each
   trigger separate Coin3D notifications = 2 redraws per event

Combined: up to 500 redraws/sec. The renderer can't keep up, causing stutter.
Blender doesn't have this problem because it accumulates NDOF input once per frame.

On Windows/macOS, FreeCAD uses the NavLib SDK (handles smoothing internally).
On Linux, NavLib is disabled in CMake — the legacy spnav path is used instead.

## Patches

### Patch 1: Event Coalescing (`GuiNativeEventLinux.cpp`)

Only post the **last** motion event per `QSocketNotifier` activation instead of each one.
spnav motion events represent current puck deflection, not accumulated deltas.

### Patch 2: Batched Camera Updates (`NavigationStyle.cpp`)

Wrap camera property changes in `enableNotify(false/true)` + `touch()` to trigger
a single Coin3D redraw instead of two.

**Patch file:** `freecad-patches/spacemouse-smooth-navigation.patch` (+13/-3 lines)

## Event Pipeline Reference

```
SpaceMouse (USB HID)
    -> spacenavd (daemon, /var/run/spnav.sock, 125-250Hz)
    -> libspnav fd
    -> QSocketNotifier::activated
    -> pollSpacenav()                    <- PATCH 1: Coalescing
        -> postMotionEvent()
            -> importSettings()          (Sensitivity, Calibration, Axis enable)
            -> Spaceball::MotionEvent
            -> QApplication::postEvent()
    -> Qt Event Loop
    -> GUIApplication::notify()
    -> SpaceNavigatorDevice::translateEvent()
        -> Rotation: int * 0.0001 -> Radians
        -> SoMotion3Event
    -> NavigationStyle::processMotionEvent()  <- PATCH 2: Batched Updates
        -> Camera orientation + position
        -> Single Coin3D redraw
```

## Failed Approaches

### 1. Custom processMotionEvent() with Deadzone/Smoothing/Curves
- Added custom deadzone, exponential smoothing, non-linear curve, extra scaling
- Fought against `importSettings()` sensitivity pipeline
- Caused lag (smoothing state takes time to drain) and drift
- Root cause was the event pipeline, not `processMotionEvent()`

### 2. SoFieldSensor + focalDistance (Python Addon v2)
- SoFieldSensor on camera.position fired after every processMotionEvent
- Set focalDistance = projection of BBox center onto view direction
- Worked but conflicted with C++ patches and added overhead

### 3. BBox Center as Rotation Pivot (in processMotionEvent)
- SoGetBoundingBoxAction every frame: too expensive (scene graph traversal at 60Hz)
- Even cached (every 30 frames) still problematic
- reorientCamera() has orthographic special case that overrides camera position
- Focal distance updates created feedback loop with getWorldToScreenScale()

### 4. SoMotion3Event Interception via SoEventCallback (dead end)
- SoMotion3Events never reach the scene graph (BlenderNavStyle sets processed=true)

### 5. Separate spnav connection (dead end)
- `spnav_open() = -1` — libspnav allows only ONE connection per process

## Configuration

### FreeCAD Sensitivity
```python
# In FreeCAD Python console (View > Panels > Python console):
p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Spaceball/Motion")
p.SetInt("GlobalSensitivity", -15)   # -50 (slow) to +50 (fast)
```

### user.cfg settings
- LegacySpaceMouseDevices = 1
- NavigationStyle = Gui::BlenderNavigationStyle
- OrbitStyle = 1 (Trackball), RotationMode = 2
- FlipYZ = 1, all 6 axes enabled
- Buttons: 0=Std_ViewFitAll, 1=Std_ViewHome

### spnavrc
- sensitivity=1.5, dead-zone=5

## Build

```bash
# Arch Linux package
cd freecad-pacman-build && makepkg -sf -s
sudo pacman -U freecad-*.pkg.tar.zst

# Or from source
cd freecad-build/build && ninja -j$(nproc) bin/FreeCAD
```

## System Environment
- Arch Linux, KDE Plasma (Wayland)
- FreeCAD 1.0.2
- spacenavd (AUR), libspnav
- Hardware: 3Dconnexion SpaceNavigator (046d:c626)

## References
- FreeCAD `GuiNativeEventLinux.cpp` — pollSpacenav() event loop (line 66)
- FreeCAD `NavigationStyle.cpp` — processMotionEvent() (line 1912)
- FreeCAD `GuiApplicationNativeEventAware.cpp` — importSettings + Sensitivity
- FreeCAD `View3DInventorViewer.cpp` — SpaceNavigatorDevice event conversion
- [Issue #9543](https://github.com/FreeCAD/FreeCAD/issues/9543): SpaceMouse Rotation Center (open since May 2023)
- [Issue #27132](https://github.com/FreeCAD/FreeCAD/issues/27132): SpaceMouse broken in FreeCAD 1.1/1.2
