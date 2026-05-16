"""Tests for the window-monitor backend selector and xprop parsers."""

from spacemouse_config.window_backend import (
    KWIN,
    NONE,
    X11,
    parse_xprop_active_window,
    parse_xprop_wm_class,
    select_backend,
)

# ── select_backend ────────────────────────────────────────────────────


def test_kde_wayland_selects_kwin():
    env = {"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"}
    assert select_backend(env) == KWIN


def test_kde_x11_still_selects_kwin():
    env = {"XDG_CURRENT_DESKTOP": "KDE", "DISPLAY": ":0"}
    assert select_backend(env) == KWIN


def test_kde_in_compound_xdg_string():
    # ubuntu:KDE etc.
    env = {"XDG_CURRENT_DESKTOP": "ubuntu:KDE", "DISPLAY": ":0"}
    assert select_backend(env) == KWIN


def test_xfce_x11_selects_x11():
    env = {"XDG_CURRENT_DESKTOP": "XFCE", "DISPLAY": ":0"}
    assert select_backend(env) == X11


def test_cinnamon_x11_selects_x11():
    env = {"XDG_CURRENT_DESKTOP": "X-Cinnamon", "DISPLAY": ":0"}
    assert select_backend(env) == X11


def test_mate_x11_selects_x11():
    env = {"XDG_CURRENT_DESKTOP": "MATE", "DISPLAY": ":0"}
    assert select_backend(env) == X11


def test_gnome_wayland_returns_none():
    # GNOME-Wayland has no portable backend yet — we'd need a Mutter
    # extension. Don't false-trigger X11 just because DISPLAY is set
    # via Xwayland fallback; WAYLAND_DISPLAY being set rules X11 out.
    env = {
        "XDG_CURRENT_DESKTOP": "GNOME",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":0",
    }
    assert select_backend(env) == NONE


def test_gnome_x11_selects_x11():
    env = {"XDG_CURRENT_DESKTOP": "GNOME", "DISPLAY": ":0"}
    assert select_backend(env) == X11


def test_sway_returns_none():
    # Sway will get its own swaymsg backend in a follow-up phase. Until
    # then, returning NONE is correct — DISPLAY may also be set for
    # Xwayland, but we don't want to false-trigger the X11 path.
    env = {"SWAYSOCK": "/run/user/1000/sway-ipc.sock", "DISPLAY": ":0"}
    assert select_backend(env) == NONE


def test_hyprland_returns_none():
    env = {"HYPRLAND_INSTANCE_SIGNATURE": "abc123", "DISPLAY": ":0"}
    assert select_backend(env) == NONE


def test_empty_env_returns_none():
    assert select_backend({}) == NONE


# ── xprop parsers ─────────────────────────────────────────────────────


def test_parse_xprop_active_window_typical():
    line = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a0000a\n"
    assert parse_xprop_active_window(line) == "0x3a0000a"


def test_parse_xprop_active_window_uppercase_hex():
    line = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0xDEADBEEF\n"
    assert parse_xprop_active_window(line) == "0xDEADBEEF"


def test_parse_xprop_active_window_no_match():
    assert parse_xprop_active_window("garbage line\n") is None
    assert parse_xprop_active_window("") is None


def test_parse_xprop_wm_class_typical():
    text = 'WM_CLASS(STRING) = "navigator", "Firefox"\n'
    assert parse_xprop_wm_class(text) == "Firefox"


def test_parse_xprop_wm_class_with_dots():
    # FreeCAD on Wayland reports org.freecad.FreeCAD as the class.
    text = 'WM_CLASS(STRING) = "freecad", "org.freecad.FreeCAD"\n'
    assert parse_xprop_wm_class(text) == "org.freecad.FreeCAD"


def test_parse_xprop_wm_class_extra_whitespace():
    # xprop sometimes formats with varying whitespace around '='.
    text = 'WM_CLASS(STRING)   =   "instance",   "Class"'
    assert parse_xprop_wm_class(text) == "Class"


def test_parse_xprop_wm_class_no_match():
    assert parse_xprop_wm_class("not the right line\n") is None
    assert parse_xprop_wm_class("") is None
