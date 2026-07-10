"""Scan XDG application directories for installed apps.

Reads ``.desktop`` files from the standard XDG paths (user + system,
plus Flatpak) and returns app metadata — display name, WM class, primary
category. Used by the Manage 3D Apps dialog to populate the "Installed"
tab so users can pick from apps that actually exist on their system
instead of typing WM class strings by hand.

The XDG ``StartupWMClass`` key carries what Wayland / X11 report as the
window's WM class. When it's missing we fall back to the ``Exec``
basename, which is right ~80% of the time in practice.
"""

import configparser
import os
import shutil
from pathlib import Path

_XDG_DIRS = [
    Path.home() / ".local" / "share" / "applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
    Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
    Path("/var/lib/flatpak/exports/share/applications"),
]

# XDG-spec main category names. The first match in a .desktop's
# Categories= list determines the bucket the app lands in.
_XDG_MAIN_CATEGORIES = (
    "AudioVideo",
    "Audio",
    "Video",
    "Development",
    "Education",
    "Game",
    "Graphics",
    "Network",
    "Office",
    "Science",
    "Settings",
    "System",
    "Utility",
)


def _current_desktops():
    """Return the set of desktop names this session advertises.

    XDG_CURRENT_DESKTOP is a colon-separated list per the spec; on
    Plasma it is typically "KDE:Plasma", on GNOME "GNOME". Apps with
    OnlyShowIn / NotShowIn lists are filtered against this set.
    """
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return {d.strip() for d in raw.split(":") if d.strip()}


def _try_exec_available(try_exec):
    """Honor the XDG TryExec key. True when the entry has no TryExec, or
    when the named binary is reachable: absolute/relative paths must
    point at an executable file, bare names are looked up via PATH."""
    if not try_exec:
        return True
    try_exec = try_exec.strip()
    if not try_exec:
        return True
    if "/" in try_exec:
        return os.path.isfile(try_exec) and os.access(try_exec, os.X_OK)
    return shutil.which(try_exec) is not None


def _exec_basename(exec_value):
    """Return the binary basename from a Desktop Entry Exec= line.

    Skips field codes (%f, %F, %u, %U, %i, …) and strips path prefix.
    """
    if not exec_value:
        return ""
    for tok in exec_value.split():
        if tok.startswith("%"):
            continue
        # Strip quotes and path prefix
        tok = tok.strip("'\"")
        if not tok:
            continue
        return os.path.basename(tok)
    return ""


def _read_desktop(path, current_desktops):
    """Parse a .desktop file. Return app info dict or None if hidden/invalid.

    Filters per XDG spec: Hidden / NoDisplay drop the entry outright;
    OnlyShowIn / NotShowIn scope it to the current desktop session;
    TryExec drops entries whose binary isn't installed.
    """
    cfg = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        cfg.read(path, encoding="utf-8")
    except (OSError, configparser.Error, UnicodeDecodeError):
        return None

    if "Desktop Entry" not in cfg.sections():
        return None
    section = cfg["Desktop Entry"]

    if section.get("Type", "").strip().lower() != "application":
        return None
    if section.get("Hidden", "false").strip().lower() == "true":
        return None
    if section.get("NoDisplay", "false").strip().lower() == "true":
        return None

    only_show_in = {x.strip() for x in section.get("OnlyShowIn", "").split(";") if x.strip()}
    not_show_in = {x.strip() for x in section.get("NotShowIn", "").split(";") if x.strip()}
    if only_show_in and not (only_show_in & current_desktops):
        return None
    if not_show_in & current_desktops:
        return None

    if not _try_exec_available(section.get("TryExec", "")):
        return None

    name = section.get("Name", "").strip()
    if not name:
        return None

    wm_class = section.get("StartupWMClass", "").strip()
    if not wm_class:
        wm_class = _exec_basename(section.get("Exec", "")) or path.stem

    categories_str = section.get("Categories", "")
    categories = [c.strip() for c in categories_str.split(";") if c.strip()]

    primary = "Other"
    for cat in categories:
        if cat in _XDG_MAIN_CATEGORIES:
            primary = cat
            break

    return {
        "name": name,
        "wm_class": wm_class,
        "categories": categories,
        "primary": primary,
        "exec": section.get("Exec", "").strip(),
    }


def scan_installed_apps():
    """Return installed applications discovered via .desktop files.

    Deduped by display name (first occurrence wins, so user-local
    overrides system). Sorted by primary category, then name.
    """
    apps = []
    seen = set()
    current_desktops = _current_desktops()

    for xdg_dir in _XDG_DIRS:
        if not xdg_dir.is_dir():
            continue
        for entry in sorted(xdg_dir.iterdir()):
            if entry.suffix != ".desktop" or not entry.is_file():
                continue
            info = _read_desktop(entry, current_desktops)
            if info is None:
                continue
            key = info["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            apps.append(info)

    apps.sort(key=lambda a: (a["primary"], a["name"].lower()))
    return apps


def group_by_category(apps):
    """Return ordered dict of ``{category: [app, ...]}`` preserving sort order."""
    grouped = {}
    for app in apps:
        grouped.setdefault(app["primary"], []).append(app)
    return grouped
