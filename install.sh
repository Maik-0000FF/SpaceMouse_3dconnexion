#!/usr/bin/env bash
#
# SpaceMouse Linux Control — installer
# Supports Arch (+ derivatives), Fedora, Debian/Ubuntu, openSUSE
# Installs the upstream driver stack (spacenavd), configures udev, builds
# this project's control daemon + GUI, sets up systemd user services.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${CYAN}[INFO]${NC} $*"; }
ok() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
step() { echo -e "\n${BOLD}==> $*${NC}"; }

# ── Preflight checks ───────────────────────────────────────────────

step "Preflight checks"

if [[ $EUID -eq 0 ]]; then
    fail "Do not run as root. The script will use sudo where needed."
    exit 1
fi

if [[ ! -r /etc/os-release ]]; then
    fail "Cannot read /etc/os-release — unsupported system."
    exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release

# Resolve distribution family. Check ID first, then ID_LIKE for derivatives
# (Manjaro/EndeavourOS → arch, Linux Mint/Pop_OS → debian, etc.).
DISTRO_FAMILY=""
case " $ID ${ID_LIKE:-} " in
    *" arch "*) DISTRO_FAMILY="arch" ;;
    *" fedora "* | *" rhel "* | *" centos "*) DISTRO_FAMILY="fedora" ;;
    *" debian "* | *" ubuntu "*) DISTRO_FAMILY="debian" ;;
    *" opensuse "* | *" opensuse-tumbleweed "* | *" opensuse-leap "* | *" suse "* | *" sles "*) DISTRO_FAMILY="opensuse" ;;
esac

if [[ -z "$DISTRO_FAMILY" ]]; then
    fail "Unsupported distribution: $ID (ID_LIKE=${ID_LIKE:-})"
    fail "Supported: Arch, Fedora, Debian/Ubuntu, openSUSE — and their derivatives."
    exit 1
fi

ok "Distribution: $PRETTY_NAME (family: $DISTRO_FAMILY)"

# Desktop-environment detection — the daemon and 3D-app integration
# work on any desktop. Window detection and desktop switching have
# native backends per DE; KDE Plasma gets the richest support, GNOME,
# XFCE, Sway and Hyprland have working backends, others fall back to
# no-op. Hints for missing pieces (extensions, etc.) print further
# down per DE.
if [[ "${XDG_CURRENT_DESKTOP:-}" != *"KDE"* ]]; then
    info "Not running KDE Plasma (XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-unset})"
    info "Auto profile switching uses the per-DE backend; see README for the feature matrix."
fi

# /run/systemd/system exists only when systemd is PID 1 — service and udev
# management is skipped on hosts that aren't running systemd (containers,
# custom inits) so install.sh can complete without spurious failures.
HAVE_SYSTEMD=false
if [[ -d /run/systemd/system ]]; then
    HAVE_SYSTEMD=true
fi

# ── Distro-specific package definitions ───────────────────────────

# Helpers route through DISTRO_FAMILY so the rest of the script is generic.
pkg_installed() {
    case "$DISTRO_FAMILY" in
        arch) pacman -Q "$1" &>/dev/null ;;
        fedora | opensuse) rpm -q "$1" &>/dev/null ;;
        debian) dpkg -s "$1" &>/dev/null ;;
    esac
}

pkg_install() {
    case "$DISTRO_FAMILY" in
        arch) sudo pacman -S --needed --noconfirm "$@" ;;
        fedora) sudo dnf install -y "$@" ;;
        debian) sudo apt-get install -y "$@" ;;
        opensuse) sudo zypper --non-interactive install "$@" ;;
    esac
}

OFFICIAL_PKGS=()
AUR_PKGS=()
AUR_HELPER=""
PYSIDE_PIP_FALLBACK=false

