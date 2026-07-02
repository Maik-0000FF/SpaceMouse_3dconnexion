/*
 * desktop_actions - implementation. See desktop_actions.h.
 */
#define _GNU_SOURCE
#include "desktop_actions.h"

#include <stddef.h>

#include <linux/input.h>

#include "dbus_actions.h"
#include "uinput.h"

enum desktop_env g_de = DE_UNKNOWN;

static int g_uinput_fd = -1;

void desktop_actions_set_uinput(int fd)
{
	g_uinput_fd = fd;
}

void desktop_action_workspace(int direction)
{
	switch (g_de) {
	case DE_KDE:
		dbus_actions_ensure_connected();
		dbus_kwin_call(direction > 0 ? "nextDesktop" : "previousDesktop");
		break;
	case DE_SWAY: {
		char *argv[] = {"swaymsg", "workspace", direction > 0 ? "next" : "prev", NULL};
		spawn_command(argv);
		break;
	}
	case DE_HYPRLAND: {
		/* "e+1"/"e-1" cycles through existing workspaces; plain "+1"/"-1"
		 * walks raw numeric ids and skips gaps, breaking switching on
		 * setups with named or non-contiguous workspaces. */
		char *argv[] = {"hyprctl", "dispatch", "workspace", direction > 0 ? "e+1" : "e-1",
				NULL};
		spawn_command(argv);
		break;
	}
	case DE_GNOME: {
		/* GNOME: Super+Page_Down/Up. Note: under default GNOME 40+ the
		 * workspace layout is horizontal, but the keyboard shortcuts
		 * keep the historical Page_Down/Up names. */
		int mods[] = {KEY_LEFTMETA};
		emit_key_combo(g_uinput_fd, mods, 1, direction > 0 ? KEY_PAGEDOWN : KEY_PAGEUP);
		break;
	}
	case DE_XFCE_X11:
	case DE_UNKNOWN:
	default: {
		/* XFCE / Cinnamon / MATE / LXQt and unknown desktops:
		 * Ctrl+Alt+Right/Left is the long-standing X11 default. */
		int mods[] = {KEY_LEFTCTRL, KEY_LEFTALT};
		emit_key_combo(g_uinput_fd, mods, 2, direction > 0 ? KEY_RIGHT : KEY_LEFT);
		break;
	}
	}
}

void desktop_action_overview(void)
{
	switch (g_de) {
	case DE_KDE:
		dbus_actions_ensure_connected();
		dbus_kglobalaccel_call("ExposeAll");
		break;
	default:
		/* On GNOME a Super tap opens Activities — closest overview
		 * equivalent. XFCE/Cinnamon/MATE/Sway/Hyprland have no
		 * canonical overview command; Super alone is the most common
		 * user binding. */
		emit_key_tap(g_uinput_fd, KEY_LEFTMETA);
		break;
	}
}

void desktop_action_show_desktop(int *state)
{
	switch (g_de) {
	case DE_KDE:
		dbus_actions_ensure_connected();
		if (!dbus_actions_is_connected())
			break;
		*state = !*state;
		dbus_kwin_show_desktop(*state);
		break;
	default: {
		/* Super+D is wired up by default on GNOME, XFCE, Cinnamon,
		 * MATE. The DE itself owns the toggle state, so we don't
		 * track *state here. */
		(void)state;
		int mods[] = {KEY_LEFTMETA};
		emit_key_combo(g_uinput_fd, mods, 1, KEY_D);
		break;
	}
	}
}
