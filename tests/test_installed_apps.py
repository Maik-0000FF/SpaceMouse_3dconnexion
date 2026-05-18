"""Tests for the XDG .desktop scanner that drives the Manage 3D Apps
dialog's Installed tab.

Covers parser edge cases (Hidden / NoDisplay / OnlyShowIn / NotShowIn /
TryExec / fallback for missing StartupWMClass) and the integration path
through scan_installed_apps with a patched XDG search list so each test
runs against a known directory tree instead of the host system."""

import pytest
from spacemouse_config import installed_apps

# ── _current_desktops ─────────────────────────────────────────────────


def test_current_desktops_single(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert installed_apps._current_desktops() == {"GNOME"}


def test_current_desktops_colon_separated(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE:Plasma")
    assert installed_apps._current_desktops() == {"KDE", "Plasma"}


def test_current_desktops_unset(monkeypatch):
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    assert installed_apps._current_desktops() == set()


# ── _try_exec_available ───────────────────────────────────────────────


def test_try_exec_empty_passes():
    assert installed_apps._try_exec_available("") is True
    assert installed_apps._try_exec_available("   ") is True


def test_try_exec_bare_name_found():
    # /bin/sh is universally available on Linux runners.
    assert installed_apps._try_exec_available("sh") is True


def test_try_exec_bare_name_missing():
    assert installed_apps._try_exec_available("definitely-not-a-real-binary-xyz") is False


def test_try_exec_absolute_existing():
    assert installed_apps._try_exec_available("/bin/sh") is True


def test_try_exec_absolute_missing():
    assert installed_apps._try_exec_available("/no/such/path/binary") is False


# ── scan_installed_apps integration ───────────────────────────────────


@pytest.fixture
def isolated_xdg(monkeypatch, tmp_path):
    """Make _XDG_DIRS point at an empty tmp dir for each test."""
    xdg = tmp_path / "applications"
    xdg.mkdir()
    monkeypatch.setattr(installed_apps, "_XDG_DIRS", [xdg])
    return xdg


def _write(dir_, name, content):
    (dir_ / name).write_text(content)


_MINIMAL = """[Desktop Entry]
Type=Application
Name=Minimal App
Exec=sh
"""

_WITH_WMCLASS = """[Desktop Entry]
Type=Application
Name=With WM Class
Exec=foo
StartupWMClass=foo-canonical
"""

_NODISPLAY = """[Desktop Entry]
Type=Application
Name=Hidden Helper
Exec=sh
NoDisplay=true
"""

_HIDDEN = """[Desktop Entry]
Type=Application
Name=Was Hidden
Exec=sh
Hidden=true
"""

_GNOME_ONLY = """[Desktop Entry]
Type=Application
Name=GNOME Only
Exec=sh
OnlyShowIn=GNOME;
"""

_KDE_NOT_SHOWN = """[Desktop Entry]
Type=Application
Name=Not On KDE
Exec=sh
NotShowIn=KDE;
"""

_TRYEXEC_MISSING = """[Desktop Entry]
Type=Application
Name=Has Missing TryExec
Exec=sh
TryExec=definitely-not-a-real-binary-xyz
"""

_TRYEXEC_PRESENT = """[Desktop Entry]
Type=Application
Name=Has Real TryExec
Exec=sh
TryExec=sh
"""

_NOT_APPLICATION = """[Desktop Entry]
Type=Link
Name=A Link Entry
URL=https://example.com
"""

_MALFORMED_INI = """not a section header
some=garbage
[Desktop Entry]
Type=Application
Name=Should Not Survive
"""

_NO_SECTION = """just a plain text file
no INI structure at all
"""

_NO_NAME = """[Desktop Entry]
Type=Application
Exec=sh
"""


def test_scan_returns_minimal_entry(isolated_xdg):
    _write(isolated_xdg, "min.desktop", _MINIMAL)
    apps = installed_apps.scan_installed_apps()
    assert [a["name"] for a in apps] == ["Minimal App"]


def test_scan_falls_back_to_exec_basename(isolated_xdg):
    _write(isolated_xdg, "min.desktop", _MINIMAL)
    (app,) = installed_apps.scan_installed_apps()
    assert app["wm_class"] == "sh"


def test_scan_prefers_startup_wm_class(isolated_xdg):
    _write(isolated_xdg, "wmc.desktop", _WITH_WMCLASS)
    (app,) = installed_apps.scan_installed_apps()
    assert app["wm_class"] == "foo-canonical"


def test_scan_hides_nodisplay(isolated_xdg):
    _write(isolated_xdg, "nd.desktop", _NODISPLAY)
    assert installed_apps.scan_installed_apps() == []


def test_scan_hides_hidden_true(isolated_xdg):
    _write(isolated_xdg, "hid.desktop", _HIDDEN)
    assert installed_apps.scan_installed_apps() == []


def test_scan_skips_non_application_type(isolated_xdg):
    _write(isolated_xdg, "link.desktop", _NOT_APPLICATION)
    assert installed_apps.scan_installed_apps() == []


def test_scan_drops_only_show_in_mismatch(isolated_xdg, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    _write(isolated_xdg, "gnome.desktop", _GNOME_ONLY)
    assert installed_apps.scan_installed_apps() == []


def test_scan_keeps_only_show_in_match(isolated_xdg, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    _write(isolated_xdg, "gnome.desktop", _GNOME_ONLY)
    (app,) = installed_apps.scan_installed_apps()
    assert app["name"] == "GNOME Only"


def test_scan_drops_not_show_in_match(isolated_xdg, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE:Plasma")
    _write(isolated_xdg, "no-kde.desktop", _KDE_NOT_SHOWN)
    assert installed_apps.scan_installed_apps() == []


def test_scan_keeps_not_show_in_mismatch(isolated_xdg, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    _write(isolated_xdg, "no-kde.desktop", _KDE_NOT_SHOWN)
    (app,) = installed_apps.scan_installed_apps()
    assert app["name"] == "Not On KDE"


def test_scan_drops_tryexec_missing_binary(isolated_xdg):
    _write(isolated_xdg, "try.desktop", _TRYEXEC_MISSING)
    assert installed_apps.scan_installed_apps() == []


def test_scan_keeps_tryexec_present_binary(isolated_xdg):
    _write(isolated_xdg, "try.desktop", _TRYEXEC_PRESENT)
    (app,) = installed_apps.scan_installed_apps()
    assert app["name"] == "Has Real TryExec"


def test_scan_dedupes_by_display_name(isolated_xdg):
    # Two .desktop files declaring the same Name — only one survives.
    _write(isolated_xdg, "first.desktop", _MINIMAL)
    _write(isolated_xdg, "second.desktop", _MINIMAL)
    apps = installed_apps.scan_installed_apps()
    assert len(apps) == 1


def test_scan_groups_by_category(isolated_xdg):
    _write(
        isolated_xdg,
        "blender.desktop",
        "[Desktop Entry]\nType=Application\nName=Blender\nExec=blender\nCategories=Graphics;3DGraphics;\n",
    )
    apps = installed_apps.scan_installed_apps()
    grouped = installed_apps.group_by_category(apps)
    assert "Graphics" in grouped
    assert grouped["Graphics"][0]["name"] == "Blender"


# ── Defensive paths: broken or incomplete files are skipped quietly ───


def test_scan_skips_malformed_ini(isolated_xdg):
    _write(isolated_xdg, "bad.desktop", _MALFORMED_INI)
    assert installed_apps.scan_installed_apps() == []


def test_scan_skips_missing_section(isolated_xdg):
    _write(isolated_xdg, "no-sec.desktop", _NO_SECTION)
    assert installed_apps.scan_installed_apps() == []


def test_scan_skips_missing_name(isolated_xdg):
    _write(isolated_xdg, "no-name.desktop", _NO_NAME)
    assert installed_apps.scan_installed_apps() == []


def test_scan_survives_bad_file_alongside_good(isolated_xdg):
    """A single broken file must not abort the whole scan."""
    _write(isolated_xdg, "bad.desktop", _MALFORMED_INI)
    _write(isolated_xdg, "good.desktop", _MINIMAL)
    apps = installed_apps.scan_installed_apps()
    assert [a["name"] for a in apps] == ["Minimal App"]
