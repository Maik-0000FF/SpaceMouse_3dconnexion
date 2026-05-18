"""WM-class → profile-name matcher.

Pure-logic helper extracted from monitors.WindowMonitor so it can be unit
tested without pulling in PySide6.
"""


# Apps that ship their own SpaceMouse configuration in the GUI (Blender /
# FreeCAD pages). When focused, the daemon must idle so the app's native
# libspnav path handles input. Add a WM-class here whenever a new
# dedicated settings page is introduced.
MANAGED_3D_APPS = (
    "blender",
    "org.freecad.FreeCAD",
    "FreeCAD",
)

PASSTHROUGH_PROFILE = "_passthrough"


def _wm_class_matches(wm_lower, candidate):
    cand_lower = candidate.lower()
    return (
        cand_lower == wm_lower
        or wm_lower.startswith(cand_lower)
        or cand_lower in wm_lower
    )


def find_matching_profile(wm_class, profiles):
    """Find the profile whose match_wm_class entry best fits the window.

    Matches case-insensitively and accepts a profile if any of its
    ``match_wm_class`` entries equals, is a prefix of, or is a substring
    of the window's ``wm_class``. Apps listed in ``MANAGED_3D_APPS``
    resolve to the built-in ``_passthrough`` profile so the daemon stays
    idle while the app's native libspnav path handles input. The
    built-in ``default`` profile is used as a fallback when nothing
    matches.
    """
    wm_lower = wm_class.lower()
    for app in MANAGED_3D_APPS:
        if _wm_class_matches(wm_lower, app):
            return PASSTHROUGH_PROFILE
    for name, profile in profiles.items():
        if name == "default":
            continue
        for wc in profile.get("match_wm_class", []):
            if _wm_class_matches(wm_lower, wc):
                return name
    return "default"
