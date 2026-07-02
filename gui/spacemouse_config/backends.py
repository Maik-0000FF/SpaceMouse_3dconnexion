"""Backends for FreeCAD user.cfg (XML) and Blender NDOF settings (JSON)."""

import filecmp
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .constants import (
    BLENDER_NDOF_PATH,
    BLENDER_SYNC_SCRIPT,
    CONFIG_DIR,
    blender_install_targets,
    discover_blender_versions,
)


class FreeCADConfig:
    """Read/write FreeCAD user.cfg XML for SpaceMouse settings."""

    _CANDIDATES = [
        Path.home() / ".config" / "FreeCAD" / "user.cfg",
        Path.home() / ".FreeCAD" / "user.cfg",
        Path.home() / ".local" / "share" / "FreeCAD" / "user.cfg",
    ]

    def __init__(self):
        self.path = None
        for c in self._CANDIDATES:
            if c.exists():
                self.path = c
                break

    def is_available(self):
        return self.path is not None

    @staticmethod
    def is_running():
        try:
            result = subprocess.run(
                ["pgrep", "-x", "FreeCAD|freecad"], capture_output=True, timeout=2
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    # XML helpers (same logic as freecad-spacemouse-patch.sh)
    @staticmethod
    def _find_group(parent, name):
        for child in parent:
            if child.tag == "FCParamGroup" and child.get("Name") == name:
                return child
        return None

    @staticmethod
    def _ensure_group(parent, name):
        grp = FreeCADConfig._find_group(parent, name)
        if grp is not None:
            return grp
        return ET.SubElement(parent, "FCParamGroup", Name=name)

    @staticmethod
    def _get_bool(parent, name, default=False):
        for child in parent:
            if child.tag == "FCBool" and child.get("Name") == name:
                return child.get("Value") == "1"
        return default

    @staticmethod
    def _get_int(parent, name, default=0):
        for child in parent:
            if child.tag == "FCInt" and child.get("Name") == name:
                try:
                    return int(child.get("Value"))
                except (TypeError, ValueError):
                    return default
        return default

    @staticmethod
    def _get_text(parent, name, default=""):
        for child in parent:
            if child.tag == "FCText" and child.get("Name") == name:
                val = child.get("Value")
                if val is not None:
                    return val
                return (child.text or "").strip()
        return default

    @staticmethod
    def _set_bool(parent, name, value):
        val_str = "1" if value else "0"
        for child in parent:
            if child.tag == "FCBool" and child.get("Name") == name:
                child.set("Value", val_str)
                return
        ET.SubElement(parent, "FCBool", Name=name, Value=val_str)

    @staticmethod
    def _set_int(parent, name, value):
        val_str = str(value)
        for child in parent:
            if child.tag == "FCInt" and child.get("Name") == name:
                child.set("Value", val_str)
                return
        ET.SubElement(parent, "FCInt", Name=name, Value=val_str)

    @staticmethod
    def _set_text(parent, name, value):
        for child in parent:
            if child.tag == "FCText" and child.get("Name") == name:
                if child.get("Value") is not None:
                    child.set("Value", value)
                else:
                    child.text = value
                return
        elem = ET.SubElement(parent, "FCText", Name=name)
        elem.text = value

    def read(self):
        """Read SpaceMouse-related settings from user.cfg. Returns dict."""
        defaults = {
            "global_sensitivity": -15,
            "flip_yz": True,
            "dominant": False,
            "pan_lr_enable": True,
            "pan_ud_enable": True,
            "zoom_enable": True,
            "tilt_enable": True,
            "roll_enable": True,
            "spin_enable": True,
            "pan_lr_reverse": False,
            "pan_ud_reverse": False,
            "zoom_reverse": False,
            "tilt_reverse": False,
            "roll_reverse": False,
            "spin_reverse": False,
            "panlr_deadzone": 0,
            "panud_deadzone": 0,
            "zoom_deadzone": 0,
            "tilt_deadzone": 0,
            "roll_deadzone": 0,
            "spin_deadzone": 0,
            "btn0_command": "Std_ViewFitAll",
            "btn1_command": "Std_ViewHome",
            "nav_style": "Gui::BlenderNavigationStyle",
            "orbit_style": 1,
        }
        if not self.path:
            return defaults

        try:
            tree = ET.parse(self.path)
        except ET.ParseError:
            return defaults

        xml_root = tree.getroot()
        fc_root = self._find_group(xml_root, "Root")
        if fc_root is None:
            return defaults
        base_app = self._find_group(fc_root, "BaseApp")
        if base_app is None:
            return defaults

        # Spaceball settings (BaseApp/Spaceball/Motion)
        spaceball = self._find_group(base_app, "Spaceball")
        if spaceball is None:
            return defaults
        motion = self._find_group(spaceball, "Motion")

        result = dict(defaults)
        if motion is not None:
            result["global_sensitivity"] = self._get_int(motion, "GlobalSensitivity", -15)
            result["flip_yz"] = self._get_bool(motion, "FlipYZ", True)
            result["dominant"] = self._get_bool(motion, "Dominant", False)
            for axis in ["PanLR", "PanUD", "Zoom", "Tilt", "Roll", "Spin"]:
                key_en = f"{axis.lower()}_enable"
                key_rev = f"{axis.lower()}_reverse"
                # Normalize: PanLR -> panlr, PanUD -> panud
                key_en = axis[0].lower() + axis[1:].lower() + "_enable"
                key_rev = axis[0].lower() + axis[1:].lower() + "_reverse"
                # Simpler: just lowercase
                key_en = axis.lower() + "_enable"
                key_rev = axis.lower() + "_reverse"
                result[key_en] = self._get_bool(motion, f"{axis}Enable", True)
                result[key_rev] = self._get_bool(motion, f"{axis}Reverse", False)
                result[f"{axis.lower()}_deadzone"] = self._get_int(motion, f"{axis}Deadzone", 0)

        # Buttons (BaseApp/Spaceball/Buttons/0, /1)
        buttons = self._find_group(spaceball, "Buttons")
        if buttons is not None:
            btn0 = self._find_group(buttons, "0")
            if btn0 is not None:
                result["btn0_command"] = self._get_text(btn0, "Command", "Std_ViewFitAll")
            btn1 = self._find_group(buttons, "1")
            if btn1 is not None:
                result["btn1_command"] = self._get_text(btn1, "Command", "Std_ViewHome")

        # View preferences (BaseApp/Preferences/View)
        prefs = self._find_group(base_app, "Preferences")
        if prefs is not None:
            view = self._find_group(prefs, "View")
            if view is not None:
                result["nav_style"] = self._get_text(
                    view, "NavigationStyle", "Gui::BlenderNavigationStyle"
                )
                result["orbit_style"] = self._get_int(view, "OrbitStyle", 1)

        return result

    def write(self, settings):
        """Write SpaceMouse-related settings to user.cfg."""
        if not self.path:
            return False

        try:
            tree = ET.parse(self.path)
        except ET.ParseError:
            return False

        xml_root = tree.getroot()
        fc_root = self._find_group(xml_root, "Root")
        if fc_root is None:
            return False
        base_app = self._find_group(fc_root, "BaseApp")
        if base_app is None:
            return False

        # Spaceball/Motion
        spaceball = self._ensure_group(base_app, "Spaceball")
        motion = self._ensure_group(spaceball, "Motion")

        self._set_int(motion, "GlobalSensitivity", settings.get("global_sensitivity", -15))
        self._set_bool(motion, "FlipYZ", settings.get("flip_yz", True))
        self._set_bool(motion, "Dominant", settings.get("dominant", False))

        for axis in ["PanLR", "PanUD", "Zoom", "Tilt", "Roll", "Spin"]:
            key_en = axis.lower() + "_enable"
            key_rev = axis.lower() + "_reverse"
            self._set_bool(motion, f"{axis}Enable", settings.get(key_en, True))
            self._set_bool(motion, f"{axis}Reverse", settings.get(key_rev, False))
            self._set_int(motion, f"{axis}Deadzone", settings.get(f"{axis.lower()}_deadzone", 0))

        # Buttons
        buttons = self._ensure_group(spaceball, "Buttons")
        btn0 = self._ensure_group(buttons, "0")
        self._set_text(btn0, "Command", settings.get("btn0_command", "Std_ViewFitAll"))
        btn1 = self._ensure_group(buttons, "1")
        self._set_text(btn1, "Command", settings.get("btn1_command", "Std_ViewHome"))

        # View preferences
        prefs = self._ensure_group(base_app, "Preferences")
        view = self._ensure_group(prefs, "View")
        self._set_text(
            view, "NavigationStyle", settings.get("nav_style", "Gui::BlenderNavigationStyle")
        )
        self._set_int(view, "OrbitStyle", settings.get("orbit_style", 1))

        tree.write(str(self.path), xml_declaration=True, encoding="utf-8")
        return True


# ── Blender Config (JSON) ─────────────────────────────────────────────


class BlenderConfig:
    """Read/write Blender NDOF settings as JSON + manage startup script."""

    DEFAULTS = {
        "ndof_sensitivity": 1.0,
        "ndof_orbit_sensitivity": 1.0,
        "ndof_deadzone": 0.1,
        "ndof_lock_horizon": False,
        "ndof_pan_yz_swap_axis": False,
        "ndof_zoom_invert": False,
        "ndof_rotx_invert_axis": False,
        "ndof_roty_invert_axis": False,
        "ndof_rotz_invert_axis": False,
        "ndof_panx_invert_axis": False,
        "ndof_pany_invert_axis": False,
        "ndof_panz_invert_axis": False,
    }

    def read(self):
        if BLENDER_NDOF_PATH.exists():
            try:
                with open(BLENDER_NDOF_PATH) as f:
                    saved = json.load(f)
                result = dict(self.DEFAULTS)
                result.update(saved)
                return result
            except (OSError, json.JSONDecodeError):
                pass
        return dict(self.DEFAULTS)

    def write(self, settings):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(BLENDER_NDOF_PATH, "w") as f:
            json.dump(settings, f, indent=2)

    def is_script_installed(self):
        """True if any detected Blender version has the script."""
        return any((dir_ / BLENDER_SYNC_SCRIPT).exists() for _, dir_ in discover_blender_versions())

    def _script_source_path(self):
        return Path(__file__).resolve().parent.parent / "blender_spacemouse_sync.py"

    def script_status(self):
        """Inspect the installed startup script across all Blender versions.

        Returns a dict with per-version status plus aggregate flags so
        the UI can render mixed states (e.g. installed for 5.0 but
        missing in 4.5, or installed everywhere but one copy out of
        date after a GUI upgrade).

        Schema:
            {
              "source_exists": bool,
              "any_installed": bool,
              "all_installed_up_to_date": bool,
              "versions": [
                {"version": "5.0", "path": Path, "installed": bool,
                 "up_to_date": bool, "mtime": float | None},
                ...
              ],
            }

        When no Blender version dir exists yet, versions[] reflects the
        default install target so the UI can still show a target path.
        """
        src = self._script_source_path()
        targets = blender_install_targets()

        per_version = []
        for version, dir_ in targets:
            dst = dir_ / BLENDER_SYNC_SCRIPT
            if not dst.exists():
                per_version.append(
                    {
                        "version": version,
                        "path": dst,
                        "installed": False,
                        "up_to_date": False,
                        "mtime": None,
                    }
                )
                continue
            up_to_date = src.exists() and filecmp.cmp(src, dst, shallow=False)
            per_version.append(
                {
                    "version": version,
                    "path": dst,
                    "installed": True,
                    "up_to_date": up_to_date,
                    "mtime": dst.stat().st_mtime,
                }
            )

        installed_entries = [v for v in per_version if v["installed"]]
        return {
            "source_exists": src.exists(),
            "any_installed": bool(installed_entries),
            "all_installed_up_to_date": bool(installed_entries)
            and all(v["up_to_date"] for v in installed_entries),
            "versions": per_version,
        }

    def install_startup_script(self):
        """Copy blender_spacemouse_sync.py to every Blender version's startup dir.

        Returns the list of (version, path) entries that were written
        (empty if the bundled source is missing). Uses plain copy (not
        copy2) so each destination's mtime reflects the install time —
        the UI surfaces that to the user as "Last install: ...".
        """
        src = self._script_source_path()
        if not src.exists():
            return []
        written = []
        for version, dir_ in blender_install_targets():
            dir_.mkdir(parents=True, exist_ok=True)
            dst = dir_ / BLENDER_SYNC_SCRIPT
            shutil.copy(src, dst)
            written.append((version, dst))
        return written

    def uninstall_startup_script(self):
        """Remove the startup script from every Blender version where it exists.

        Returns the list of (version, path) entries that were removed.
        Iterates over *discovered* versions (not install_targets) so an
        uninstall after a Blender version dir was deleted manually does
        not leak orphan files — it only acts on what's actually there.
        """
        removed = []
        for version, dir_ in discover_blender_versions():
            dst = dir_ / BLENDER_SYNC_SCRIPT
            try:
                dst.unlink()
                removed.append((version, dst))
            except FileNotFoundError:
                pass
        return removed
