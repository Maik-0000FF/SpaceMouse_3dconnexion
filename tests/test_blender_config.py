"""Tests for BlenderConfig — JSON round-trip against a tmp_path."""

import json

import pytest

from spacemouse_config import backends


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point BLENDER_NDOF_PATH and CONFIG_DIR at tmp_path for the test."""
    target = tmp_path / "blender-ndof.json"
    monkeypatch.setattr(backends, "BLENDER_NDOF_PATH", target)
    monkeypatch.setattr(backends, "CONFIG_DIR", tmp_path)
    return backends.BlenderConfig(), target


def test_read_returns_defaults_when_file_missing(cfg):
    bc, _ = cfg
    s = bc.read()
    assert s["ndof_sensitivity"] == 1.0
    assert s["ndof_orbit_sensitivity"] == 1.0
    assert s["ndof_deadzone"] == 0.1
    assert s["ndof_lock_horizon"] is False


def test_read_merges_saved_values_over_defaults(cfg, tmp_path):
    bc, target = cfg
    target.write_text(json.dumps({"ndof_sensitivity": 2.5,
                                  "ndof_lock_horizon": True}))
    s = bc.read()
    # Saved values win
    assert s["ndof_sensitivity"] == 2.5
    assert s["ndof_lock_horizon"] is True
    # Missing keys fall back to defaults
    assert s["ndof_orbit_sensitivity"] == 1.0
    assert s["ndof_deadzone"] == 0.1


def test_write_then_read_roundtrip(cfg):
    bc, _ = cfg
    new = dict(bc.DEFAULTS)
    new["ndof_sensitivity"] = 3.14
    new["ndof_zoom_invert"] = True
    new["ndof_rotx_invert_axis"] = True

    bc.write(new)
    s = bc.read()

    assert s["ndof_sensitivity"] == 3.14
    assert s["ndof_zoom_invert"] is True
    assert s["ndof_rotx_invert_axis"] is True
    assert s["ndof_roty_invert_axis"] is False  # untouched


def test_read_recovers_from_corrupt_json(cfg, tmp_path):
    bc, target = cfg
    target.write_text("not json at all {{{")
    s = bc.read()
    # No exception, falls back to defaults
    assert s == bc.DEFAULTS


def test_defaults_has_all_documented_keys():
    """Every key listed in the CLAUDE.md NDOF table is present in DEFAULTS."""
    documented = {
        "ndof_sensitivity", "ndof_orbit_sensitivity", "ndof_deadzone",
        "ndof_lock_horizon", "ndof_pan_yz_swap_axis", "ndof_zoom_invert",
        "ndof_rotx_invert_axis", "ndof_roty_invert_axis", "ndof_rotz_invert_axis",
        "ndof_panx_invert_axis", "ndof_pany_invert_axis", "ndof_panz_invert_axis",
    }
    assert documented == set(backends.BlenderConfig.DEFAULTS.keys())
