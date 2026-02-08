# -*- coding: utf-8 -*-
"""
SpaceNavFix — Auto-loading FreeCAD Addon
Polls for a 3D view and starts the SpaceMouse fix when one is available.
"""

import FreeCAD
import FreeCADGui


def _try_activate():
    """Check if a 3D view is available and start the fix."""
    global _poll_timer, _started

    if _started:
        if _poll_timer is not None:
            _poll_timer.stop()
        return

    # Check for active 3D view
    try:
        doc = FreeCADGui.ActiveDocument
        if doc is None:
            return
        view = doc.ActiveView
        if view is None:
            return
        view.getCameraNode()
    except Exception:
        return

    # 3D view is ready — start the fix
    try:
        import freecad_spacenav
        freecad_spacenav.spacenav_start()
        _started = True
        if _poll_timer is not None:
            _poll_timer.stop()
    except Exception as e:
        FreeCAD.Console.PrintError(f"SpaceNavFix: {e}\n")


_started = False
_poll_timer = None

try:
    from PySide6.QtCore import QTimer
except ImportError:
    from PySide2.QtCore import QTimer

_poll_timer = QTimer()
_poll_timer.timeout.connect(_try_activate)
_poll_timer.start(2000)  # Check every 2 seconds

FreeCAD.Console.PrintMessage("SpaceNavFix: Loaded. Waiting for 3D view...\n")