case "$DISTRO_FAMILY" in
    arch)
        # xorg-xprop drives the X11 window-monitor backend (XFCE,
        # Cinnamon, MATE, LXQt and X11 sessions of KDE/GNOME).
        OFFICIAL_PKGS=(libspnav json-c dbus pyside6 gcc make pkgconf xorg-xprop)
        AUR_PKGS=(spacenavd)

        if command -v yay &>/dev/null; then
            AUR_HELPER="yay"
        elif command -v paru &>/dev/null; then
            AUR_HELPER="paru"
        else
            fail "No AUR helper found. Install yay or paru first."
            exit 1
        fi
        ok "AUR helper: $AUR_HELPER"
        ;;

    fedora)
        # Fedora 40+ ships xprop as its own package; older releases
        # bundled it in xorg-x11-utils.
        OFFICIAL_PKGS=(libspnav-devel spacenavd json-c-devel dbus-devel python3-pyside6 gcc make pkgconf-pkg-config xprop)
        ;;

    debian)
        # libx11-dev needed because spnav.h pulls in <X11/Xlib.h> and
        # bookworm doesn't auto-install it as a dependency of libspnav-dev.
        # x11-utils ships xprop for the X11 window-monitor backend.
        OFFICIAL_PKGS=(libspnav-dev spacenavd libjson-c-dev libdbus-1-dev libx11-dev gcc make pkg-config x11-utils)
        sudo apt-get update

        # PySide6 availability:
        #   Debian 12 (bookworm)        — not in apt (added in Debian 13)
        #   Ubuntu 24.04 LTS (noble)    — not in apt (added in 24.10)
        #   Newer releases              — apt package: python3-pyside6.qtwidgets
        if apt-cache show python3-pyside6.qtwidgets &>/dev/null; then
            OFFICIAL_PKGS+=(python3-pyside6.qtwidgets)
        else
            warn "PySide6 is not in your apt repositories (Debian 12 / Ubuntu 24.04 or older)."
            warn "Will set up a Python venv with pip-installed PySide6 instead."
            PYSIDE_PIP_FALLBACK=true
            OFFICIAL_PKGS+=(python3-venv python3-pip)
        fi
        ;;

    opensuse)
        # libspnav-devel on openSUSE pulls in X11 headers via spnav.h.
        # xprop drives the X11 window-monitor backend.
        OFFICIAL_PKGS=(libspnav-devel spacenavd libjson-c-devel dbus-1-devel libX11-devel python3-pyside6 gcc make pkg-config xprop)
        ;;
esac

# ── Package installation ───────────────────────────────────────────

step "Installing packages"

for pkg in "${OFFICIAL_PKGS[@]}"; do
    if pkg_installed "$pkg"; then
        ok "$pkg already installed"
    else
        info "Installing $pkg..."
        pkg_install "$pkg"
        ok "$pkg installed"
    fi
done

# Arch: spacenavd from AUR (other distros pull it from official repos above)
for pkg in "${AUR_PKGS[@]}"; do
    if pkg_installed "$pkg"; then
        ok "$pkg already installed"
    else
        info "Installing $pkg from AUR..."
        "$AUR_HELPER" -S --needed --noconfirm "$pkg"
        ok "$pkg installed"
    fi
done

# Optional pip venv for PySide6 on older Debian/Ubuntu
if $PYSIDE_PIP_FALLBACK; then
    step "Setting up PySide6 in a Python venv"
    VENV_DIR="$HOME/.local/share/spacemouse-venv"
    if [[ ! -d "$VENV_DIR" ]]; then
        python3 -m venv "$VENV_DIR"
        ok "venv created at $VENV_DIR"
    fi
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install PySide6
    ok "PySide6 installed in venv"
    info "GUI will run with: $VENV_DIR/bin/python3 ~/.local/bin/spacemouse-config.py"
fi

# ── udev rules ─────────────────────────────────────────────────────

step "Installing udev rules"

sudo mkdir -p /etc/udev/rules.d
sudo cp "$SCRIPT_DIR/config/99-spacemouse.rules" /etc/udev/rules.d/99-spacemouse.rules
if $HAVE_SYSTEMD && command -v udevadm &>/dev/null; then
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    ok "udev rules installed and reloaded"
else
    warn "udev not active — rules placed but not reloaded (will take effect on next boot)"
fi

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

if $HAVE_SYSTEMD; then
    sudo systemctl enable spacenavd.service
    sudo systemctl restart spacenavd.service
    sleep 1

    if systemctl is-active --quiet spacenavd.service; then
        ok "spacenavd is running"
    else
        warn "spacenavd failed to start (device may not be connected)"
    fi
else
    warn "systemd not running as PID 1 — skipping spacenavd service enable"
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

