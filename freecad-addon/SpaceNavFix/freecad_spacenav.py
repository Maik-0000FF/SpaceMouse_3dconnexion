# -*- coding: utf-8 -*-
"""
FreeCAD SpaceMouse Navigation Fix for Linux
============================================
Intercepts SoMotion3Event from the Coin3D scene graph and applies
own camera logic with rotation around scene/selection center.

Completely replaces FreeCAD's broken processMotionEvent() which
rotates around an arbitrary point and has no smoothing.
"""

from pivy import coin
import FreeCAD
import FreeCADGui
import math

try:
    from PySide6.QtCore import QTimer
except ImportError:
    from PySide2.QtCore import QTimer

# ── Configuration ─────────────────────────────────────────────────

ROTATION_SPEED = 0.6        # Rotation multiplier (1.0 = raw, 0.5 = half)
TRANSLATION_SPEED = 0.0003  # Pan speed multiplier
ZOOM_SPEED = 0.0005         # Zoom speed multiplier
DEADZONE = 0.05             # Ignore input below this threshold (0-1 range)
SMOOTHING = 0.4             # Exponential smoothing (0 = raw, 0.9 = very smooth)
SHOW_PIVOT_MARKER = True
MAX_DISTANCE_FACTOR = 15.0  # Camera max distance = factor * scene size

BUTTON_DEFAULTS = {
    0: "Std_ViewFitAll",
    1: "Std_ViewHome",
}

# ── State ────────────────────────────────────────────────────────

_active = False
_motion_cb_node = None
_button_cb_node = None
_button_map = {}
_pivot_node = None
_pivot_translation = None
_pivot_scale = None
_pivot_timer = None

# Smoothing state
_smooth_tx = 0.0
_smooth_ty = 0.0
_smooth_tz = 0.0
_smooth_rx = 0.0
_smooth_ry = 0.0
_smooth_rz = 0.0

# ── Pivot Marker ─────────────────────────────────────────────────

def _create_pivot_marker():
    global _pivot_node, _pivot_translation, _pivot_scale

    anno = coin.SoAnnotation()
    sep = coin.SoSeparator()

    _pivot_translation = coin.SoTranslation()
    sep.addChild(_pivot_translation)

    _pivot_scale = coin.SoScale()
    sep.addChild(_pivot_scale)

    mat = coin.SoBaseColor()
    mat.rgb.setValue(1.0, 0.4, 0.0)
    sep.addChild(mat)

    style = coin.SoDrawStyle()
    style.lineWidth.setValue(2)
    sep.addChild(style)

    # 3-axis cross
    coords = coin.SoCoordinate3()
    coords.point.setNum(6)
    coords.point.set1Value(0, -1, 0, 0)
    coords.point.set1Value(1, 1, 0, 0)
    coords.point.set1Value(2, 0, -1, 0)
    coords.point.set1Value(3, 0, 1, 0)
    coords.point.set1Value(4, 0, 0, -1)
    coords.point.set1Value(5, 0, 0, 1)
    sep.addChild(coords)

    lines = coin.SoLineSet()
    lines.numVertices.setNum(3)
    lines.numVertices.set1Value(0, 2)
    lines.numVertices.set1Value(1, 2)
    lines.numVertices.set1Value(2, 2)
    sep.addChild(lines)

    anno.addChild(sep)
    _pivot_node = anno
    return anno


def _update_pivot_marker(center, cam_pos):
    if _pivot_translation is None:
        return
    _pivot_translation.translation.setValue(center)
    if _pivot_scale is not None:
        dx = center[0] - cam_pos[0]
        dy = center[1] - cam_pos[1]
        dz = center[2] - cam_pos[2]
        dist = (dx*dx + dy*dy + dz*dz) ** 0.5
        s = max(dist * 0.025, 0.3)
        _pivot_scale.scaleFactor.setValue(s, s, s)


def _update_pivot_visual():
    """Timer callback to update pivot marker position."""
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        sg = view.getSceneGraph()
    except Exception:
        return

    center = _get_selection_center()
    if center is None:
        center = _get_scene_center(sg)
    if center is None:
        return

    cam_pos = cam.position.getValue()
    _update_pivot_marker(center, cam_pos)


# ── Scene Queries ────────────────────────────────────────────────

