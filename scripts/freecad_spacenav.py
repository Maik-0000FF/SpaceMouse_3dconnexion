# -*- coding: utf-8 -*-
"""
FreeCAD SpaceMouse Navigation Fix for Linux
============================================
Standalone version — run in FreeCAD Python console:
  exec(open("/path/to/freecad_spacenav.py").read())
  spacenav_stop()   # to disable

For auto-loading, install the SpaceNavFix addon instead:
  cp -r freecad-addon/SpaceNavFix ~/.local/share/FreeCAD/Mod/

Fixes:
1. ROTATION CENTER: Adjusts camera focalDistance so rotation pivot =
   bounding box center of visible objects (like NavLib on Win/Mac).
2. SENSITIVITY: Reduces GlobalSensitivity at runtime.
3. BUTTONS: SoEventCallback fallback for spaceball button handling.

Prerequisites:
  - LegacySpaceMouseDevices = 1 in user.cfg
  - spacenavd running
  - A document with a 3D view open
"""

from pivy import coin
import FreeCAD
import FreeCADGui

try:
    from PySide6.QtCore import QTimer
except ImportError:
    from PySide2.QtCore import QTimer

# ── Configuration ─────────────────────────────────────────────────

SENSITIVITY = -40
PIVOT_UPDATE_MS = 50

BUTTON_DEFAULTS = {
    0: "Std_ViewFitAll",
    1: "Std_ViewHome",
}

# ── State ────────────────────────────────────────────────────────

_timer = None
_active = False
_prev_sensitivity = None
_button_cb_node = None
_button_map = {}

# ── Core: Dynamic Pivot Point ────────────────────────────────────

def _update_pivot():
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
    orient = cam.orientation.getValue()
    direction = coin.SbVec3f()
    orient.multVec(coin.SbVec3f(0, 0, -1), direction)

    dx = center[0] - cam_pos[0]
    dy = center[1] - cam_pos[1]
    dz = center[2] - cam_pos[2]

    focal_dist = (dx * direction[0] +
                  dy * direction[1] +
                  dz * direction[2])

    if focal_dist > 0.001:
        cam.focalDistance.setValue(focal_dist)


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
        action = coin.SoGetBoundingBoxAction(
            coin.SbViewportRegion(1, 1)
        )
        action.apply(sg)
        bbox = action.getBoundingBox()
        if bbox.isEmpty():
            return None
        return bbox.getCenter()
    except Exception:
        return None


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
        FreeCAD.Console.PrintLog(f"SpaceNavFix: Button {bnum} -> {cmd}\n")
        try:
            FreeCADGui.runCommand(cmd)
        except Exception as e:
            FreeCAD.Console.PrintWarning(
                f"SpaceNavFix: Command '{cmd}' failed: {e}\n"
            )
        event_cb.setHandled()


def _install_button_handler():
    global _button_cb_node
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        sg = view.getSceneGraph()
    except Exception:
        return False

    if not hasattr(coin, 'SoSpaceballButtonEvent'):
        FreeCAD.Console.PrintWarning(
            "SpaceNavFix: SoSpaceballButtonEvent not in pivy.\n"
        )
        return False

    _load_button_map()
    _button_cb_node = coin.SoEventCallback()
    _button_cb_node.addEventCallback(
        coin.SoSpaceballButtonEvent.getClassTypeId(),
        _handle_spaceball_button
    )
    sg.insertChild(_button_cb_node, 0)
    return True


def _remove_button_handler():
    global _button_cb_node
    if _button_cb_node is None:
        return
    try:
        view = FreeCADGui.ActiveDocument.ActiveView
        sg = view.getSceneGraph()
        idx = sg.findChild(_button_cb_node)
        if idx >= 0:
            sg.removeChild(idx)
    except Exception:
        pass
    _button_cb_node = None


# ── Start / Stop ─────────────────────────────────────────────────

def spacenav_start():
    global _timer, _active, _prev_sensitivity

    if _active:
        FreeCAD.Console.PrintMessage("SpaceNav Fix: Already running.\n")
        return

    try:
        FreeCADGui.ActiveDocument.ActiveView.getCameraNode()
    except Exception:
        FreeCAD.Console.PrintError(
            "SpaceNav: No active 3D view. Open a document first.\n"
        )
        return

    grp = FreeCAD.ParamGet(
        "User parameter:BaseApp/Preferences/Spaceball/Motion"
    )
    _prev_sensitivity = grp.GetInt("GlobalSensitivity", 0)
    grp.SetInt("GlobalSensitivity", SENSITIVITY)

    _timer = QTimer()
    _timer.timeout.connect(_update_pivot)
    _timer.start(PIVOT_UPDATE_MS)
    _update_pivot()
    _active = True

    btn_ok = _install_button_handler()
    btn_status = "Coin3D callback" if btn_ok else "native only"

    FreeCAD.Console.PrintMessage(
        f"SpaceNav Fix: Active\n"
        f"  Rotation pivot = scene/selection center\n"
        f"  Sensitivity: {_prev_sensitivity} -> {SENSITIVITY}\n"
        f"  Buttons: {btn_status}\n"
        f"  spacenav_stop() to disable\n"
    )


def spacenav_stop():
    global _timer, _active, _prev_sensitivity

    if not _active:
        FreeCAD.Console.PrintMessage("SpaceNav: Not running.\n")
        return

    if _timer:
        _timer.stop()
        _timer = None

    _remove_button_handler()

    if _prev_sensitivity is not None:
        grp = FreeCAD.ParamGet(
            "User parameter:BaseApp/Preferences/Spaceball/Motion"
        )
        grp.SetInt("GlobalSensitivity", _prev_sensitivity)

    _active = False
    FreeCAD.Console.PrintMessage("SpaceNav Fix: Stopped.\n")


# ── Auto-start (standalone mode) ─────────────────────────────────

spacenav_start()
