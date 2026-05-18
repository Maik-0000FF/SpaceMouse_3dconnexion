"""Tests for the WM-class → profile-name matcher."""

from spacemouse_config.profile_match import find_matching_profile

PROFILES = {
    "default": {"match_wm_class": []},
    "browser": {"match_wm_class": ["firefox", "chromium"]},
    "passthrough": {"match_wm_class": ["blender", "FreeCAD", "openscad"]},
}


def test_exact_match():
    assert find_matching_profile("blender", PROFILES) == "passthrough"
    assert find_matching_profile("firefox", PROFILES) == "browser"


def test_case_insensitive():
    assert find_matching_profile("Firefox", PROFILES) == "browser"
    assert find_matching_profile("CHROMIUM", PROFILES) == "browser"
    assert find_matching_profile("BLENDER", PROFILES) == "passthrough"


def test_substring_match():
    # GTK Firefox window often reports "Navigator.firefox" or similar.
    assert find_matching_profile("Navigator.firefox", PROFILES) == "browser"


def test_prefix_match():
    # FreeCAD Wayland reports org.freecad.FreeCAD; the bare "FreeCAD"
    # entry should match windows that start with it.
    assert find_matching_profile("FreeCAD-1.1", PROFILES) == "passthrough"


def test_default_fallback():
    # Anything no profile claims falls to default — the catch-all for
    # ordinary desktop apps. Whether actions actually fire depends on
    # default's axis/button mappings (daemon decides).
    assert find_matching_profile("totally-unknown-app", PROFILES) == "default"
    assert find_matching_profile("libreoffice-writer", PROFILES) == "default"


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
