"""Tests for the WM-class → profile-name matcher."""

from spacemouse_config.profile_match import PASSTHROUGH_PROFILE, find_matching_profile

PROFILES = {
    "default": {"match_wm_class": ["plasmashell", "firefox", "org.kde.dolphin"]},
    "browser": {"match_wm_class": ["chromium", "Navigator"]},
}


def test_exact_match():
    assert find_matching_profile("chromium", PROFILES) == "browser"


def test_case_insensitive():
    assert find_matching_profile("Firefox", PROFILES) == "default"
    assert find_matching_profile("CHROMIUM", PROFILES) == "browser"


def test_substring_match():
    # GTK Firefox window often reports "Navigator.firefox" or similar.
    assert find_matching_profile("Navigator.firefox", PROFILES) == "default"


def test_prefix_match():
    assert find_matching_profile("org.kde.dolphin.X", PROFILES) == "default"


def test_default_matches_its_own_classes():
    # Whitelist semantics: default no longer auto-matches everything.
    # It only fires for windows listed in its own match_wm_class.
    assert find_matching_profile("plasmashell", PROFILES) == "default"
    assert find_matching_profile("firefox", PROFILES) == "default"


def test_unknown_app_falls_to_passthrough():
    # Anything not whitelisted by any profile resolves to _passthrough
    # so the daemon stays out of the way — critical for 3D apps with
    # their own libspnav support (Blender, FreeCAD, OpenSCAD, ...).
    assert find_matching_profile("totally-unknown-app", PROFILES) == PASSTHROUGH_PROFILE
    assert find_matching_profile("blender", PROFILES) == PASSTHROUGH_PROFILE
    assert find_matching_profile("org.freecad.FreeCAD", PROFILES) == PASSTHROUGH_PROFILE
    assert find_matching_profile("openscad", PROFILES) == PASSTHROUGH_PROFILE


def test_profile_without_match_wm_class():
    profiles = {
        "default": {},
        "empty": {},  # no match_wm_class key at all
    }
    assert find_matching_profile("anything", profiles) == PASSTHROUGH_PROFILE


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
    assert find_matching_profile("anything", {}) == PASSTHROUGH_PROFILE
