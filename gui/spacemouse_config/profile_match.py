"""WM-class → profile-name matcher.

Pure-logic helper extracted from monitors.WindowMonitor so it can be unit
tested without pulling in PySide6.
"""


def _wm_class_matches(wm_lower, candidate):
    cand_lower = candidate.lower()
    return cand_lower == wm_lower or wm_lower.startswith(cand_lower) or cand_lower in wm_lower


def find_matching_profile(wm_class, profiles):
    """Find the profile whose match_wm_class entry best fits the window.

    Walks user profiles in dict order. The first profile whose
    ``match_wm_class`` contains a string that equals, prefixes, or is a
    substring of ``wm_class`` (case-insensitive) wins. ``default`` is
    skipped during the loop and used as the catch-all fallback when
    nothing else matches.

    The matcher returns profile names only. Passthrough behavior is a
    daemon-side concern, auto-triggered when a profile has all axes and
    buttons set to ``none`` — see ``src/config.c``.
    """
    wm_lower = wm_class.lower()
    for name, profile in profiles.items():
        if name == "default":
            continue
        for wc in profile.get("match_wm_class", []):
            if _wm_class_matches(wm_lower, wc):
                return name
    return "default"
