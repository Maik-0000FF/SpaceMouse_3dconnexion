#!/usr/bin/env bash
#
# Build patched FreeCAD as Arch Linux pacman package
#
# Downloads the official PKGBUILD, applies the SpaceMouse smooth
# navigation patch, and builds a proper pacman package.
#
# Usage:
#   ./freecad-pacman-build.sh           # Build package
#   ./freecad-pacman-build.sh --install # Build + install with pacman
#
# The resulting package can be reinstalled anytime with:
#   sudo pacman -U freecad-build/pkg/freecad-*.pkg.tar.zst
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PATCH_SCRIPT="$REPO_DIR/freecad-patches/apply-spacemouse-fix.py"
WORK_DIR="$REPO_DIR/freecad-pacman-build"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

DO_INSTALL=false
[[ "${1:-}" == "--install" ]] && DO_INSTALL=true

# ── Check prerequisites ─────────────────────────────────────────

if [[ ! -f "$PATCH_SCRIPT" ]]; then
    fail "Patch script not found: $PATCH_SCRIPT"
fi

if ! command -v makepkg &>/dev/null; then
    fail "makepkg not found (part of pacman)"
fi

# ── Get PKGBUILD ─────────────────────────────────────────────────

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

if [[ ! -f PKGBUILD ]]; then
    info "Downloading FreeCAD PKGBUILD from Arch repos..."

    # Try asp first, then pkgctl, then direct download
    if command -v asp &>/dev/null; then
        asp checkout freecad
        cp freecad/trunk/* .
        rm -rf freecad
    elif command -v pkgctl &>/dev/null; then
        pkgctl repo clone freecad --protocol=https
        cp freecad/* .
        rm -rf freecad
    else
        # Direct download from Arch GitLab
        info "Downloading from gitlab.archlinux.org..."
        curl -sL "https://gitlab.archlinux.org/archlinux/packaging/packages/freecad/-/raw/main/PKGBUILD" \
            -o PKGBUILD

        if [[ ! -s PKGBUILD ]]; then
            fail "Could not download PKGBUILD.
    Install asp (sudo pacman -S asp) or pkgctl (sudo pacman -S devtools) and retry."
        fi
    fi
    ok "PKGBUILD downloaded"
else
    info "Using existing PKGBUILD"
fi

# ── Copy patch script into build dir ─────────────────────────────

cp "$PATCH_SCRIPT" "$WORK_DIR/apply-spacemouse-fix.py"
ok "Patch script copied to build directory"

# ── Modify PKGBUILD to include our patch ─────────────────────────

if grep -q "apply-spacemouse-fix.py" PKGBUILD; then
    info "PKGBUILD already patched"
else
    info "Adding SpaceMouse patch to PKGBUILD..."

    python3 << 'PATCHSCRIPT'
import re

with open("PKGBUILD", "r") as f:
    content = f.read()

if "apply-spacemouse-fix.py" not in content:
    # Add to source array
    content = re.sub(
        r'(source=\([^)]*)',
        r'\1\n        apply-spacemouse-fix.py',
        content,
        count=1
    )

    # Add SKIP checksum for our local file
    for sums_name in ['b2sums', 'sha256sums', 'sha512sums', 'md5sums']:
        pattern = rf'({sums_name}=\([^)]*)'
        if re.search(pattern, content):
            content = re.sub(
                pattern,
                rf'\1\n        SKIP',
                content,
                count=1
            )
            break

    # HDF5 2.0 fix + SpaceMouse patch for prepare()
    hdf5_fix = (
        '  # Arch HDF5 2.0: pkg-config module is "hdf5", not "hdf5-serial"\n'
        '  sed -i -e \'s/set(HDF5_VARIANT "hdf5-serial")/set(HDF5_VARIANT "hdf5")/\' \\\n'
        '         -e \'s/find_file(Hdf5dotH hdf5.h PATHS ${HDF5_INCLUDE_DIRS} NO_DEFAULT_PATH)/find_file(Hdf5dotH hdf5.h)/\' \\\n'
        '    cMake/FreeCAD_Helpers/SetupSalomeSMESH.cmake 2>/dev/null || true'
    )
    spacemouse_fix = '  python3 "$srcdir/apply-spacemouse-fix.py" .'
    patch_block = f'  # SpaceMouse smooth navigation patch\n{spacemouse_fix}\n{hdf5_fix}'

    # Add to prepare() function
    if "prepare()" in content:
        content = content.replace(
            "prepare() {",
            'prepare() {\n' + patch_block
        )
    else:
        content = content.replace(
            "build() {",
            'prepare() {\n  cd "${pkgname}-${pkgver}"\n' + patch_block + '\n}\n\nbuild() {'
        )

with open("PKGBUILD", "w") as f:
    f.write(content)

print("  PKGBUILD modified: source, checksums, and prepare() updated")
PATCHSCRIPT

    ok "PKGBUILD patched"
fi

# ── Update checksums ─────────────────────────────────────────────

info "Updating checksums..."
updpkgsums 2>/dev/null || makepkg -g >> PKGBUILD 2>/dev/null || warn "Could not auto-update checksums (install pacman-contrib for updpkgsums)"

# ── Build package ────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Building FreeCAD package (this takes a while)...${NC}"
echo ""

makepkg -sf --noconfirm 2>&1 | tail -20

PKG_FILE=$(ls -t "$WORK_DIR"/*.pkg.tar.zst 2>/dev/null | head -1)

if [[ -z "$PKG_FILE" ]]; then
    fail "Package build failed. Check output above."
fi

ok "Package built: $PKG_FILE"

# ── Install if requested ────────────────────────────────────────

if $DO_INSTALL; then
    echo ""
    info "Installing package..."
    sudo pacman -U --noconfirm "$PKG_FILE"
    ok "Installed! FreeCAD with SpaceMouse patch is now your system FreeCAD."
fi

# ── Done ─────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}Package ready.${NC}"
echo ""
echo -e "  ${BOLD}Install with:${NC}"
echo "    sudo pacman -U $PKG_FILE"
echo ""
echo -e "  ${BOLD}After a pacman update overwrites it, rebuild with:${NC}"
echo "    $0 --install"
echo ""
echo -e "  ${BOLD}Sensitivity (in FreeCAD Python console):${NC}"
echo '    p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Spaceball/Motion")'
echo '    p.SetInt("GlobalSensitivity", -15)'
echo ""