def _get_selection_center():
    sel = FreeCADGui.Selection.getSelection()
    if not sel:
        return None

    xmin = ymin = zmin = float('inf')
    xmax = ymax = zmax = float('-inf')
    found = False

    for obj in sel:
        try:
            if hasattr(obj, 'Shape') and not obj.Shape.isNull():
                bb = obj.Shape.BoundBox
            elif hasattr(obj, 'Mesh') and obj.Mesh.CountPoints > 0:
                bb = obj.Mesh.BoundBox
            else:
                continue
            if bb.XLength <= 0 and bb.YLength <= 0 and bb.ZLength <= 0:
                continue
            xmin = min(xmin, bb.XMin)
            ymin = min(ymin, bb.YMin)
            zmin = min(zmin, bb.ZMin)
            xmax = max(xmax, bb.XMax)
            ymax = max(ymax, bb.YMax)
            zmax = max(zmax, bb.ZMax)
            found = True
        except Exception:
            continue

    if not found:
        return None
    return coin.SbVec3f(
        (xmin + xmax) / 2.0,
        (ymin + ymax) / 2.0,
        (zmin + zmax) / 2.0
    )


def _get_scene_center(sg):
    try:
        action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(1, 1))
        action.apply(sg)
        bbox = action.getBoundingBox()
        if bbox.isEmpty():
            return None
        return bbox.getCenter()
    except Exception:
        return None


def _get_scene_size(sg):
    try:
        action = coin.SoGetBoundingBoxAction(coin.SbViewportRegion(1, 1))
        action.apply(sg)
        bbox = action.getBoundingBox()
        if bbox.isEmpty():
            return 100.0
        bmin = bbox.getMin()
        bmax = bbox.getMax()
        dx = bmax[0] - bmin[0]
        dy = bmax[1] - bmin[1]
        dz = bmax[2] - bmin[2]
        return max((dx*dx + dy*dy + dz*dz) ** 0.5, 0.01)
    except Exception:
        return 100.0


# ── Core: Motion Event Handler ───────────────────────────────────

def _apply_deadzone(value):
    """Apply deadzone — ignore small inputs."""
    if abs(value) < DEADZONE:
        return 0.0
    # Rescale so movement starts at 0 after deadzone
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - DEADZONE) / (1.0 - DEADZONE)


_debug_counter = 0

