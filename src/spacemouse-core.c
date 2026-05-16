/*
 * spacemouse-core - Pure-logic helpers, linkable into unit tests.
 *
 * See spacemouse-core.h for the rationale and API.
 */
#define _GNU_SOURCE
#include "spacemouse-core.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <linux/input.h>

/* ── Key name table ─────────────────────────────────────────────────── */

const struct key_name_entry KEY_NAMES[] = {
	{"SPACE",     KEY_SPACE},
	{"ENTER",     KEY_ENTER},
	{"ESC",       KEY_ESC},
	{"TAB",       KEY_TAB},
	{"BACKSPACE", KEY_BACKSPACE},
	{"LEFT",      KEY_LEFT},
	{"RIGHT",     KEY_RIGHT},
	{"UP",        KEY_UP},
	{"DOWN",      KEY_DOWN},
	{"PAGEUP",    KEY_PAGEUP},
	{"PAGEDOWN",  KEY_PAGEDOWN},
	{"HOME",      KEY_HOME},
	{"END",       KEY_END},
	{"A", KEY_A}, {"B", KEY_B}, {"C", KEY_C}, {"D", KEY_D},
	{"E", KEY_E}, {"F", KEY_F}, {"G", KEY_G}, {"H", KEY_H},
	{"I", KEY_I}, {"J", KEY_J}, {"K", KEY_K}, {"L", KEY_L},
	{"M", KEY_M}, {"N", KEY_N}, {"O", KEY_O}, {"P", KEY_P},
	{"Q", KEY_Q}, {"R", KEY_R}, {"S", KEY_S}, {"T", KEY_T},
	{"U", KEY_U}, {"V", KEY_V}, {"W", KEY_W}, {"X", KEY_X},
	{"Y", KEY_Y}, {"Z", KEY_Z},
	{"F1", KEY_F1}, {"F2", KEY_F2}, {"F3", KEY_F3}, {"F4", KEY_F4},
	{"F5", KEY_F5}, {"F6", KEY_F6}, {"F7", KEY_F7}, {"F8", KEY_F8},
	{"F9", KEY_F9}, {"F10", KEY_F10}, {"F11", KEY_F11}, {"F12", KEY_F12},
	{NULL, 0}
};

int lookup_key(const char *name)
{
	if (!name) return 0;
	for (const struct key_name_entry *e = KEY_NAMES; e->name; e++)
		if (strcasecmp(name, e->name) == 0)
			return e->code;
	return 0;
}

/* ── Desktop environment detection ──────────────────────────────────── */

int env_contains(const char *env, const char *needle)
{
	const char *v = getenv(env);
	if (!v || !needle) return 0;
	size_t nl = strlen(needle);
	for (const char *p = v; *p; p++) {
		if (strncasecmp(p, needle, nl) == 0) return 1;
	}
	return 0;
}

enum desktop_env detect_desktop_env(void)
{
	/* Compositor-specific env vars are the most reliable signal — set
	 * directly by sway and hyprland, independent of XDG_CURRENT_DESKTOP. */
	if (getenv("HYPRLAND_INSTANCE_SIGNATURE")) return DE_HYPRLAND;
	if (getenv("SWAYSOCK")) return DE_SWAY;

	if (env_contains("XDG_CURRENT_DESKTOP", "KDE")) return DE_KDE;
	if (env_contains("XDG_CURRENT_DESKTOP", "GNOME")) return DE_GNOME;
	if (env_contains("XDG_CURRENT_DESKTOP", "XFCE") ||
	    env_contains("XDG_CURRENT_DESKTOP", "X-Cinnamon") ||
	    env_contains("XDG_CURRENT_DESKTOP", "Cinnamon") ||
	    env_contains("XDG_CURRENT_DESKTOP", "MATE") ||
	    env_contains("XDG_CURRENT_DESKTOP", "LXQt") ||
	    env_contains("XDG_CURRENT_DESKTOP", "LXDE") ||
	    env_contains("XDG_CURRENT_DESKTOP", "Pantheon") ||
	    env_contains("XDG_CURRENT_DESKTOP", "Budgie"))
		return DE_XFCE_X11;

	return DE_UNKNOWN;
}

const char *de_name(enum desktop_env de)
{
	switch (de) {
	case DE_KDE:      return "KDE";
	case DE_GNOME:    return "GNOME";
	case DE_XFCE_X11: return "XFCE-family / X11-keys";
	case DE_SWAY:     return "Sway";
	case DE_HYPRLAND: return "Hyprland";
	default:          return "unknown (defaulting to X11-keys)";
	}
}

/* ── Curve + scroll accumulator ─────────────────────────────────────── */

double apply_curve(int raw, int deadzone, double exponent, double scale)
{
	double v = (double)raw;
	if (fabs(v) < deadzone)
		return 0.0;
	double sign = v > 0 ? 1.0 : -1.0;
	double norm = (fabs(v) - deadzone) / (350.0 - deadzone);
	if (norm > 1.0) norm = 1.0;
	if (norm < 0.0) norm = 0.0;
	return sign * pow(norm, exponent) * scale;
}

void scroll_acc_reset(struct scroll_acc *sa)
{
	sa->acc_x = sa->acc_y = sa->acc_z = 0;
}

int scroll_acc_consume(double *acc)
{
	int val = (int)*acc;
	*acc -= val;
	return val;
}
