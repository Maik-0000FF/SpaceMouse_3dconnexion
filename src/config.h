/*
 * config - JSON profile loader and per-profile state.
 *
 * Owns the profile array consumed by the event loop. Exports the enums
 * and structs the rest of the daemon needs to read profile state.
 */
#ifndef SPACEMOUSE_CONFIG_H
#define SPACEMOUSE_CONFIG_H

/* ── Sizing ─────────────────────────────────────────────────────────── */

#define MAX_PROFILES 32
#define MAX_WM_CLASSES 32
#define MAX_BUTTONS 32

/* ── Defaults (also used by event loop for thresholds) ──────────────── */

#define DEFAULT_DEADZONE 15
#define DEFAULT_SCROLL_SPEED 3.0
#define DEFAULT_SCROLL_EXP 2.0
#define DEFAULT_ZOOM_SPEED 2.0
#define DEFAULT_DSWITCH_THRESH 200
#define DEFAULT_DSWITCH_COOL_MS 500
#define DEFAULT_SENSITIVITY 1.0

/* Discrete-action thresholds (axis-action gating). Live with the
 * profile defaults because they're tied to deadzone semantics. */
#define VOLUME_COOLDOWN_MS 80
#define VOLUME_THRESHOLD 60
#define KEY_PAIR_THRESHOLD 60

/* ── Action enums ───────────────────────────────────────────────────── */

enum axis_action {
	ACT_NONE = 0,
	ACT_SCROLL_H,
	ACT_SCROLL_V,
	ACT_ZOOM,
	ACT_DESKTOP_SWITCH,
	ACT_VOLUME,
	ACT_KEY_PAIR
};

enum btn_action {
	BTNACT_NONE = 0,
	BTNACT_OVERVIEW,
	BTNACT_SHOW_DESKTOP,
	BTNACT_VOLUME_UP,
	BTNACT_VOLUME_DOWN,
	BTNACT_MUTE,
	BTNACT_PLAY_PAUSE,
	BTNACT_NEXT_TRACK,
	BTNACT_PREV_TRACK,
	BTNACT_KEY
};

/* ── Per-profile config ─────────────────────────────────────────────── */

struct config {
	int deadzone;
	int axis_deadzone[6]; /* per-axis override, 0 = use global */
	double scroll_speed;
	double scroll_exponent;
	double zoom_speed;
	int dswitch_threshold;
	int dswitch_cooldown_ms;
	enum axis_action axis_map[6];
	int axis_invert[6];  /* per-axis direction flip, applied to scroll_h/scroll_v/zoom */
	int axis_key_neg[6]; /* keycode for negative direction (ACT_KEY_PAIR only) */
	int axis_key_pos[6]; /* keycode for positive direction (ACT_KEY_PAIR only) */
	enum btn_action btn_map[MAX_BUTTONS];
	int btn_key[MAX_BUTTONS]; /* keycode (BTNACT_KEY only) */
	double sensitivity;
};

struct profile {
	char name[64];
	char *wm_classes[MAX_WM_CLASSES];
	int wm_class_count;
	struct config cfg;
	int passthrough; /* 1 if all axes+buttons are none → skip event processing */
};

/* ── Profile table (owned by config.c, shared with the event loop) ──── */

extern struct profile g_profiles[MAX_PROFILES];
extern int g_profile_count;
extern int g_active_profile;

/* Load profiles from JSON at `path`. On parse failure / missing file
 * installs a single default profile. Returns 0 on success. The
 * function always succeeds in installing at least one profile. */
int config_load_all(const char *path);

/* Free wm_classes for every loaded profile and reset the count. */
void profiles_free_all(void);

#endif /* SPACEMOUSE_CONFIG_H */
