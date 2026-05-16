"""WM-class → profile-name matcher.

Pure-logic helper extracted from monitors.WindowMonitor so it can be unit
tested without pulling in PySide6.
"""


def find_matching_profile(wm_class, profiles):
    """Find the profile whose match_wm_class entry best fits the window.

    Matches case-insensitively and accepts a profile if any of its
    ``match_wm_class`` entries equals, is a prefix of, or is a substring
    of the window's ``wm_class``. The built-in ``default`` profile is
    used as a fallback when nothing matches.
    """
    wm_lower = wm_class.lower()
    for name, profile in profiles.items():
        if name == "default":
            continue
        for wc in profile.get("match_wm_class", []):
            wc_lower = wc.lower()
            if (wc_lower == wm_lower or
                wm_lower.startswith(wc_lower) or
                wc_lower in wm_lower):
                return name
    return "default"