# GUI package — the launcher imports `spacemouse_config` from here at runtime.
# blender_spacemouse_sync.py also lives next to the package because
# backends.BlenderConfig.install_startup_script() copies it to Blender's
# startup dir using a path relative to the package.
mkdir -p "$HOME/.local/share/spacemouse"
rm -rf "$HOME/.local/share/spacemouse/spacemouse_config"
# Clean up package directory from older install layouts that placed it next
# to the launcher in ~/.local/bin/.
rm -rf "$HOME/.local/bin/spacemouse_config"
cp -r "$SCRIPT_DIR/gui/spacemouse_config" "$HOME/.local/share/spacemouse/spacemouse_config"
install -m644 "$SCRIPT_DIR/gui/blender_spacemouse_sync.py" \
    "$HOME/.local/share/spacemouse/blender_spacemouse_sync.py"
ok "Binaries and GUI installed to ~/.local/bin/ (package: ~/.local/share/spacemouse/)"

# Ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    # shellcheck disable=SC2088  # tilde shown to user, not expanded
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

# When PySide6 lives in a venv, the GUI service must use that interpreter
if $PYSIDE_PIP_FALLBACK; then
    sed "s|^ExecStart=.*|ExecStart=$HOME/.local/share/spacemouse-venv/bin/python3 %h/.local/bin/spacemouse-config.py|" \
        "$SCRIPT_DIR/systemd/spacemouse-config.service" \
        >"$HOME/.config/systemd/user/spacemouse-config.service"
else
    cp "$SCRIPT_DIR/systemd/spacemouse-config.service" "$HOME/.config/systemd/user/"
fi

if $HAVE_SYSTEMD; then
    systemctl --user daemon-reload
    systemctl --user enable spacemouse-desktop.service
    systemctl --user enable spacemouse-config.service
else
    warn "systemd not running as PID 1 — service files placed but not enabled"
fi

# Start the daemon if systemd is running. /dev/uinput must also be writable;
# if not, drop a udev rule and ask the user to relogin.
if $HAVE_SYSTEMD; then
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
        echo 'KERNEL=="uinput", MODE="0666", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        warn "Uinput rule added. Re-login or reboot may be required for it to take effect."
        warn "Then run: systemctl --user restart spacemouse-desktop.service"
    fi
fi

ok "systemd user service installed"

# ── Verification ─────────────────────────────────────────────────

step "Running diagnostics"

"$HOME/.local/bin/spacemouse-test" --check || true

# ── GNOME extension hints ────────────────────────────────────────
#
# GNOME needs two extensions to reach feature parity with KDE:
#   * AppIndicator — without it, QSystemTrayIcon apps are invisible
#     because GNOME ships no StatusNotifierWatcher.
#   * Window Calls (Wayland only) — exposes the active-window list on
#     D-Bus, which the GUI polls to auto-switch profiles when Blender
#     or FreeCAD gains focus. GNOME-X11 doesn't need it (xprop works).
# Both extensions are optional: the daemon and manual switching keep
# working without them.

if [[ "${XDG_CURRENT_DESKTOP:-}" == *"GNOME"* ]]; then
    warn "GNOME detected — system tray icons are not visible by default."
    case "$DISTRO_FAMILY" in
        fedora) info "Install:  sudo dnf install gnome-shell-extension-appindicator" ;;
        debian) info "Install:  sudo apt install gnome-shell-extension-appindicator3" ;;
        arch) info "Install:  yay -S gnome-shell-extension-appindicator" ;;
        opensuse) info "Install:  sudo zypper install gnome-shell-extension-appindicator" ;;
    esac
    info "Then log out and back in. Manual install: https://extensions.gnome.org/extension/615/appindicator-support/"

    if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
        echo ""
        warn "GNOME-Wayland: auto profile switching for Blender / FreeCAD needs the Window Calls extension."
        info "Install from: https://extensions.gnome.org/extension/4974/window-calls/"
        info "Without it, the daemon stays on its default profile — manual switching via the tray still works."
    fi
fi

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
echo "    ./freecad/scripts/setup.sh             Apply SpaceMouse config"
echo "    ./freecad/scripts/setup.sh --restore   Undo changes"
echo ""
