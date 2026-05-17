"""Pick the right window-monitor backend for the current session.

Pure logic kept out of monitors.py so it stays importable without
PySide6 — the choice is driven by a few env vars and unit-testable.
"""

import json
import os
import re

# Backend identifiers.
KWIN = "kwin"
X11 = "x11"
SWAY = "sway"
HYPRLAND = "hyprland"
GNOME_WAYLAND = "gnome_wayland"
NONE = "none"


def select_backend(env=None):
    """Return the window-monitor backend best matching `env`.

    `env` is a mapping (defaults to os.environ). KWin scripting wins
    when the session is KDE Plasma. Sway and Hyprland speak their own
    IPC and are detected via SWAYSOCK / HYPRLAND_INSTANCE_SIGNATURE.
    GNOME-Wayland uses the Window Calls extension's D-Bus API; the
    monitor probes for it at runtime and falls back to no-op if the
    extension is missing. Every other X11 session uses xprop. Any
    unrecognized Wayland compositor returns NONE.
    """
    if env is None:
        env = os.environ

    desktop = (env.get("XDG_CURRENT_DESKTOP") or "").lower()
    if "kde" in desktop:
        return KWIN

    # Wayland tilers have native IPC. Detect them before X11 so an
    # Xwayland-set DISPLAY does not steer us to xprop.
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return HYPRLAND
    if env.get("SWAYSOCK"):
        return SWAY
    if "gnome" in desktop and env.get("WAYLAND_DISPLAY"):
        return GNOME_WAYLAND

    # Any X11 session (XFCE, Cinnamon, MATE, LXQt, X11-mode KDE/GNOME):
    # DISPLAY is set and WAYLAND_DISPLAY is not.
    if env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        return X11

    return NONE


# xprop output parsers — pure functions, easy to test.

_XPROP_WINDOW_ID_RE = re.compile(r"window id # (0x[0-9a-fA-F]+)")
_XPROP_WM_CLASS_RE = re.compile(r'WM_CLASS\(STRING\)\s*=\s*"([^"]*)"\s*,\s*"([^"]*)"')


def parse_xprop_active_window(line):
    """Extract the active-window id from a `xprop -spy -root _NET_ACTIVE_WINDOW` line.

    Lines look like:
      _NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a0000a
    Returns the hex id string (e.g. '0x3a0000a') or None.
    """
    m = _XPROP_WINDOW_ID_RE.search(line)
    return m.group(1) if m else None


def parse_xprop_wm_class(text):
    """Extract the WM_CLASS class field from `xprop -id <id> WM_CLASS` output.

    Output looks like:
      WM_CLASS(STRING) = "instance", "Class"
    Returns the class string (the second field — that's what KWin's
    resourceClass also reports), or None if absent.
    """
    m = _XPROP_WM_CLASS_RE.search(text)
    return m.group(2) if m else None


# Sway window-event parser. swaymsg subscribe yields one JSON object per
# event; the parser is pure JSON, no shell quoting concerns.


def parse_sway_focus_event(obj):
    """Extract wm_class from a Sway 'window' event dict.

    Returns the class string when the event is a focus change, else None.
    Prefers container.app_id (native Wayland clients), falls back to
    container.window_properties.class for Xwayland clients.
    """
    if not isinstance(obj, dict):
        return None
    if obj.get("change") != "focus":
        return None
    container = obj.get("container")
    if not isinstance(container, dict):
        return None
    app_id = container.get("app_id")
    if app_id:
        return app_id
    props = container.get("window_properties")
    if isinstance(props, dict):
        return props.get("class")
    return None


# Hyprland event-socket lines have the form "EVENT>>DATA\n". For
# activewindow the DATA is "CLASS,TITLE".


def parse_hyprland_event(line):
    """Extract wm_class from a Hyprland socket2 'activewindow' line.

    Returns the class string when the line is an activewindow event,
    else None. Format: "activewindow>>CLASS,TITLE".
    """
    if not line:
        return None
    line = line.rstrip("\r\n")
    head, sep, rest = line.partition(">>")
    if not sep or head != "activewindow":
        return None
    cls, _, _ = rest.partition(",")
    cls = cls.strip()
    return cls or None


# Window Calls (GNOME Shell extension) returns a JSON-encoded array of
# window dicts. Each entry has at least: wm_class, wm_class_instance,
# focus (bool), pid, id, in_current_workspace. We poll List() and pick
# the focused entry's class.


def parse_window_calls_list(text):
    """Extract the focused window's wm_class from Window Calls List() JSON.

    Returns the class string of the entry with focus=True, or None if
    no window is focused, the payload is malformed, or the array is
    empty. Falls back to wm_class_instance only if wm_class is missing.
    """
    try:
        items = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("focus"):
            continue
        cls = item.get("wm_class") or item.get("wm_class_instance")
        if cls:
            return cls
        return None
    return None
