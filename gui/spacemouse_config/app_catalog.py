"""Catalog of well-known applications and their WM class strings.

Used by the Add Application dialog so users can pick from a friendly list
instead of having to type cryptic WM class names. The matcher itself is
case-insensitive and matches via equal/prefix/substring, so a single
canonical entry typically covers all casing variants of an app.

Categories drive the layout in the dialog. Add new entries here whenever
a common app's WM class becomes known.
"""


APP_CATALOG = {
    "3D & CAD": {
        "Blender": ["blender"],
        "FreeCAD": ["FreeCAD"],
        "OpenSCAD": ["openscad"],
        "KiCad": ["kicad"],
        "Solvespace": ["solvespace"],
        "MeshLab": ["meshlab"],
        "F3D": ["f3d"],
        "View3DScene": ["view3dscene"],
        "PrusaSlicer": ["PrusaSlicer"],
        "Cura": ["UltiMaker-Cura"],
        "OrcaSlicer": ["OrcaSlicer"],
    },
    "Browsers": {
        "Firefox": ["firefox", "Navigator"],
        "Chromium": ["chromium"],
        "Google Chrome": ["google-chrome"],
        "Brave": ["Brave-browser"],
        "Vivaldi": ["vivaldi-stable"],
        "Microsoft Edge": ["microsoft-edge"],
    },
    "File Managers": {
        "Dolphin": ["org.kde.dolphin"],
        "Nautilus": ["org.gnome.Nautilus"],
        "Thunar": ["thunar"],
        "Nemo": ["nemo"],
        "PCManFM": ["pcmanfm"],
    },
    "Terminals": {
        "Konsole": ["org.kde.konsole"],
        "Alacritty": ["Alacritty"],
        "Kitty": ["kitty"],
        "WezTerm": ["org.wezfurlong.wezterm"],
        "GNOME Terminal": ["gnome-terminal-server"],
        "Xterm": ["xterm"],
    },
    "Office": {
        "LibreOffice": ["libreoffice", "soffice"],
        "OnlyOffice": ["DesktopEditors"],
    },
    "Editors & IDEs": {
        "Kate": ["org.kde.kate"],
        "VSCode": ["Code", "code-oss"],
        "Sublime Text": ["sublime_text"],
        "Emacs": ["emacs"],
        "Neovim (GUI)": ["nvim-qt"],
        "JetBrains IDE": ["jetbrains-idea", "jetbrains-pycharm", "jetbrains-clion"],
    },
    "Media & Viewers": {
        "VLC": ["vlc"],
        "MPV": ["mpv"],
        "Okular": ["org.kde.okular"],
        "Evince": ["org.gnome.Evince"],
        "Gwenview": ["org.kde.gwenview"],
        "Loupe": ["org.gnome.Loupe"],
    },
    "Desktop": {
        "Plasma Shell": ["plasmashell"],
    },
}


def display_name_for(wm_class):
    """Return the friendly name for a WM class, or the class itself if unknown.

    Used by chip widgets to show readable labels. The reverse direction —
    friendly name → WM classes — is handled directly off the catalog.
    """
    wm_lower = wm_class.lower()
    for category in APP_CATALOG.values():
        for name, classes in category.items():
            for c in classes:
                if c.lower() == wm_lower:
                    return name
    return wm_class


def app_owns_class(app_classes, wm_class):
    """True if wm_class is one of app_classes (case-insensitive)."""
    wm_lower = wm_class.lower()
    return any(c.lower() == wm_lower for c in app_classes)
