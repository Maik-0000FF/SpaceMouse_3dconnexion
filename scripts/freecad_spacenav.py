# -*- coding: utf-8 -*-
"""
FreeCAD SpaceMouse Navigation Addon
Replaces FreeCAD's basic legacy spacemouse handling with smooth
viewport navigation on Linux, using the same rotation logic as
FreeCAD's mouse navigation (reorientCamera).

Rotation pivot = camera focal point (same as mouse middle-button drag).

Prerequisites:
  - FreeCAD's native SpaceMouse DISABLED (LegacySpaceMouseDevices = 0)
  - spacenavd running, libspnav.so installed

Usage:
  exec(open("/path/to/freecad_spacenav.py").read())
  spacenav_stop()   # to disable
"""

import ctypes

import FreeCAD
import FreeCADGui

from pivy import coin
try:
    from PySide6.QtCore import QTimer
except ImportError:
    from PySide2.QtCore import QTimer

# ── Configuration ─────────────────────────────────────────────────

SMOOTHING = 0.35          # 0=instant, 1=frozen
DEAD_ZONE = 12            # Ignore axis values below this
TRANS_SENSITIVITY = 0.00004
ROT_SENSITIVITY = 0.0004
ZOOM_SENSITIVITY = 0.0004
VELOCITY_EXPONENT = 1.5   # >1 = precise at low speed
FLIP_YZ = True            # Push/pull = zoom
POLL_INTERVAL_MS = 16     # ~60fps

# ── libspnav ctypes ──────────────────────────────────────────────

class _SpnavMotion(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("z", ctypes.c_int),
        ("rx", ctypes.c_int), ("ry", ctypes.c_int), ("rz", ctypes.c_int),
        ("period", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]

class _SpnavButton(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("press", ctypes.c_int),
        ("bnum", ctypes.c_int),
    ]

class _SpnavEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("motion", _SpnavMotion),
        ("button", _SpnavButton),
    ]

# ── State ────────────────────────────────────────────────────────

_smooth = [0.0] * 6
_timer = None
_lib = None

# ── Helpers ──────────────────────────────────────────────────────

def _deadzone(value, dz):
    if abs(value) < dz:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - dz)

def _vcurve(value, exp):
    sign = 1.0 if value >= 0 else -1.0
    return sign * (abs(value) ** exp)

def _get_camera():
    try:
        return FreeCADGui.ActiveDocument.ActiveView.getCameraNode()
    except Exception:
        return None

# ── reorientCamera — exact copy of FreeCAD's C++ logic ──────────

def _reorient_camera(cam, rot):
    """Rotate camera while keeping focal point fixed.
    This is FreeCAD's NavigationStyle::reorientCamera() in Python."""

    # Find global coordinates of focal point
    direction = coin.SbVec3f()
    cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1), direction)

    focal_dist = cam.focalDistance.getValue()
    cam_pos = cam.position.getValue()

    focal_point = coin.SbVec3f(
        cam_pos[0] + focal_dist * direction[0],
        cam_pos[1] + focal_dist * direction[1],
        cam_pos[2] + focal_dist * direction[2]
    )

    # Set new orientation by accumulating the rotation
    new_orient = rot * cam.orientation.getValue()
    cam.orientation.setValue(new_orient)

    # Reposition camera so we're still pointing at the same focal point
    new_direction = coin.SbVec3f()
    cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1), new_direction)

    cam.position.setValue(coin.SbVec3f(
        focal_point[0] - focal_dist * new_direction[0],
        focal_point[1] - focal_dist * new_direction[1],
        focal_point[2] - focal_dist * new_direction[2]
    ))

# ── panCamera — matches FreeCAD's camera-plane panning ───────────

