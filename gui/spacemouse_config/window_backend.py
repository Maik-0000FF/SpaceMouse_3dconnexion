"""Pick the right window-monitor backend for the current session.

Pure logic kept out of monitors.py so it stays importable without
PySide6 — the choice is driven by a few env vars and unit-testable.
"""

import os
import re

# Backend identifiers.
KWIN = "kwin"
X11 = "x11"
NONE = "none"


def select_backend(env=None):
    """Return the window-monitor backend best matching `env`.

    `env` is a mapping (defaults to os.environ). The selector prefers
    KWin scripting when the session is KDE Plasma — Wayland or X11 —
    because it gives focus events natively. For every other X11
    session it falls back to xprop polling. Wayland sessions outside
    KWin (Mutter, wlroots) have no portable backend yet, so we return
    NONE and let the daemon stay on its default profile.
    """
    if env is None:
        env = os.environ

    desktop = (env.get("XDG_CURRENT_DESKTOP") or "").lower()
    if "kde" in desktop:
        return KWIN

    # Sway / Hyprland will get IPC-native backends in a follow-up phase.
    # Their compositor signals are present, so don't false-trigger X11.
    if env.get("SWAYSOCK") or env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return NONE

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
