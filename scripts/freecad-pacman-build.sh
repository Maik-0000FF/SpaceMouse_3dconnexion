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
PATCH_FILE="$REPO_DIR/freecad-patches/spacemouse-smooth-navigation.patch"
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

if [[ ! -f "$PATCH_FILE" ]]; then
    fail "Patch not found: $PATCH_FILE"
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

# ── Copy patch into build dir ────────────────────────────────────

cp "$PATCH_FILE" "$WORK_DIR/spacemouse-smooth-navigation.patch"
ok "Patch copied to build directory"

# ── Modify PKGBUILD to include our patch ─────────────────────────

if grep -q "spacemouse-smooth-navigation.patch" PKGBUILD; then
    info "PKGBUILD already patched"
else
    info "Adding SpaceMouse patch to PKGBUILD..."

    python3 << 'PATCHSCRIPT'
import re

with open("PKGBUILD", "r") as f:
    content = f.read()

# Add patch file to source array
# Find the source=( ... ) block and add our patch
if "spacemouse-smooth-navigation.patch" not in content:
    # Add to source array - find the closing ) of source=(
    # Handle both single-line and multi-line source arrays
    content = re.sub(
        r'(source=\([^)]*)',
        r'\1\n        "spacemouse-smooth-navigation.patch"',
        content,
        count=1
    )

    # Add to sha256sums or b2sums - add SKIP for our local file
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

    # Add patch command to prepare() function
    if "prepare()" in content:
        content = content.replace(
            "prepare() {",
            'prepare() {\n  # SpaceMouse smooth navigation patch\n  patch -Np1 -i "$srcdir/spacemouse-smooth-navigation.patch"'
        )
    else:
        # No prepare() exists, add one before build()
        content = content.replace(
            "build() {",
            'prepare() {\n  cd "${pkgname}-${pkgver}"\n  # SpaceMouse smooth navigation patch\n  patch -Np1 -i "$srcdir/spacemouse-smooth-navigation.patch"\n}\n\nbuild() {'
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
