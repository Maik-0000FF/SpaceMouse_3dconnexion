"""Tests for the WM-class → profile-name matcher."""

from spacemouse_config.profile_match import PASSTHROUGH_PROFILE, find_matching_profile

PROFILES = {
    "default": {"match_wm_class": []},
    "browser": {"match_wm_class": ["firefox", "chromium"]},
    "filemanager": {"match_wm_class": ["org.kde.dolphin"]},
}


def test_exact_match():
    assert find_matching_profile("firefox", PROFILES) == "browser"


def test_case_insensitive():
    assert find_matching_profile("Firefox", PROFILES) == "browser"
    assert find_matching_profile("CHROMIUM", PROFILES) == "browser"


def test_substring_match():
    # GTK Firefox window often reports "Navigator.firefox" or similar.
    assert find_matching_profile("Navigator.firefox", PROFILES) == "browser"


def test_prefix_match():
    assert find_matching_profile("org.kde.dolphin.X", PROFILES) == "filemanager"


def test_default_fallback():
    assert find_matching_profile("totally-unknown-app", PROFILES) == "default"


def test_default_profile_is_skipped_as_match_source():
    # Even if someone accidentally adds match_wm_class to "default",
    # the matcher must skip it — default is the fallback, not a target.
    profiles = {
        "default": {"match_wm_class": ["firefox"]},
        "browser": {"match_wm_class": ["firefox"]},
    }
    assert find_matching_profile("firefox", profiles) == "browser"


def test_profile_without_match_wm_class():
    profiles = {
        "default": {},
        "empty": {},  # no match_wm_class key at all
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


def test_managed_3d_app_resolves_to_passthrough():
    # Apps that ship their own SpaceMouse settings tabs (Blender, FreeCAD)
    # must always idle the daemon, regardless of what's in profiles.
    assert find_matching_profile("blender", PROFILES) == PASSTHROUGH_PROFILE
    assert find_matching_profile("Blender", PROFILES) == PASSTHROUGH_PROFILE
    assert find_matching_profile("org.freecad.FreeCAD", PROFILES) == PASSTHROUGH_PROFILE
    assert find_matching_profile("FreeCAD-1.1", PROFILES) == PASSTHROUGH_PROFILE


def test_managed_3d_app_wins_over_profile():
    # Even if a user adds match_wm_class entries that overlap with a
    # managed app, the managed app's passthrough wins so the 3D app's
    # native libspnav path is never starved.
    profiles = {
        "default": {"match_wm_class": []},
        "rogue": {"match_wm_class": ["blender"]},
    }
    assert find_matching_profile("blender", profiles) == PASSTHROUGH_PROFILE