def _pan_camera(cam, dx, dy):
    """Pan camera in its local XY plane, scaled by focal distance."""
    focal_dist = cam.focalDistance.getValue()
    scale = focal_dist * TRANS_SENSITIVITY

    orient = cam.orientation.getValue()

    # Camera right (local X) and up (local Y) vectors
    right = coin.SbVec3f()
    orient.multVec(coin.SbVec3f(1, 0, 0), right)
    up = coin.SbVec3f()
    orient.multVec(coin.SbVec3f(0, 1, 0), up)

    move_x = dx * scale
    move_y = dy * scale

    pos = cam.position.getValue()
    cam.position.setValue(coin.SbVec3f(
        pos[0] + right[0] * move_x + up[0] * move_y,
        pos[1] + right[1] * move_x + up[1] * move_y,
        pos[2] + right[2] * move_x + up[2] * move_y
    ))

# ── zoomCamera — move along view direction ───────────────────────

def _zoom_camera(cam, amount):
    """Zoom by moving camera along its view direction."""
    focal_dist = cam.focalDistance.getValue()

    if cam.getTypeId() == coin.SoOrthographicCamera.getClassTypeId():
        cam.height = cam.height.getValue() * (1.0 - amount * ZOOM_SENSITIVITY)
    else:
        orient = cam.orientation.getValue()
        view_dir = coin.SbVec3f()
        orient.multVec(coin.SbVec3f(0, 0, -1), view_dir)

        move = amount * focal_dist * ZOOM_SENSITIVITY
        pos = cam.position.getValue()
        cam.position.setValue(coin.SbVec3f(
            pos[0] + view_dir[0] * move,
            pos[1] + view_dir[1] * move,
            pos[2] + view_dir[2] * move
        ))
        # Keep focal distance in sync (rotation center follows zoom)
        cam.focalDistance.setValue(max(0.01, focal_dist - move))

# ── Core: Apply SpaceMouse Input ─────────────────────────────────

def _apply_navigation(axes):
    global _smooth

    cam = _get_camera()
    if cam is None:
        return

    tx, ty, tz, rx, ry, rz = axes

    # Flip Y/Z (push/pull = zoom instead of up/down)
    if FLIP_YZ:
        ty, tz = tz, -ty
        ry, rz = rz, -ry

    # Dead zone
    vals = [_deadzone(v, DEAD_ZONE) for v in [tx, ty, tz, rx, ry, rz]]

    # Exponential smoothing (low-pass filter)
    alpha = 1.0 - SMOOTHING
    for i in range(6):
        _smooth[i] = alpha * vals[i] + SMOOTHING * _smooth[i]

    tx, ty, tz, rx, ry, rz = _smooth

    # Skip if near zero
    if all(abs(v) < 0.5 for v in _smooth):
        return

    # Velocity curve
    tx = _vcurve(tx, VELOCITY_EXPONENT)
    ty = _vcurve(ty, VELOCITY_EXPONENT)
    tz = _vcurve(tz, VELOCITY_EXPONENT)
    rx = _vcurve(rx, VELOCITY_EXPONENT)
    ry = _vcurve(ry, VELOCITY_EXPONENT)
    rz = _vcurve(rz, VELOCITY_EXPONENT)

    # ── Rotation ──
    # Build incremental rotation from SpaceMouse axes, then call
    # reorientCamera() — exactly like FreeCAD's mouse navigation.
    #
    # Pitch = around camera local X (tilt forward/back)
    # Yaw   = around world Y (turn left/right, keeps horizon)
    # Roll  = around camera local Z

    if abs(rx) > 0.5 or abs(ry) > 0.5 or abs(rz) > 0.5:
        # Build the combined rotation
        pitch = coin.SbRotation(coin.SbVec3f(1, 0, 0), -rx * ROT_SENSITIVITY)
        roll = coin.SbRotation(coin.SbVec3f(0, 0, 1), rz * ROT_SENSITIVITY)

        # Yaw in world space (pre-multiply), pitch+roll in camera space (post-multiply)
        # This is equivalent to: rot = yaw_world * pitch_local * roll_local
        # But reorientCamera applies as: rot * cam->orientation
        # So we need: rot = inverse(cam_orient) * yaw * cam_orient * pitch * roll
        cam_orient = cam.orientation.getValue()

        # World-space yaw rotation
        yaw_world = coin.SbRotation(coin.SbVec3f(0, 1, 0), ry * ROT_SENSITIVITY)

        # Convert world yaw to camera-local space
        cam_orient_inv = cam_orient.inverse()
        yaw_local = cam_orient_inv * yaw_world * cam_orient

        # Combined local rotation
        combined = yaw_local * pitch * roll

        # reorientCamera expects: new_orient = rot * old_orient
        _reorient_camera(cam, combined)

    # ── Pan ──
    if abs(tx) > 0.5 or abs(ty) > 0.5:
        _pan_camera(cam, tx, -ty)

    # ── Zoom ──
    if abs(tz) > 0.5:
        _zoom_camera(cam, tz)

