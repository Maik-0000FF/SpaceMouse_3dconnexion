#!/usr/bin/env bash
#
# Build FreeCAD with SpaceMouse smooth navigation patch
#
# Fixes jerky SpaceMouse input on Linux by:
#   1. Coalescing spnav events (only latest motion per poll cycle)
#   2. Batching Coin3D camera updates (single redraw per event)
#   3. Per-axis deadzone filtering (reads from user.cfg)
#
# Usage:
#   ./freecad-build-patched.sh                    # Build using existing source
#   ./freecad-build-patched.sh --clone            # Clone FreeCAD source first
#   ./freecad-build-patched.sh --clone 1.0.2      # Clone specific version tag
#   ./freecad-build-patched.sh --install          # Build + install to ~/.local
#
# Requirements:
#   Arch: sudo pacman -S cmake ninja qt6-base python pyside6 opencascade
#         coin vtk xerces-c boost eigen fmt yaml-cpp med-salome hdf5
#         libspnav pivy pybind11
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH_SCRIPT="$SCRIPT_DIR/../freecad-patches/apply-spacemouse-fix.py"
BUILD_BASE="$SCRIPT_DIR/../freecad-build"
INSTALL_PREFIX="$HOME/.local"

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

DO_CLONE=false
DO_INSTALL=false
FC_TAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clone)
            DO_CLONE=true
            if [[ "${2:-}" =~ ^[0-9] ]]; then
                FC_TAG="$2"
                shift
            fi
            ;;
        --install)
            DO_INSTALL=true
            ;;
        --help|-h)
            head -17 "$0" | tail -15
            exit 0
            ;;
        *)
            warn "Unknown option: $1"
            ;;
    esac
    shift
done

# ── Check patch script ────────────────────────────────────────────

if [[ ! -f "$PATCH_SCRIPT" ]]; then
    fail "Patch script not found: $PATCH_SCRIPT"
fi

ok "Patch script: $PATCH_SCRIPT"

# ── Clone source if requested ────────────────────────────────────

if $DO_CLONE; then
    if [[ -d "$BUILD_BASE/.git" ]]; then
        warn "Source directory already exists: $BUILD_BASE"
        info "Pulling latest changes..."
        cd "$BUILD_BASE"
        git checkout -- . 2>/dev/null || true
        git pull
    else
        info "Cloning FreeCAD source..."
        git clone --depth=1 \
            ${FC_TAG:+--branch "$FC_TAG"} \
            https://github.com/FreeCAD/FreeCAD.git "$BUILD_BASE"
    fi
fi

# ── Verify source exists ─────────────────────────────────────────

if [[ ! -f "$BUILD_BASE/src/Gui/3Dconnexion/GuiNativeEventLinux.cpp" ]]; then
    fail "FreeCAD source not found at: $BUILD_BASE
    Use --clone to download, or symlink your source tree to:
    $BUILD_BASE"
fi

ok "FreeCAD source: $BUILD_BASE"

# ── Apply patch ──────────────────────────────────────────────────

info "Applying SpaceMouse patch..."
if python3 "$PATCH_SCRIPT" "$BUILD_BASE"; then
    ok "Patch applied successfully"
else
    fail "Patch failed to apply. See errors above."
fi

# ── Fix HDF5 2.0 compatibility ──────────────────────────────────
# Arch HDF5 2.0: pkg-config module is "hdf5", FreeCAD cmake expects "hdf5-serial"
# cmake also strips /usr/include from INCLUDE_DIRS (system dir), breaking find_file

SMESH_CMAKE="$BUILD_BASE/cMake/FreeCAD_Helpers/SetupSalomeSMESH.cmake"
if [[ -f "$SMESH_CMAKE" ]] && grep -q 'hdf5-serial' "$SMESH_CMAKE"; then
    info "Fixing HDF5 2.0 cmake compatibility..."
    sed -i -e 's/set(HDF5_VARIANT "hdf5-serial")/set(HDF5_VARIANT "hdf5")/' \
           -e 's/find_file(Hdf5dotH hdf5.h PATHS ${HDF5_INCLUDE_DIRS} NO_DEFAULT_PATH)/find_file(Hdf5dotH hdf5.h)/' \
        "$SMESH_CMAKE"
    ok "HDF5 cmake fix applied"
fi

# ── Configure (cmake) ───────────────────────────────────────────

BUILD_DIR="$BUILD_BASE/build"
mkdir -p "$BUILD_DIR"

if [[ ! -f "$BUILD_DIR/build.ninja" ]]; then
    info "Configuring build with cmake..."
    cmake -B "$BUILD_DIR" -S "$BUILD_BASE" \
        -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
        -DBUILD_QT5=OFF \
        2>&1 | tail -5
    ok "CMake configuration done"
else
    info "Build already configured, reusing existing config."
fi

# ── Build ────────────────────────────────────────────────────────

JOBS="$(nproc)"
info "Building FreeCAD with ${JOBS} jobs..."

if ninja -C "$BUILD_DIR" -j"$JOBS" bin/FreeCAD 2>&1 | tail -5; then
    ok "Build successful"
else
    fail "Build failed. Check output above."
fi

# ── Verify binary ────────────────────────────────────────────────

FREECAD_BIN="$BUILD_DIR/bin/FreeCAD"
if [[ -x "$FREECAD_BIN" ]]; then
    ok "Binary: $FREECAD_BIN"
else
    fail "Binary not found at $FREECAD_BIN"
fi

# ── Install if requested ────────────────────────────────────────

if $DO_INSTALL; then
    info "Installing to $INSTALL_PREFIX..."
    ninja -C "$BUILD_DIR" install 2>&1 | tail -3
    ok "Installed to $INSTALL_PREFIX"
fi

# ── Done ─────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}FreeCAD with SpaceMouse patch is ready.${NC}"
echo ""
echo -e "  ${BOLD}Run:${NC}"
echo "    $FREECAD_BIN"
echo ""
echo -e "  ${BOLD}Sensitivity (in FreeCAD Python console):${NC}"
echo '    p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Spaceball/Motion")'
echo '    p.SetInt("GlobalSensitivity", -15)'
echo ""
if ! $DO_INSTALL; then
    echo -e "  ${BOLD}Optional — install system-wide:${NC}"
    echo "    $0 --install"
    echo ""
fi
