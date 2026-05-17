/*
 * spacemouse-core - Pure-logic helpers extracted from spacemouse-desktop.
 *
 * These functions touch no kernel/D-Bus/socket state and can be linked
 * into unit tests without the daemon's I/O dependencies. Anything that
 * opens fds, talks to D-Bus, or relies on the running event loop stays
 * in spacemouse-desktop.c.
 */
#ifndef SPACEMOUSE_CORE_H
#define SPACEMOUSE_CORE_H

/* ── Key name lookup ────────────────────────────────────────────────── */

struct key_name_entry {
	const char *name;
	int code;
};

/* Sentinel-terminated table mapping config-file key names to kernel
 * keycodes. Used by lookup_key() and by uinput_open() (which iterates it
 * to register every key the daemon might emit). */
extern const struct key_name_entry KEY_NAMES[];

/* Case-insensitive lookup. Returns 0 for unknown names and for NULL. */
int lookup_key(const char *name);

/* ── Desktop environment detection ──────────────────────────────────── */

enum desktop_env {
	DE_UNKNOWN = 0,
	DE_KDE,
	DE_GNOME,
	DE_XFCE_X11, /* XFCE, Cinnamon, MATE, LXQt, Pantheon, Budgie, generic X11 */
	DE_SWAY,
	DE_HYPRLAND,
};

/* Case-insensitive substring search inside the named env var. Returns
 * 0 if the variable is unset or the needle is not present. */
int env_contains(const char *env, const char *needle);

/* Probe XDG_CURRENT_DESKTOP plus the compositor-specific signals
 * (SWAYSOCK, HYPRLAND_INSTANCE_SIGNATURE). Returns DE_UNKNOWN if no
 * signal matches. */
enum desktop_env detect_desktop_env(void);

/* Human-readable label for log output. */
const char *de_name(enum desktop_env de);

/* ── Curve + scroll accumulator ─────────────────────────────────────── */

/* Apply deadzone, normalize to [0,1] against full deflection (350),
 * raise to `exponent`, scale. raw values inside the deadzone return 0. */
double apply_curve(int raw, int deadzone, double exponent, double scale);

struct scroll_acc {
	double acc_x, acc_y, acc_z;
};

void scroll_acc_reset(struct scroll_acc *sa);

/* Drain the integer part out of an accumulator and return it. The
 * fractional remainder stays in the accumulator for the next call. */
int scroll_acc_consume(double *acc);

#endif /* SPACEMOUSE_CORE_H */
