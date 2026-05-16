"""Tests for FreeCADConfig — XML round-trip on a synthetic user.cfg."""

import xml.etree.ElementTree as ET

import pytest
from spacemouse_config.backends import FreeCADConfig

MINIMAL_USER_CFG = """<?xml version="1.0" encoding="utf-8"?>
<FCParameters>
  <FCParamGroup Name="Root">
    <FCParamGroup Name="BaseApp">
      <FCParamGroup Name="Preferences">
        <FCParamGroup Name="View">
          <FCText Name="NavigationStyle">Gui::BlenderNavigationStyle</FCText>
          <FCInt Name="OrbitStyle" Value="1"/>
        </FCParamGroup>
      </FCParamGroup>
      <FCParamGroup Name="Spaceball">
        <FCParamGroup Name="Motion">
          <FCInt Name="GlobalSensitivity" Value="-15"/>
          <FCBool Name="FlipYZ" Value="1"/>
          <FCBool Name="Dominant" Value="0"/>
          <FCBool Name="PanLREnable" Value="1"/>
          <FCBool Name="PanLRReverse" Value="0"/>
          <FCInt Name="PanLRDeadzone" Value="5"/>
          <FCBool Name="ZoomEnable" Value="1"/>
          <FCBool Name="ZoomReverse" Value="1"/>
          <FCInt Name="ZoomDeadzone" Value="20"/>
        </FCParamGroup>
        <FCParamGroup Name="Buttons">
          <FCParamGroup Name="0">
            <FCText Name="Command">Std_ViewFitAll</FCText>
          </FCParamGroup>
          <FCParamGroup Name="1">
            <FCText Name="Command">Std_ViewHome</FCText>
          </FCParamGroup>
        </FCParamGroup>
      </FCParamGroup>
    </FCParamGroup>
  </FCParamGroup>
</FCParameters>
"""


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "user.cfg"
    p.write_text(MINIMAL_USER_CFG)
    return p


@pytest.fixture
def cfg(cfg_path):
    c = FreeCADConfig()
    c.path = cfg_path  # bypass the home-dir auto-detection
    return c


def test_read_returns_expected_settings(cfg):
    s = cfg.read()
    assert s["global_sensitivity"] == -15
    assert s["flip_yz"] is True
    assert s["dominant"] is False
    assert s["panlr_enable"] is True
    assert s["panlr_reverse"] is False
    assert s["panlr_deadzone"] == 5
    assert s["zoom_enable"] is True
    assert s["zoom_reverse"] is True
    assert s["zoom_deadzone"] == 20
    assert s["btn0_command"] == "Std_ViewFitAll"
    assert s["btn1_command"] == "Std_ViewHome"
    assert s["nav_style"] == "Gui::BlenderNavigationStyle"
    assert s["orbit_style"] == 1


def test_read_with_no_path_returns_defaults():
    c = FreeCADConfig()
    c.path = None
    s = c.read()
    assert s["global_sensitivity"] == -15
    assert s["flip_yz"] is True
    assert s["nav_style"] == "Gui::BlenderNavigationStyle"


def test_write_then_read_roundtrip(cfg):
    new_settings = {
        "global_sensitivity": -42,
        "flip_yz": False,
        "dominant": True,
        "panlr_enable": False,
        "panlr_reverse": True,
        "panlr_deadzone": 99,
        "zoom_enable": True,
        "zoom_reverse": False,
        "zoom_deadzone": 7,
        "btn0_command": "Std_OrthographicCamera",
        "btn1_command": "Std_PerspectiveCamera",
        "nav_style": "Gui::CADNavigationStyle",
        "orbit_style": 0,
    }
    assert cfg.write(new_settings) is True

    s = cfg.read()
    assert s["global_sensitivity"] == -42
    assert s["flip_yz"] is False
    assert s["dominant"] is True
    assert s["panlr_enable"] is False
    assert s["panlr_reverse"] is True
    assert s["panlr_deadzone"] == 99
    assert s["zoom_enable"] is True
    assert s["zoom_reverse"] is False
    assert s["zoom_deadzone"] == 7
    assert s["btn0_command"] == "Std_OrthographicCamera"
    assert s["btn1_command"] == "Std_PerspectiveCamera"
    assert s["nav_style"] == "Gui::CADNavigationStyle"
    assert s["orbit_style"] == 0


def test_write_creates_missing_groups(tmp_path):
    """Spaceball/Buttons can be missing in user.cfg — write must add them."""
    bare = tmp_path / "user.cfg"
    bare.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<FCParameters>\n"
        '  <FCParamGroup Name="Root">\n'
        '    <FCParamGroup Name="BaseApp"/>\n'
        "  </FCParamGroup>\n"
        "</FCParameters>\n"
    )
    c = FreeCADConfig()
    c.path = bare
    assert c.write({"btn0_command": "Std_Fit"}) is True

    tree = ET.parse(bare)
    root = tree.getroot()
    base = root.find("FCParamGroup[@Name='Root']/FCParamGroup[@Name='BaseApp']")
    assert base is not None
    spaceball = base.find("FCParamGroup[@Name='Spaceball']")
    assert spaceball is not None
    btn0 = spaceball.find("FCParamGroup[@Name='Buttons']/FCParamGroup[@Name='0']")
    assert btn0 is not None