def _handle_motion3(userdata, event_cb):
    """Intercept SoMotion3Event — replace processMotionEvent entirely."""
    global _smooth_tx, _smooth_ty, _smooth_tz
    global _smooth_rx, _smooth_ry, _smooth_rz
    global _debug_counter

    event = event_cb.getEvent()
    if not event.isOfType(coin.SoMotion3Event.getClassTypeId()):
        return

    trans = event.getTranslation()
    rot = event.getRotation()

    # Extract rotation as axis-angle
    rot_axis = coin.SbVec3f()
    rot_angle = 0.0
    rot_axis, rot_angle = rot.getValue(rot_axis, rot_angle)

    if abs(rot_angle) > 0.0001:
        rx = rot_axis[0] * rot_angle
        ry = rot_axis[1] * rot_angle
        rz = rot_axis[2] * rot_angle
    else:
        rx = ry = rz = 0.0

    tx = trans[0]
    ty = trans[1]
    tz = trans[2]

    # Debug: log raw values every 60 frames
    _debug_counter += 1
    if _debug_counter % 60 == 1:
        FreeCAD.Console.PrintLog(
            f"SpaceNavFix raw: t=({tx:.3f},{ty:.3f},{tz:.3f}) "
            f"r=({rx:.4f},{ry:.4f},{rz:.4f})\n"
        )

    # Apply deadzone
    tx = _apply_deadzone(tx)
    ty = _apply_deadzone(ty)
    tz = _apply_deadzone(tz)
    rx = _apply_deadzone(rx)
    ry = _apply_deadzone(ry)
    rz = _apply_deadzone(rz)

    # ── Dominant mode: only strongest axis group is active ──
    rot_sum = abs(rx) + abs(ry) + abs(rz)
    trans_sum = abs(tx) + abs(ty) + abs(tz)

    if rot_sum > trans_sum:
        # Rotation dominant — suppress all translation
        tx = ty = tz = 0.0
    else:
        # Translation dominant — suppress all rotation
        rx = ry = rz = 0.0

    # Exponential smoothing
    s = SMOOTHING
    _smooth_tx = s * _smooth_tx + (1 - s) * tx
    _smooth_ty = s * _smooth_ty + (1 - s) * ty
    _smooth_tz = s * _smooth_tz + (1 - s) * tz
    _smooth_rx = s * _smooth_rx + (1 - s) * rx
    _smooth_ry = s * _smooth_ry + (1 - s) * ry
    _smooth_rz = s * _smooth_rz + (1 - s) * rz

    tx, ty, tz = _smooth_tx, _smooth_ty, _smooth_tz
    rx, ry, rz = _smooth_rx, _smooth_ry, _smooth_rz

    # Skip if all near zero
    total = abs(tx) + abs(ty) + abs(tz) + abs(rx) + abs(ry) + abs(rz)
    if total < 0.001:
        event_cb.setHandled()
        return

    # ── Get camera and scene ──
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        sg = view.getSceneGraph()
    except Exception:
        return

    # ── Get pivot point ──
    center = _get_selection_center()
    if center is None:
        center = _get_scene_center(sg)
    if center is None:
        event_cb.setHandled()
        return

    cam_pos = cam.position.getValue()
    cam_orient = cam.orientation.getValue()
    scene_size = _get_scene_size(sg)

    # Distance from camera to pivot
    to_center_x = center[0] - cam_pos[0]
    to_center_y = center[1] - cam_pos[1]
    to_center_z = center[2] - cam_pos[2]
    cam_dist = (to_center_x**2 + to_center_y**2 + to_center_z**2) ** 0.5

    # Absolute distance limits
    min_dist = scene_size * 0.05
    max_dist = scene_size * MAX_DISTANCE_FACTOR
    cam_dist = max(cam_dist, min_dist)

    # ── Apply rotation around pivot ──
    rot_magnitude = (rx*rx + ry*ry + rz*rz) ** 0.5
    if rot_magnitude > 0.0001:
        angle = rot_magnitude * ROTATION_SPEED

        # Rotation axis in world space
        axis_cam = coin.SbVec3f(rx / rot_magnitude,
                                ry / rot_magnitude,
                                rz / rot_magnitude)
        axis_world = coin.SbVec3f()
        cam_orient.multVec(axis_cam, axis_world)

        delta_rot = coin.SbRotation(axis_world, angle)
        new_orient = delta_rot * cam_orient

        # Reposition: same distance from pivot, new direction
        new_dir = coin.SbVec3f()
        new_orient.multVec(coin.SbVec3f(0, 0, -1), new_dir)

        cam.orientation.setValue(new_orient)
        cam.position.setValue(
            center[0] - new_dir[0] * cam_dist,
            center[1] - new_dir[1] * cam_dist,
            center[2] - new_dir[2] * cam_dist
        )
        cam_orient = new_orient

    # ── Apply translation (pan) in camera plane ──
    pan_magnitude = abs(tx) + abs(ty)
    if pan_magnitude > 0.001:
        scale = cam_dist * TRANSLATION_SPEED

        right = coin.SbVec3f()
        up = coin.SbVec3f()
        cam_orient.multVec(coin.SbVec3f(1, 0, 0), right)
        cam_orient.multVec(coin.SbVec3f(0, 1, 0), up)

        move_x = tx * scale
        move_y = ty * scale

        pos = cam.position.getValue()
        cam.position.setValue(
            pos[0] + right[0] * move_x + up[0] * move_y,
            pos[1] + right[1] * move_x + up[1] * move_y,
            pos[2] + right[2] * move_x + up[2] * move_y
        )

    # ── Apply zoom ──
    if abs(tz) > 0.001:
        zoom_factor = 1.0 - tz * ZOOM_SPEED
        zoom_factor = max(0.95, min(1.05, zoom_factor))  # Clamp per frame
        new_dist = cam_dist * zoom_factor

        # Absolute clamp
        new_dist = max(min_dist, min(new_dist, max_dist))

        if cam.getTypeId().isDerivedFrom(
                coin.SoOrthographicCamera.getClassTypeId()):
            height = cam.height.getValue()
            cam.height.setValue(height * zoom_factor)
        else:
            fwd = coin.SbVec3f()
            cam_orient.multVec(coin.SbVec3f(0, 0, -1), fwd)
            cam.position.setValue(
                center[0] - fwd[0] * new_dist,
                center[1] - fwd[1] * new_dist,
                center[2] - fwd[2] * new_dist
            )
            cam_dist = new_dist

    # Update focal distance
    cam.focalDistance.setValue(cam_dist)

    # Consume event — don't let processMotionEvent run
    event_cb.setHandled()


# ── Button Handling ──────────────────────────────────────────────

def _load_button_map():
    global _button_map
    _button_map = dict(BUTTON_DEFAULTS)
    try:
        grp = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/Spaceball/Buttons"
        )
        for i in range(16):
            cmd = grp.GetString(str(i), "")
            if cmd:
                _button_map[i] = cmd
    except Exception:
        pass


def _handle_spaceball_button(userdata, event_cb):
    event = event_cb.getEvent()
    if not event.isOfType(coin.SoSpaceballButtonEvent.getClassTypeId()):
        return
    if event.getState() != coin.SoButtonEvent.DOWN:
        return

    button = event.getButton()
    btn_enum_to_num = {
        coin.SoSpaceballButtonEvent.BUTTON1: 0,
        coin.SoSpaceballButtonEvent.BUTTON2: 1,
    }
    for attr in dir(coin.SoSpaceballButtonEvent):
        if attr.startswith('BUTTON') and attr[6:].isdigit():
            num = int(attr[6:]) - 1
            btn_enum_to_num[getattr(coin.SoSpaceballButtonEvent, attr)] = num

    bnum = btn_enum_to_num.get(button)
    if bnum is None:
        return

    cmd = _button_map.get(bnum)
    if cmd:
        FreeCAD.Console.PrintMessage(f"SpaceNavFix: Button {bnum} -> {cmd}\n")
        try:
            FreeCADGui.runCommand(cmd)
        except Exception as e:
            FreeCAD.Console.PrintWarning(f"SpaceNavFix: '{cmd}' failed: {e}\n")
        event_cb.setHandled()


