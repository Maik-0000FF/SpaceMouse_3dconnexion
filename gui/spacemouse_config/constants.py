"""Static configuration constants — shared by all modules."""

import os
import re
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "spacemouse"
CONFIG_PATH = CONFIG_DIR / "config.json"
BLENDER_NDOF_PATH = CONFIG_DIR / "blender-ndof.json"
SOCK_PATH = f"/run/user/{os.getuid()}/spacemouse-cmd.sock"

BLENDER_CONFIG_ROOT = Path.home() / ".config" / "blender"
# Fallback target when no Blender version dir exists yet — the user
# hasn't run Blender once, but we still want the install button to
# leave something Blender will pick up on first launch.
BLENDER_DEFAULT_VERSION = "5.0"
BLENDER_SYNC_SCRIPT = "spacemouse_sync.py"

_BLENDER_VERSION_RE = re.compile(r"\d+\.\d+")


def _version_startup_dir(version):
    return BLENDER_CONFIG_ROOT / version / "scripts" / "startup"


def discover_blender_versions():
    """Return [(version, startup_dir), ...] for every installed Blender.

    Blender creates ~/.config/blender/N.N/ on first launch, so the
    directory's existence is a strong signal that the user runs that
    version. Non-version subdirs (addons, snap_archives, ...) are
    skipped via the strict N.N regex.
    """
    if not BLENDER_CONFIG_ROOT.is_dir():
        return []
    found = []
    for entry in sorted(BLENDER_CONFIG_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        if not _BLENDER_VERSION_RE.fullmatch(entry.name):
            continue
        found.append((entry.name, _version_startup_dir(entry.name)))
    return found


def blender_install_targets():
    """Where the startup script should be written.

    Existing version dirs if any (so Blender 4.5 + 5.0 both get the
    script), otherwise a single default target so a fresh-Blender
    install still picks up the sync script on first launch.
    """
    discovered = discover_blender_versions()
    if discovered:
        return discovered
    return [(BLENDER_DEFAULT_VERSION, _version_startup_dir(BLENDER_DEFAULT_VERSION))]


AXIS_ACTIONS = [
    "none",
    "scroll_h",
    "scroll_v",
    "zoom",
    "desktop_switch",
    "volume",
    "key_pair:LEFT,RIGHT",
    "key_pair:DOWN,UP",
    "key_pair:PAGEDOWN,PAGEUP",
    "key_pair:J,L",
]
AXIS_ACTION_LABELS = [
    "None",
    "Horizontal Scroll",
    "Vertical Scroll",
    "Zoom",
    "Desktop Switch",
    "Volume",
    "Arrow Left/Right (5s Seek)",
    "Arrow Down/Up",
    "Page Down/Up",
    "J/L (10s Seek)",
]

BTN_ACTIONS = [
    "none",
    "overview",
    "show_desktop",
    "volume_up",
    "volume_down",
    "mute",
    "play_pause",
    "next_track",
    "prev_track",
    "key:SPACE",
    "key:F",
    "key:M",
    "key:ENTER",
    "key:ESC",
]
BTN_ACTION_LABELS = [
    "None",
    "Overview (Expose)",
    "Show Desktop",
    "Volume Up",
    "Volume Down",
    "Mute",
    "Play/Pause (MPRIS)",
    "Next Track",
    "Previous Track",
    "Space (Play/Pause Browser)",
    "F (Fullscreen)",
    "M (Mute YouTube)",
    "Enter",
    "Escape",
]

AXIS_NAMES = [
    "TX (Left/Right)",
    "TY (Push/Pull)",
    "TZ (Up/Down)",
    "RX (Pitch)",
    "RY (Roll)",
    "RZ (Yaw/Twist)",
]
AXIS_KEYS = ["tx", "ty", "tz", "rx", "ry", "rz"]

FREECAD_BTN_COMMANDS = [
    "Std_ViewFitAll",
    "Std_ViewHome",
    "Std_ViewIsometric",
    "Std_ViewFront",
    "Std_ViewTop",
    "Std_ViewRight",
]
FREECAD_BTN_LABELS = [
    "Fit All",
    "Home View",
    "Isometric",
    "Front",
    "Top",
    "Right",
]

FREECAD_NAV_STYLES = [
    "Gui::InventorNavigationStyle",
    "Gui::BlenderNavigationStyle",
    "Gui::CADNavigationStyle",
    "Gui::OpenCascadeNavigationStyle",
    "Gui::RevitNavigationStyle",
]
FREECAD_NAV_LABELS = ["Inventor", "Blender", "CAD", "OpenCascade", "Revit"]

FREECAD_ORBIT_STYLES = {"Trackball": 1, "Turntable": 0}

# ── Dark Theme QSS ────────────────────────────────────────────────────

DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: sans-serif;
    font-size: 13px;
}

/* Sidebar */
#sidebar {
    background-color: #181825;
    border-right: 1px solid #313244;
}
#sidebar QPushButton {
    background-color: transparent;
    color: #a6adc8;
    border: none;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: left;
    font-size: 13px;
    font-weight: bold;
}
#sidebar QPushButton:hover {
    background-color: #313244;
    color: #cdd6f4;
}
#sidebar QPushButton:checked {
    background-color: #5294e2;
    color: #ffffff;
}

/* Cards / Sections */
QFrame.card {
    background-color: #2a2a3e;
    border-radius: 8px;
    padding: 12px;
}
QFrame.card QLabel.section-title {
    color: #a6adc8;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    padding-bottom: 4px;
}

/* Labels */
QLabel {
    color: #cdd6f4;
    background: transparent;
}
QLabel.dimmed {
    color: #a6adc8;
}
QLabel.value-label {
    color: #5294e2;
    font-weight: bold;
    min-width: 40px;
}

/* Sliders */
QSlider::groove:horizontal {
    background: #45475a;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #5294e2;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal {
    background: #5294e2;
    border-radius: 3px;
}

/* Combos */
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 160px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #5294e2;
    border: 1px solid #45475a;
    border-radius: 4px;
}

/* Checkboxes — hide default indicator, ToggleSwitch paints itself */
QCheckBox {
    spacing: 8px;
    color: #cdd6f4;
}

/* Buttons */
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton#apply-btn {
    background-color: #5294e2;
    color: #ffffff;
    border: none;
    padding: 8px 32px;
    font-size: 14px;
}
QPushButton#apply-btn:hover {
    background-color: #6ba4f0;
}

/* Line edits */
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 10px;
}

/* Progress bars (live preview) */
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 3px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #5294e2;
    border-radius: 3px;
}

/* Scroll area */
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* Live bar */
#live-bar {
    background-color: #181825;
    border-top: 1px solid #313244;
}

/* Warning label */
QLabel.warning {
    color: #f9e2af;
    background-color: #3a3636;
    border-radius: 6px;
    padding: 8px;
}
"""
