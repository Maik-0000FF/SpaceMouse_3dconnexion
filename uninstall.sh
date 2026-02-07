#!/usr/bin/env bash
#
# SpaceMouse Driver Uninstall Script
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "[INFO] $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo -e "${BOLD}SpaceMouse Uninstaller${NC}\n"

# ── Stop and disable desktop daemon ─────────────────────────────

info "Stopping spacemouse-desktop..."
systemctl --user stop spacemouse-desktop.service 2>/dev/null || true
systemctl --user disable spacemouse-desktop.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/spacemouse-desktop.service"
systemctl --user daemon-reload
ok "Desktop daemon stopped and disabled"

# ── Stop spacenavd ──────────────────────────────────────────────

info "Stopping spacenavd..."
sudo systemctl stop spacenavd.service 2>/dev/null || true
sudo systemctl disable spacenavd.service 2>/dev/null || true
ok "spacenavd stopped and disabled"

# ── Remove configuration ────────────────────────────────────────

info "Removing configuration..."
sudo rm -f /etc/udev/rules.d/99-spacemouse.rules
sudo rm -f /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules 2>/dev/null || true
ok "udev rules removed"

if [[ -f /etc/spnavrc ]]; then
    sudo rm -f /etc/spnavrc
    ok "spnavrc removed"
fi

# ── Remove user files ───────────────────────────────────────────

info "Removing user files..."
rm -f "$HOME/.local/bin/spacemouse-desktop"
rm -f "$HOME/.local/bin/spacemouse-test"
rm -f "$HOME/.local/bin/spnav_example"
ok "Binaries removed"

read -rp "Remove config directory ~/.config/spacemouse/? [y/N] " ans
if [[ "$ans" == [yY] ]]; then
    rm -rf "$HOME/.config/spacemouse"
    ok "Config directory removed"
fi

# ── Optionally remove packages ──────────────────────────────────

read -rp "Remove spacenavd package? [y/N] " ans
if [[ "$ans" == [yY] ]]; then
    if command -v yay &>/dev/null; then
        yay -R --noconfirm spacenavd 2>/dev/null || true
    elif command -v paru &>/dev/null; then
        paru -R --noconfirm spacenavd 2>/dev/null || true
    fi
    ok "spacenavd removed"
fi

echo ""
echo -e "${BOLD}Uninstall complete.${NC}"
echo "Note: libspnav was NOT removed (may be needed by Blender/FreeCAD)."
echo ""
