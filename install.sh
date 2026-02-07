#!/usr/bin/env bash
#
# SpaceMouse Driver Installation Script for Arch Linux
# Installs spacenavd, configures udev, builds tools, sets up systemd services
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
step()  { echo -e "\n${BOLD}==> $*${NC}"; }

# ── Preflight checks ───────────────────────────────────────────────

step "Preflight checks"

if [[ $EUID -eq 0 ]]; then
    fail "Do not run as root. The script will use sudo where needed."
    exit 1
fi

if [[ ! -f /etc/arch-release ]]; then
    fail "This script is designed for Arch Linux."
    exit 1
fi

if ! command -v yay &>/dev/null && ! command -v paru &>/dev/null; then
    fail "No AUR helper found. Install yay or paru first."
    exit 1
fi

AUR_HELPER="yay"
if ! command -v yay &>/dev/null; then
    AUR_HELPER="paru"
fi

ok "Arch Linux detected, AUR helper: $AUR_HELPER"

# ── Package installation ───────────────────────────────────────────

step "Installing packages"

# Official repos
OFFICIAL_PKGS="libspnav json-c dbus"
for pkg in $OFFICIAL_PKGS; do
    if pacman -Q "$pkg" &>/dev/null; then
        ok "$pkg already installed"
    else
        info "Installing $pkg..."
        sudo pacman -S --needed --noconfirm "$pkg"
        ok "$pkg installed"
    fi
done

# AUR: spacenavd
if pacman -Q spacenavd &>/dev/null; then
    ok "spacenavd already installed"
else
    info "Installing spacenavd from AUR..."
    $AUR_HELPER -S --needed --noconfirm spacenavd
    ok "spacenavd installed"
fi

# ── udev rules ─────────────────────────────────────────────────────

step "Installing udev rules"

sudo cp "$SCRIPT_DIR/config/99-spacemouse.rules" /etc/udev/rules.d/99-spacemouse.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
ok "udev rules installed and reloaded"

# ── spacenavd configuration ───────────────────────────────────────

step "Configuring spacenavd"

if [[ -f /etc/spnavrc ]]; then
    sudo cp /etc/spnavrc "/etc/spnavrc.backup.$(date +%Y%m%d%H%M%S)"
    warn "Existing /etc/spnavrc backed up"
fi
sudo cp "$SCRIPT_DIR/config/spnavrc" /etc/spnavrc
ok "spnavrc installed"

# ── Start spacenavd ───────────────────────────────────────────────

step "Enabling spacenavd"

sudo systemctl enable spacenavd.service
sudo systemctl restart spacenavd.service
sleep 1

if systemctl is-active --quiet spacenavd.service; then
    ok "spacenavd is running"
else
    warn "spacenavd failed to start (device may not be connected)"
fi

# ── Build C programs ──────────────────────────────────────────────

step "Building tools"

make -C "$SCRIPT_DIR/src" clean
make -C "$SCRIPT_DIR/src"
ok "All tools compiled"

# ── Install binaries ─────────────────────────────────────────────

step "Installing binaries"

mkdir -p "$HOME/.local/bin"

install -m755 "$SCRIPT_DIR/src/spacemouse-desktop" "$HOME/.local/bin/spacemouse-desktop"
install -m755 "$SCRIPT_DIR/src/spacemouse-test" "$HOME/.local/bin/spacemouse-test"
install -m755 "$SCRIPT_DIR/src/spnav_example" "$HOME/.local/bin/spnav_example"
install -m755 "$SCRIPT_DIR/gui/spacemouse-config.py" "$HOME/.local/bin/spacemouse-config.py"
ok "Binaries and GUI installed to ~/.local/bin/"

# Ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin is not in PATH. Add to your shell profile:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── Desktop daemon config ────────────────────────────────────────

step "Installing desktop daemon configuration"

mkdir -p "$HOME/.config/spacemouse"
if [[ ! -f "$HOME/.config/spacemouse/config.json" ]]; then
    cp "$SCRIPT_DIR/config/spacemouse-desktop.conf" "$HOME/.config/spacemouse/config.json"
    ok "Config installed to ~/.config/spacemouse/config.json"
else
    ok "Config already exists (not overwritten)"
fi

# ── systemd user service ─────────────────────────────────────────

step "Installing systemd user service"

mkdir -p "$HOME/.config/systemd/user"
cp "$SCRIPT_DIR/systemd/spacemouse-desktop.service" "$HOME/.config/systemd/user/"
cp "$SCRIPT_DIR/systemd/spacemouse-config.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable spacemouse-desktop.service
systemctl --user enable spacemouse-config.service

# Check if uinput is accessible
if [[ -w /dev/uinput ]]; then
    systemctl --user restart spacemouse-desktop.service
    sleep 1
    if systemctl --user is-active --quiet spacemouse-desktop.service; then
        ok "spacemouse-desktop daemon is running"
    else
        warn "spacemouse-desktop failed to start. Check: journalctl --user -u spacemouse-desktop"
    fi
else
    warn "/dev/uinput not writable. Adding udev rule..."
    echo 'KERNEL=="uinput", MODE="0666", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/99-uinput.rules > /dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    warn "Uinput rule added. Re-login or reboot may be required for it to take effect."
    warn "Then run: systemctl --user restart spacemouse-desktop.service"
fi

ok "systemd user service installed"

# ── Verification ─────────────────────────────────────────────────

step "Running diagnostics"

"$HOME/.local/bin/spacemouse-test" --check || true

# ── Summary ──────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  SpaceMouse Setup Complete!${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════${NC}"
echo ""
echo "  Installed components:"
echo "    - spacenavd daemon (system service)"
echo "    - spacemouse-desktop (desktop navigation daemon)"
echo "    - spacemouse-config (PySide6 GUI with system tray)"
echo "    - spacemouse-test (diagnostic tool)"
echo "    - spnav_example (libspnav C example)"
echo ""
echo "  Quick commands:"
echo "    spacemouse-test --check    Run diagnostics"
echo "    spacemouse-test --live     Live event monitor"
echo "    spacemouse-test --led      LED test"
echo ""
echo "  Configuration:"
echo "    ~/.config/spacemouse/config.json  (desktop daemon)"
echo "    /etc/spnavrc                      (spacenavd)"
echo ""
echo "  Services:"
echo "    sudo systemctl status spacenavd          (driver daemon)"
echo "    systemctl --user status spacemouse-desktop (desktop nav)"
echo ""
echo "  Blender/FreeCAD: will auto-detect SpaceMouse when started"
echo ""
echo "  FreeCAD setup (optional):"
echo "    ./scripts/freecad-spacemouse-patch.sh   Apply SpaceMouse config"
echo "    ./scripts/freecad-spacemouse-patch.sh --restore   Undo changes"
echo ""
