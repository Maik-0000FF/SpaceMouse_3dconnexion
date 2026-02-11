#!/usr/bin/env bash
#
# FreeCAD SpaceMouse Configuration Patch
# Configures FreeCAD for direct viewport manipulation with SpaceMouse
# (orbit, pan, zoom like Blender instead of cube-only navigation)
#
# What this does:
#   - Enables LegacySpaceMouseDevices (required for spacenavd on Linux)
#   - Sets Blender navigation style + Trackball orbit
#   - Enables FlipYZ for intuitive zoom direction
#   - Enables all 6DOF axes (pan, zoom, tilt, roll, spin)
#   - Sets rotation mode to object center
#
# Usage: ./freecad-spacemouse-patch.sh [--restore]
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }

# ── Locate user.cfg ──────────────────────────────────────────────

USER_CFG=""
for candidate in \
    "$HOME/.config/FreeCAD/user.cfg" \
    "$HOME/.FreeCAD/user.cfg" \
    "$HOME/.local/share/FreeCAD/user.cfg"; do
    if [[ -f "$candidate" ]]; then
        USER_CFG="$candidate"
        break
    fi
done

if [[ -z "$USER_CFG" ]]; then
    if command -v freecad &>/dev/null || command -v FreeCAD &>/dev/null; then
        fail "FreeCAD is installed but no user.cfg found."
        info "Start FreeCAD once to generate it, then re-run this script."
    else
        fail "FreeCAD does not appear to be installed."
    fi
    exit 1
fi

info "Found user.cfg: $USER_CFG"

# ── Restore mode ─────────────────────────────────────────────────

if [[ "${1:-}" == "--restore" ]]; then
    BACKUP="$USER_CFG.spacemouse-backup"
    if [[ -f "$BACKUP" ]]; then
        cp "$BACKUP" "$USER_CFG"
        ok "Restored from backup: $BACKUP"
    else
        fail "No backup found at $BACKUP"
        exit 1
    fi
    exit 0
fi

# ── Backup ───────────────────────────────────────────────────────

BACKUP="$USER_CFG.spacemouse-backup"
if [[ ! -f "$BACKUP" ]]; then
    cp "$USER_CFG" "$BACKUP"
    ok "Backup created: $BACKUP"
else
    info "Backup already exists (not overwritten): $BACKUP"
fi

# ── Patch via Python XML manipulation ────────────────────────────

info "Patching FreeCAD configuration..."

USER_CFG_PATH="$USER_CFG" python3 << 'PYTHON_PATCH'
import xml.etree.ElementTree as ET
import os

user_cfg = os.environ["USER_CFG_PATH"]
tree = ET.parse(user_cfg)
xml_root = tree.getroot()  # <FCParameters>

def find_group(parent, name):
    """Find an existing FCParamGroup by Name attribute."""
    for child in parent:
        if child.tag == "FCParamGroup" and child.get("Name") == name:
            return child
    return None

def ensure_group(parent, name):
    """Find or create an FCParamGroup with the given Name attribute."""
    grp = find_group(parent, name)
    if grp is not None:
        return grp
    return ET.SubElement(parent, "FCParamGroup", Name=name)

def set_bool(parent, name, value):
    val_str = "1" if value else "0"
    for child in parent:
        if child.tag == "FCBool" and child.get("Name") == name:
            old = child.get("Value")
            if old != val_str:
                child.set("Value", val_str)
                print(f"  Changed {name}: {old} -> {val_str}")
            else:
                print(f"  {name} already OK ({val_str})")
            return
    ET.SubElement(parent, "FCBool", Name=name, Value=val_str)
    print(f"  Added {name} = {val_str}")

def set_int(parent, name, value):
    val_str = str(value)
    for child in parent:
        if child.tag == "FCInt" and child.get("Name") == name:
            old = child.get("Value")
            if old != val_str:
                child.set("Value", val_str)
                print(f"  Changed {name}: {old} -> {val_str}")
            else:
                print(f"  {name} already OK ({val_str})")
            return
    ET.SubElement(parent, "FCInt", Name=name, Value=val_str)
    print(f"  Added {name} = {val_str}")

