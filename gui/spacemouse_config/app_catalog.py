"""Catalog of well-known applications and their WM class strings.

Used by ``display_name_for`` to turn a raw WM class string into a
human-friendly chip label. The Manage 3D Apps dialog itself scans XDG
``.desktop`` files for its installed-apps list; this catalog only fills
in display names when a WM class happens to match one of the known apps.
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
