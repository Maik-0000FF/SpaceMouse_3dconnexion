"""Tests for the window-monitor backend selector and xprop parsers."""

from spacemouse_config.window_backend import (
    GNOME_WAYLAND,
    HYPRLAND,
    KWIN,
    NONE,
    SWAY,
    X11,
    parse_hyprland_event,
    parse_sway_focus_event,
    parse_window_calls_list,
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


def test_gnome_wayland_selects_gnome_wayland():
    # GNOME-Wayland routes through the Window Calls extension. Even
    # when DISPLAY is set via Xwayland fallback, WAYLAND_DISPLAY
    # presence pins the selection to the Wayland backend.
    env = {
        "XDG_CURRENT_DESKTOP": "GNOME",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":0",
    }
    assert select_backend(env) == GNOME_WAYLAND


def test_gnome_wayland_compound_xdg_string():
    # ubuntu:GNOME etc.
    env = {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "WAYLAND_DISPLAY": "wayland-0"}
    assert select_backend(env) == GNOME_WAYLAND


def test_gnome_x11_selects_x11():
    env = {"XDG_CURRENT_DESKTOP": "GNOME", "DISPLAY": ":0"}
    assert select_backend(env) == X11


def test_sway_selects_sway():
    # Even with DISPLAY set for Xwayland the IPC-native backend wins.
    env = {"SWAYSOCK": "/run/user/1000/sway-ipc.sock", "DISPLAY": ":0"}
    assert select_backend(env) == SWAY


def test_hyprland_selects_hyprland():
    env = {"HYPRLAND_INSTANCE_SIGNATURE": "abc123", "DISPLAY": ":0"}
    assert select_backend(env) == HYPRLAND


def test_hyprland_wins_over_swaysock_if_both_present():
    # Pathological case — should never occur in practice. Documenting
    # the dispatch order so a future refactor doesn't reverse it.
    env = {
        "HYPRLAND_INSTANCE_SIGNATURE": "abc123",
        "SWAYSOCK": "/run/user/1000/sway-ipc.sock",
    }
    assert select_backend(env) == HYPRLAND


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


# ── Sway parser ───────────────────────────────────────────────────────


def test_sway_focus_event_native_wayland():
    obj = {"change": "focus", "container": {"app_id": "firefox"}}
    assert parse_sway_focus_event(obj) == "firefox"


def test_sway_focus_event_xwayland_fallback():
    # Sway exposes Xwayland clients without app_id; window_properties.class
    # holds the X11 WM_CLASS instead.
    obj = {
        "change": "focus",
        "container": {
            "app_id": None,
            "window_properties": {"class": "Inkscape"},
        },
    }
    assert parse_sway_focus_event(obj) == "Inkscape"


def test_sway_non_focus_event_ignored():
    obj = {"change": "new", "container": {"app_id": "firefox"}}
    assert parse_sway_focus_event(obj) is None


def test_sway_missing_container():
    assert parse_sway_focus_event({"change": "focus"}) is None


def test_sway_unknown_input():
    assert parse_sway_focus_event(None) is None
    assert parse_sway_focus_event("not a dict") is None
    assert parse_sway_focus_event({}) is None


# ── Hyprland parser ───────────────────────────────────────────────────


def test_hyprland_activewindow_line():
    line = "activewindow>>firefox,Mozilla Firefox\n"
    assert parse_hyprland_event(line) == "firefox"


def test_hyprland_activewindow_without_title():
    line = "activewindow>>kitty,\n"
    assert parse_hyprland_event(line) == "kitty"


def test_hyprland_ignores_other_events():
    assert parse_hyprland_event("workspace>>3\n") is None
    assert parse_hyprland_event("openwindow>>abc,firefox,Firefox\n") is None


def test_hyprland_no_separator():
    assert parse_hyprland_event("plain text\n") is None
    assert parse_hyprland_event("") is None
    assert parse_hyprland_event(None) is None


def test_hyprland_empty_class_returns_none():
    # When Hyprland reports an empty focus event the class is blank;
    # we must not propagate '' as a profile match key.
    assert parse_hyprland_event("activewindow>>,\n") is None


# ── Window Calls (GNOME Shell extension) parser ───────────────────────


def test_window_calls_focused_entry():
    payload = (
        '[{"wm_class": "firefox", "focus": false},'
        ' {"wm_class": "blender", "focus": true},'
        ' {"wm_class": "Code", "focus": false}]'
    )
    assert parse_window_calls_list(payload) == "blender"


def test_window_calls_no_focus():
    # All windows unfocused (e.g. overview shown): no class to report.
    payload = '[{"wm_class": "firefox", "focus": false}]'
    assert parse_window_calls_list(payload) is None


def test_window_calls_empty_array():
    assert parse_window_calls_list("[]") is None


def test_window_calls_instance_fallback():
    # Older Window Calls builds sometimes only populate wm_class_instance
    # for Xwayland clients; we fall back to it rather than emit nothing.
    payload = '[{"wm_class_instance": "Inkscape", "focus": true}]'
    assert parse_window_calls_list(payload) == "Inkscape"


def test_window_calls_malformed_json():
    assert parse_window_calls_list("not json") is None
    assert parse_window_calls_list("") is None
    assert parse_window_calls_list(None) is None


def test_window_calls_unexpected_shape():
    # Defensive: an object instead of an array should not raise.
    assert parse_window_calls_list('{"focus": true}') is None