def set_text(parent, name, value):
    """Handle both FreeCAD XML formats:
       - Attribute format: <FCText Name="foo" Value="bar"/>
       - Text content format: <FCText Name="foo">bar</FCText>
    """
    for child in parent:
        if child.tag == "FCText" and child.get("Name") == name:
            # Check attribute format first
            old = child.get("Value")
            if old is not None:
                if old != value:
                    child.set("Value", value)
                    print(f"  Changed {name}: {old} -> {value}")
                else:
                    print(f"  {name} already OK ({value})")
                return
            # Text content format
            old = (child.text or "").strip()
            if old != value:
                child.text = value
                print(f"  Changed {name}: {old} -> {value}")
            else:
                print(f"  {name} already OK ({value})")
            return
    # Create in text content format (matches FreeCAD's native style)
    elem = ET.SubElement(parent, "FCText", Name=name)
    elem.text = value
    print(f"  Added {name} = {value}")

# ── Navigate the real FreeCAD XML hierarchy ──
# Structure: <FCParameters> -> <FCParamGroup Name="Root"> -> <FCParamGroup Name="BaseApp">
fc_root = find_group(xml_root, "Root")
if fc_root is None:
    print("[FAIL] <FCParamGroup Name='Root'> not found in user.cfg")
    raise SystemExit(1)

base_app = find_group(fc_root, "BaseApp")
if base_app is None:
    print("[FAIL] <FCParamGroup Name='BaseApp'> not found under Root")
    raise SystemExit(1)

# ── View preferences: Root/BaseApp/Preferences/View ──
prefs = ensure_group(base_app, "Preferences")
view = ensure_group(prefs, "View")

print("\n[View Preferences]")
set_bool(view, "LegacySpaceMouseDevices", True)
set_text(view, "NavigationStyle", "Gui::BlenderNavigationStyle")
set_int(view, "OrbitStyle", 1)        # Trackball
set_int(view, "RotationMode", 2)      # Object center

# ── Spaceball motion: Root/BaseApp/Spaceball/Motion ──
# Note: This is BaseApp/Spaceball, NOT BaseApp/Preferences/Spaceball
spaceball = ensure_group(base_app, "Spaceball")
motion = ensure_group(spaceball, "Motion")

print("\n[Spaceball Motion]")
set_bool(motion, "Dominant", False)
set_bool(motion, "FlipYZ", True)

set_bool(motion, "Translations", True)
set_bool(motion, "PanLREnable", True)
set_bool(motion, "PanUDEnable", True)
set_bool(motion, "ZoomEnable", True)

set_bool(motion, "Rotations", True)
set_bool(motion, "TiltEnable", True)
set_bool(motion, "RollEnable", True)
set_bool(motion, "SpinEnable", True)

# GlobalSensitivity = 0 (default). The SpaceNavFix addon overrides
# this at runtime to -45 for controlled sensitivity.
# Valid range: -55 (1%) to 0 (100%). Below -55 INVERTS axes!
set_int(motion, "GlobalSensitivity", 0)
set_int(motion, "PanLRSensitivity", 0)
set_int(motion, "PanUDSensitivity", 0)
set_int(motion, "ZoomSensitivity", 0)
set_int(motion, "TiltSensitivity", 0)
set_int(motion, "RollSensitivity", 0)
set_int(motion, "SpinSensitivity", 0)

set_int(motion, "Remapping", 12345)

set_bool(motion, "PanLRReverse", False)
set_bool(motion, "PanUDReverse", False)
set_bool(motion, "ZoomReverse", False)
set_bool(motion, "TiltReverse", False)
set_bool(motion, "RollReverse", False)
set_bool(motion, "SpinReverse", False)

# ── Spaceball buttons: Root/BaseApp/Spaceball/Buttons ──
buttons = ensure_group(spaceball, "Buttons")

print("\n[Spaceball Buttons]")
set_text(buttons, "0", "Std_ViewFitAll")
set_text(buttons, "1", "Std_ViewHome")

tree.write(user_cfg, xml_declaration=True, encoding="utf-8")
print("\n[Done] Configuration patched successfully.")
PYTHON_PATCH

echo ""
ok "FreeCAD SpaceMouse patch applied!"
echo ""
echo -e "  ${BOLD}What was changed:${NC}"
echo "    - LegacySpaceMouseDevices enabled (required for spacenavd on Linux)"
echo "    - Navigation style: Blender + Trackball orbit"
echo "    - Rotation mode: Object center"
echo "    - FlipYZ enabled (intuitive zoom direction)"
echo "    - All 6DOF axes enabled (pan, zoom, tilt, roll, spin)"
echo "    - Button 0: Fit All, Button 1: Home View"
echo ""
echo -e "  ${BOLD}Next step — build FreeCAD with SpaceMouse patch:${NC}"
echo "    ./scripts/freecad-build-patched.sh"
echo ""
echo -e "  ${YELLOW}FreeCAD must be restarted for changes to take effect.${NC}"
echo ""
echo -e "  To restore original settings:"
echo "    $0 --restore"