# ── Start / Stop ─────────────────────────────────────────────────

def spacenav_start():
    global _active, _motion_cb_node, _button_cb_node, _pivot_timer

    if _active:
        FreeCAD.Console.PrintMessage("SpaceNavFix: Already running.\n")
        return

    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        sg = view.getSceneGraph()
    except Exception:
        FreeCAD.Console.PrintError(
            "SpaceNavFix: No active 3D view. Open a document first.\n"
        )
        return

    # ── Install motion event interceptor ──
    _motion_cb_node = coin.SoEventCallback()
    _motion_cb_node.addEventCallback(
        coin.SoMotion3Event.getClassTypeId(),
        _handle_motion3
    )
    # Insert at position 0 so we get events BEFORE NavigationStyle
    sg.insertChild(_motion_cb_node, 0)

    # ── Install button handler ──
    btn_ok = False
    if hasattr(coin, 'SoSpaceballButtonEvent'):
        _load_button_map()
        _button_cb_node = coin.SoEventCallback()
        _button_cb_node.addEventCallback(
            coin.SoSpaceballButtonEvent.getClassTypeId(),
            _handle_spaceball_button
        )
        sg.insertChild(_button_cb_node, 0)
        btn_ok = True

    # ── Pivot marker ──
    marker_ok = False
    if SHOW_PIVOT_MARKER:
        _create_pivot_marker()
        try:
            viewer = view.getViewer()
            root = viewer.getSoRenderManager().getSceneGraph()
            root.addChild(_pivot_node)
            marker_ok = True
        except Exception:
            try:
                sg.addChild(_pivot_node)
                marker_ok = True
            except Exception:
                pass

        if marker_ok:
            _pivot_timer = QTimer()
            _pivot_timer.timeout.connect(_update_pivot_visual)
            _pivot_timer.start(100)  # 10fps for visual only

    _active = True

    FreeCAD.Console.PrintMessage(
        f"SpaceNavFix: Active (event interceptor mode)\n"
        f"  Rotation: around scene/selection center\n"
        f"  Smoothing: {SMOOTHING}, Deadzone: {DEADZONE}\n"
        f"  Pivot marker: {'visible' if marker_ok else 'off'}\n"
        f"  Buttons: {'active' if btn_ok else 'native only'}\n"
        f"  spacenav_stop() to disable\n"
    )


def spacenav_stop():
    global _active, _motion_cb_node, _button_cb_node
    global _pivot_node, _pivot_translation, _pivot_scale, _pivot_timer

    if not _active:
        FreeCAD.Console.PrintMessage("SpaceNavFix: Not running.\n")
        return

    if _pivot_timer:
        _pivot_timer.stop()
        _pivot_timer = None

    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        sg = view.getSceneGraph()

        for node in [_motion_cb_node, _button_cb_node]:
            if node is not None:
                idx = sg.findChild(node)
                if idx >= 0:
                    sg.removeChild(idx)

        if _pivot_node is not None:
            # Try viewer root
            try:
                viewer = view.getViewer()
                root = viewer.getSoRenderManager().getSceneGraph()
                idx = root.findChild(_pivot_node)
                if idx >= 0:
                    root.removeChild(idx)
            except Exception:
                idx = sg.findChild(_pivot_node)
                if idx >= 0:
                    sg.removeChild(idx)
    except Exception:
        pass

    _motion_cb_node = None
    _button_cb_node = None
    _pivot_node = None
    _pivot_translation = None
    _pivot_scale = None
    _active = False

    FreeCAD.Console.PrintMessage("SpaceNavFix: Stopped.\n")


def spacenav_status():
    FreeCAD.Console.PrintMessage(
        f"SpaceNavFix Status:\n"
        f"  Active: {_active}\n"
        f"  Motion interceptor: {_motion_cb_node is not None}\n"
        f"  Button handler: {_button_cb_node is not None}\n"
        f"  Pivot marker: {_pivot_node is not None}\n"
        f"  Smoothing: tx={_smooth_tx:.3f} ty={_smooth_ty:.3f} tz={_smooth_tz:.3f}\n"
        f"  Smoothing: rx={_smooth_rx:.4f} ry={_smooth_ry:.4f} rz={_smooth_rz:.4f}\n"
    )
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        FreeCAD.Console.PrintMessage(
            f"  Focal dist: {cam.focalDistance.getValue():.2f}\n"
        )
    except Exception:
        pass


def is_active():
    return _active
