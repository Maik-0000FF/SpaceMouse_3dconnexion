"""
Blender startup script for SpaceMouse NDOF sync.

Install to: ~/.config/blender/5.0/scripts/startup/
Reads settings from ~/.config/spacemouse/blender-ndof.json
and applies them to Blender's NDOF input preferences on startup.
"""

import bpy
import json
import os

CONFIG = os.path.expanduser("~/.config/spacemouse/blender-ndof.json")


def sync_ndof_settings():
    """Read blender-ndof.json and apply to bpy.context.preferences.inputs."""
    if not os.path.exists(CONFIG):
        return
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    prefs = bpy.context.preferences.inputs
    for key, value in cfg.items():
        if hasattr(prefs, key):
            try:
                setattr(prefs, key, value)
            except (TypeError, AttributeError):
                pass


def _deferred_sync():
    """Deferred sync — bpy.context is not ready at import time."""
    sync_ndof_settings()
    return None  # Don't repeat


bpy.app.timers.register(_deferred_sync, first_interval=1.0, persistent=False)
