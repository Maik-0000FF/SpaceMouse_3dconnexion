"""WM-class → profile-name matcher.

Pure-logic helper extracted from monitors.WindowMonitor so it can be unit
tested without pulling in PySide6.
"""


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

    Whitelist semantics: a profile only fires if its ``match_wm_class``
    explicitly lists the window's class. Anything not listed resolves to
    the built-in ``_passthrough`` profile so the daemon stays idle —
    apps with their own libspnav support (Blender, FreeCAD, OpenSCAD,
    KiCad, ...) are automatically left alone unless the user opts them
    in via a user profile.

    Matches case-insensitively. A profile's entry matches if it equals,
    is a prefix of, or is a substring of the window's ``wm_class``.
    """
    wm_lower = wm_class.lower()
    for name, profile in profiles.items():
        for wc in profile.get("match_wm_class", []):
            if _wm_class_matches(wm_lower, wc):
                return name
    return PASSTHROUGH_PROFILE
