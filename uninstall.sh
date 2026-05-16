#!/usr/bin/env bash
#
# SpaceMouse Driver Uninstall Script
#
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "[INFO] $*"; }
ok() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

echo -e "${BOLD}SpaceMouse Uninstaller${NC}\n"

# ── Stop and disable desktop daemon ─────────────────────────────

info "Stopping spacemouse-desktop..."
systemctl --user stop spacemouse-desktop.service 2>/dev/null || true
systemctl --user disable spacemouse-desktop.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/spacemouse-desktop.service"
ok "Desktop daemon stopped and disabled"

info "Stopping spacemouse-config GUI..."
systemctl --user stop spacemouse-config.service 2>/dev/null || true
systemctl --user disable spacemouse-config.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/spacemouse-config.service"
ok "Config GUI stopped and disabled"

systemctl --user daemon-reload

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
rm -f "$HOME/.local/bin/spacemouse-config.py"
rm -rf "$HOME/.local/share/spacemouse/spacemouse_config"
rm -f "$HOME/.local/share/spacemouse/blender_spacemouse_sync.py"
rmdir "$HOME/.local/share/spacemouse" 2>/dev/null || true
# Legacy package directory from older install layouts.
rm -rf "$HOME/.local/bin/spacemouse_config"
# Blender startup script — the GUI's "Install startup script" button copies
# blender_spacemouse_sync.py here, possibly across multiple Blender versions.
for d in "$HOME"/.config/blender/*/scripts/startup; do
    [[ -d "$d" ]] || continue
    rm -f "$d/spacemouse_sync.py"
done
ok "Binaries and GUI removed"

read -rp "Remove config directory ~/.config/spacemouse/? [y/N] " ans
if [[ "$ans" == [yY] ]]; then
    rm -rf "$HOME/.config/spacemouse"
    ok "Config directory removed"
fi

# Remove pip venv created on Debian 12 / Ubuntu 24.04 (PySide6 fallback)
if [[ -d "$HOME/.local/share/spacemouse-venv" ]]; then
    read -rp "Remove PySide6 venv at ~/.local/share/spacemouse-venv? [y/N] " ans
    if [[ "$ans" == [yY] ]]; then
        rm -rf "$HOME/.local/share/spacemouse-venv"
        ok "PySide6 venv removed"
    fi
fi

# ── Optionally remove packages ──────────────────────────────────

read -rp "Remove spacenavd package? [y/N] " ans
if [[ "$ans" == [yY] ]]; then
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
    fi
    case " ${ID:-} ${ID_LIKE:-} " in
        *" arch "*)
            if command -v yay &>/dev/null; then
                yay -R --noconfirm spacenavd 2>/dev/null || true
            elif command -v paru &>/dev/null; then
                paru -R --noconfirm spacenavd 2>/dev/null || true
            fi
            ;;
        *" fedora "* | *" rhel "* | *" centos "*)
            sudo dnf remove -y spacenavd 2>/dev/null || true
            ;;
        *" debian "* | *" ubuntu "*)
            sudo apt-get remove -y spacenavd 2>/dev/null || true
            ;;
        *" opensuse "* | *" opensuse-tumbleweed "* | *" opensuse-leap "* | *" suse "* | *" sles "*)
            sudo zypper --non-interactive remove spacenavd 2>/dev/null || true
            ;;
    esac
    ok "spacenavd removed"
fi

echo ""
echo -e "${BOLD}Uninstall complete.${NC}"
echo "Note: libspnav was NOT removed (may be needed by Blender/FreeCAD)."
echo ""
