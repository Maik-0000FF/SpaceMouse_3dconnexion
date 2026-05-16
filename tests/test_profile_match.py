"""Tests for the WM-class → profile-name matcher."""

from spacemouse_config.profile_match import find_matching_profile


PROFILES = {
    "default":    {"match_wm_class": []},
    "blender":    {"match_wm_class": ["blender", "Blender"]},
    "freecad":    {"match_wm_class": ["org.freecad.FreeCAD", "FreeCAD"]},
    "browser":    {"match_wm_class": ["firefox", "chromium"]},
    "filemanager": {"match_wm_class": ["org.kde.dolphin"]},
}


def test_exact_match():
    assert find_matching_profile("blender", PROFILES) == "blender"


def test_case_insensitive():
    assert find_matching_profile("BLENDER", PROFILES) == "blender"
    assert find_matching_profile("Firefox", PROFILES) == "browser"


def test_substring_match():
    # GTK Firefox window often reports "Navigator.firefox" or similar.
    assert find_matching_profile("Navigator.firefox", PROFILES) == "browser"


def test_prefix_match():
    # The FreeCAD WM class on Wayland is org.freecad.FreeCAD; the profile
    # also lists the bare "FreeCAD" string which should match windows
    # that start with that.
    assert find_matching_profile("FreeCAD-1.1", PROFILES) == "freecad"


def test_default_fallback():
    assert find_matching_profile("totally-unknown-app", PROFILES) == "default"


def test_default_profile_is_skipped_as_match_source():
    # Even if someone accidentally adds match_wm_class to "default",
    # the matcher must skip it — default is the fallback, not a target.
    profiles = {
        "default": {"match_wm_class": ["blender"]},
        "blender": {"match_wm_class": ["blender"]},
    }
    assert find_matching_profile("blender", profiles) == "blender"


def test_profile_without_match_wm_class():
    profiles = {
        "default": {},
        "empty":   {},  # no match_wm_class key at all
    }
    assert find_matching_profile("anything", profiles) == "default"


def test_first_match_wins():
    # Dict iteration order is insertion order in CPython 3.7+. The
    # matcher walks profiles in iteration order, so the first profile
    # whose any match_wm_class hits wins.
    profiles = {
        "default": {"match_wm_class": []},
        "a": {"match_wm_class": ["foo"]},
        "b": {"match_wm_class": ["foo"]},
    }
    assert find_matching_profile("foo", profiles) == "a"


def test_empty_profiles():
    assert find_matching_profile("anything", {}) == "default"