# ── Button Handling ──────────────────────────────────────────────

def _handle_button(bnum, pressed):
    if not pressed:
        return
    try:
        if bnum == 0:
            FreeCADGui.runCommand("Std_ViewFitAll")
        elif bnum == 1:
            FreeCADGui.runCommand("Std_ViewHome")
    except Exception as e:
        FreeCAD.Console.PrintWarning(f"SpaceNav: button error: {e}\n")

# ── Event Polling ────────────────────────────────────────────────

def _poll_events():
    if _lib is None:
        return

    ev = _SpnavEvent()
    latest_axes = None

    while True:
        ret = _lib.spnav_poll_event(ctypes.byref(ev))
        if ret == 0:
            break
        if ev.type == 1:  # SPNAV_EVENT_MOTION
            latest_axes = [
                ev.motion.x, ev.motion.y, ev.motion.z,
                ev.motion.rx, ev.motion.ry, ev.motion.rz
            ]
        elif ev.type == 2:  # SPNAV_EVENT_BUTTON
            _handle_button(ev.button.bnum, bool(ev.button.press))

    if latest_axes is not None:
        _apply_navigation(latest_axes)
    else:
        # Decay towards zero (smooth deceleration when input stops)
        global _smooth
        decay = SMOOTHING * 0.8
        changed = False
        for i in range(6):
            if abs(_smooth[i]) > 0.5:
                _smooth[i] *= decay
                changed = True
            else:
                _smooth[i] = 0.0
        if changed:
            _apply_navigation([0] * 6)

# ── Start / Stop ─────────────────────────────────────────────────

def spacenav_start():
    global _lib, _timer, _smooth

    if _timer is not None:
        FreeCAD.Console.PrintMessage("SpaceNav: Already running.\n")
        return

    for libname in ["libspnav.so", "libspnav.so.0"]:
        try:
            _lib = ctypes.CDLL(libname)
            break
        except OSError:
            continue
    else:
        FreeCAD.Console.PrintError("SpaceNav: libspnav.so not found!\n")
        return

    if _lib.spnav_open() == -1:
        FreeCAD.Console.PrintError(
            "SpaceNav: Cannot connect to spacenavd.\n"
        )
        _lib = None
        return

    _smooth = [0.0] * 6

    _timer = QTimer()
    _timer.timeout.connect(_poll_events)
    _timer.start(POLL_INTERVAL_MS)

    FreeCAD.Console.PrintMessage(
        "SpaceNav: Started. Using reorientCamera() rotation logic.\n"
        "SpaceNav: Rotation pivot = camera focal point (same as mouse).\n"
        "SpaceNav: Run spacenav_stop() to disable.\n"
    )

def spacenav_stop():
    global _lib, _timer

    if _timer is not None:
        _timer.stop()
        _timer = None

    if _lib is not None:
        _lib.spnav_close()
        _lib = None

    FreeCAD.Console.PrintMessage("SpaceNav: Stopped.\n")

# ── Auto-start ───────────────────────────────────────────────────

spacenav_start()
