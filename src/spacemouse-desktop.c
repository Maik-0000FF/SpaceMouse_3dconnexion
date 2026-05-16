/*
 * spacemouse-desktop - High-performance SpaceMouse desktop navigation daemon
 *
 * Features:
 *   - Per-application profiles with full parameter customization
 *   - UNIX command socket for profile switching (used by GUI)
 *   - poll()-based event loop for responsive profile switching
 *   - uinput scroll/zoom emulation
 *   - D-Bus integration for KDE KWin desktop actions
 *   - SIGHUP config reload
 *
 * Build: make spacemouse-desktop
 * Run:   ./spacemouse-desktop [-f] [-c config.json]
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <math.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <poll.h>
#include <linux/uinput.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <dirent.h>
#include <linux/input.h>
#include <dbus/dbus.h>
#include <json-c/json.h>

/* ── Constants ──────────────────────────────────────────────────────── */

#define SPACEMOUSE_VERSION  "0.1.0"

#define MAX_PROFILES    32
#define MAX_WM_CLASSES  8
#define CMD_BUF_SIZE    256
#define SOCK_BACKLOG    4

#define DEFAULT_DEADZONE        15
#define DEFAULT_SCROLL_SPEED    3.0
#define DEFAULT_SCROLL_EXP      2.0
#define DEFAULT_ZOOM_SPEED      2.0
#define DEFAULT_DSWITCH_THRESH  200
#define DEFAULT_DSWITCH_COOL_MS 500
#define DEFAULT_SENSITIVITY     1.0

/* ── Types ──────────────────────────────────────────────────────────── */

enum axis_action {
	ACT_NONE = 0,
	ACT_SCROLL_H,
	ACT_SCROLL_V,
	ACT_ZOOM,
	ACT_DESKTOP_SWITCH,
	ACT_VOLUME,
	ACT_KEY_PAIR,
	ACT_SEEK_AUTO
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
	BTNACT_KEY,
	BTNACT_PLAY_PAUSE_AUTO
};

#define VOLUME_COOLDOWN_MS  80
#define VOLUME_THRESHOLD    60
#define KEY_PAIR_THRESHOLD  60

/* Mapping from human-readable key name (used in config.json) to kernel keycode.
 * Sentinel-terminated. Used for "key:NAME" button actions and
 * "key_pair:NEG,POS" axis actions. */
struct key_name_entry {
	const char *name;
	int code;
};

static const struct key_name_entry KEY_NAMES[] = {
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

static int lookup_key(const char *name)
{
	if (!name) return 0;
	for (const struct key_name_entry *e = KEY_NAMES; e->name; e++)
		if (strcasecmp(name, e->name) == 0)
			return e->code;
	return 0;
}

struct config {
	int deadzone;
	int axis_deadzone[6]; /* per-axis deadzone, 0 = use global */
	double scroll_speed;
	double scroll_exponent;
	double zoom_speed;
	int dswitch_threshold;
	int dswitch_cooldown_ms;
	enum axis_action axis_map[6];
	int axis_key_neg[6];   /* keycode for negative direction (ACT_KEY_PAIR only) */
	int axis_key_pos[6];   /* keycode for positive direction (ACT_KEY_PAIR only) */
	enum btn_action btn_map[16];
	int btn_key[16];        /* keycode (BTNACT_KEY only) */
	int invert_scroll_x;
	int invert_scroll_y;
	double sensitivity;
};

struct profile {
	char name[64];
	char *wm_classes[MAX_WM_CLASSES];
	int wm_class_count;
	struct config cfg;
	int passthrough; /* 1 if all axes+buttons are none → skip event processing */
	int browser_keys; /* 1 if smart actions should send Space/Arrow keys */
};

struct scroll_acc {
	double acc_x, acc_y, acc_z;
};

/* ── Globals ────────────────────────────────────────────────────────── */

static volatile sig_atomic_t g_running = 1;
static volatile sig_atomic_t g_reload = 0;

static int g_uinput_fd = -1;
static int g_kinput_fd = -1;
static DBusConnection *g_dbus = NULL;
static char g_config_path[512];
static char g_sock_path[256];

static struct profile g_profiles[MAX_PROFILES];
static int g_profile_count = 0;
static int g_active_profile = 0;

/* Desktop environment, picked at startup. Drives which backend
 * desktop_action_*() uses: KDE keeps the D-Bus path, Sway/Hyprland use
 * their IPC CLIs, everything else taps keyboard shortcuts via uinput. */
enum desktop_env {
	DE_UNKNOWN = 0,
	DE_KDE,
	DE_GNOME,
	DE_XFCE_X11,    /* XFCE, Cinnamon, MATE, LXQt, generic X11 */
	DE_SWAY,
	DE_HYPRLAND,
};

static enum desktop_env g_de = DE_UNKNOWN;

/* ── Signal handlers ────────────────────────────────────────────────── */

static void on_sigterm(int sig) { (void)sig; g_running = 0; }
static void on_sighup(int sig)  { (void)sig; g_reload = 1; }

/* ── Time helpers ───────────────────────────────────────────────────── */

static long long time_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* ── Nonlinear curve ────────────────────────────────────────────────── */

static double apply_curve(int raw, int deadzone, double exponent, double scale)
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

/* ── uinput ─────────────────────────────────────────────────────────── */

static int uinput_open(void)
{
	int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
	if (fd < 0) {
		perror("spacemouse-desktop: open /dev/uinput");
		return -1;
	}

	ioctl(fd, UI_SET_EVBIT, EV_REL);
	ioctl(fd, UI_SET_RELBIT, REL_WHEEL);
	ioctl(fd, UI_SET_RELBIT, REL_HWHEEL);
	ioctl(fd, UI_SET_RELBIT, REL_WHEEL_HI_RES);
	ioctl(fd, UI_SET_RELBIT, REL_HWHEEL_HI_RES);
	ioctl(fd, UI_SET_EVBIT, EV_KEY);
	ioctl(fd, UI_SET_KEYBIT, BTN_LEFT);
	ioctl(fd, UI_SET_KEYBIT, KEY_LEFTCTRL);
	ioctl(fd, UI_SET_KEYBIT, KEY_LEFTALT);
	ioctl(fd, UI_SET_KEYBIT, KEY_LEFTMETA);
	ioctl(fd, UI_SET_KEYBIT, KEY_VOLUMEUP);
	ioctl(fd, UI_SET_KEYBIT, KEY_VOLUMEDOWN);
	ioctl(fd, UI_SET_KEYBIT, KEY_MUTE);
	ioctl(fd, UI_SET_KEYBIT, KEY_PLAYPAUSE);
	ioctl(fd, UI_SET_KEYBIT, KEY_NEXTSONG);
	ioctl(fd, UI_SET_KEYBIT, KEY_PREVIOUSSONG);
	ioctl(fd, UI_SET_KEYBIT, KEY_FASTFORWARD);
	ioctl(fd, UI_SET_KEYBIT, KEY_REWIND);
	for (const struct key_name_entry *e = KEY_NAMES; e->name; e++)
		ioctl(fd, UI_SET_KEYBIT, e->code);

	struct uinput_setup usetup;
	memset(&usetup, 0, sizeof(usetup));
	usetup.id.bustype = BUS_VIRTUAL;
	usetup.id.vendor = 0x1209;   /* pid.codes assigned for testing */
	usetup.id.product = 0x000a;
	/* Avoid the literal string "SpaceMouse" so spacenavd's autodetect
	 * does not bind to this virtual scroll-wheel device. */
	snprintf(usetup.name, UINPUT_MAX_NAME_SIZE, "Desktop Scroll Emulator");

	if (ioctl(fd, UI_DEV_SETUP, &usetup) < 0) {
		perror("spacemouse-desktop: UI_DEV_SETUP");
		close(fd);
		return -1;
	}
	if (ioctl(fd, UI_DEV_CREATE) < 0) {
		perror("spacemouse-desktop: UI_DEV_CREATE");
		close(fd);
		return -1;
	}
	usleep(100000);
	return fd;
}

static void uinput_close(int fd)
{
	if (fd >= 0) {
		ioctl(fd, UI_DEV_DESTROY);
		close(fd);
	}
}

static void emit_event(int fd, int type, int code, int val)
{
	struct input_event ie;
	memset(&ie, 0, sizeof(ie));
	ie.type = type;
	ie.code = code;
	ie.value = val;
	write(fd, &ie, sizeof(ie));
}

static void emit_scroll(int fd, int dx, int dy)
{
	if (dy != 0) {
		emit_event(fd, EV_REL, REL_WHEEL, dy);
		emit_event(fd, EV_REL, REL_WHEEL_HI_RES, dy * 120);
	}
	if (dx != 0) {
		emit_event(fd, EV_REL, REL_HWHEEL, dx);
		emit_event(fd, EV_REL, REL_HWHEEL_HI_RES, dx * 120);
	}
	if (dx != 0 || dy != 0)
		emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void emit_key_tap(int fd, int code)
{
	if (fd < 0) return;
	emit_event(fd, EV_KEY, code, 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_KEY, code, 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

/* Press modifiers (e.g. Super, Ctrl), tap key, release modifiers. Used
 * for desktop actions on non-KDE DEs where we drive global shortcuts
 * instead of D-Bus. n_mods may be 0 — then this degenerates to emit_key_tap. */
static void emit_key_combo(int fd, const int *mods, int n_mods, int key)
{
	if (fd < 0) return;
	for (int i = 0; i < n_mods; i++)
		emit_event(fd, EV_KEY, mods[i], 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_KEY, key, 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_KEY, key, 0);
	for (int i = n_mods - 1; i >= 0; i--)
		emit_event(fd, EV_KEY, mods[i], 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

/* Fire-and-forget a subprocess. Used to dispatch swaymsg / hyprctl
 * without blocking the event loop. We do not wait — the caller does not
 * care about the exit status, and reaping is handled via SIGCHLD set to
 * SIG_IGN at startup. */
static void spawn_command(char *const argv[])
{
	pid_t pid = fork();
	if (pid < 0) {
		perror("spacemouse-desktop: fork");
		return;
	}
	if (pid == 0) {
		/* child */
		int devnull = open("/dev/null", O_RDWR);
		if (devnull >= 0) {
			dup2(devnull, STDIN_FILENO);
			dup2(devnull, STDOUT_FILENO);
			dup2(devnull, STDERR_FILENO);
			if (devnull > STDERR_FILENO) close(devnull);
		}
		execvp(argv[0], argv);
		_exit(127);
	}
}

static void emit_zoom(int fd, int dz)
{
	if (dz == 0) return;
	emit_event(fd, EV_KEY, KEY_LEFTCTRL, 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_REL, REL_WHEEL, dz);
	emit_event(fd, EV_REL, REL_WHEEL_HI_RES, dz * 120);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_KEY, KEY_LEFTCTRL, 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

/* ── Desktop environment detection ──────────────────────────────────── */

static int env_contains(const char *env, const char *needle)
{
	const char *v = getenv(env);
	if (!v || !needle) return 0;
	/* Case-insensitive substring search. XDG_CURRENT_DESKTOP is a
	 * colon-separated list ("KDE", "GNOME", "ubuntu:GNOME", ...) and
	 * casing varies between distros. */
	size_t nl = strlen(needle);
	for (const char *p = v; *p; p++) {
		if (strncasecmp(p, needle, nl) == 0) return 1;
	}
	return 0;
}

static enum desktop_env detect_desktop_env(void)
{
	/* Compositor-specific env vars are the most reliable signal — set
	 * directly by sway and hyprland, independent of XDG_CURRENT_DESKTOP. */
	if (getenv("HYPRLAND_INSTANCE_SIGNATURE")) return DE_HYPRLAND;
	if (getenv("SWAYSOCK")) return DE_SWAY;

	/* XDG_CURRENT_DESKTOP is reliable for the major desktops. */
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

static const char *de_name(enum desktop_env de)
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

/* ── D-Bus helpers ──────────────────────────────────────────────────── */

static DBusConnection *dbus_connect(void)
{
	DBusError err;
	dbus_error_init(&err);
	DBusConnection *conn = dbus_bus_get(DBUS_BUS_SESSION, &err);
	if (dbus_error_is_set(&err)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus error: %s\n", err.message);
		dbus_error_free(&err);
		return NULL;
	}
	dbus_connection_set_exit_on_disconnect(conn, FALSE);
	return conn;
}

static void dbus_ensure_connected(void)
{
	if (g_dbus && dbus_connection_get_is_connected(g_dbus))
		return;
	if (g_dbus) {
		dbus_connection_unref(g_dbus);
		g_dbus = NULL;
	}
	g_dbus = dbus_connect();
	if (g_dbus)
		fprintf(stderr, "spacemouse-desktop: D-Bus reconnected\n");
	else
		fprintf(stderr, "spacemouse-desktop: D-Bus reconnect failed\n");
}

static void dbus_call_kwin(DBusConnection *conn, const char *method)
{
	if (!conn || !dbus_connection_get_is_connected(conn)) return;
	DBusMessage *msg = dbus_message_new_method_call(
		"org.kde.KWin", "/KWin", "org.kde.KWin", method);
	if (!msg) return;
	dbus_message_set_no_reply(msg, TRUE);
	if (!dbus_connection_send(conn, msg, NULL)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus send failed: %s\n", method);
		dbus_message_unref(msg);
		return;
	}
	dbus_connection_flush(conn);
	dbus_message_unref(msg);
}

static void dbus_call_kglobalaccel(DBusConnection *conn, const char *shortcut)
{
	if (!conn || !dbus_connection_get_is_connected(conn)) return;
	DBusMessage *msg = dbus_message_new_method_call(
		"org.kde.kglobalaccel", "/component/kwin",
		"org.kde.kglobalaccel.Component", "invokeShortcut");
	if (!msg) return;
	dbus_message_append_args(msg, DBUS_TYPE_STRING, &shortcut, DBUS_TYPE_INVALID);
	dbus_message_set_no_reply(msg, TRUE);
	if (!dbus_connection_send(conn, msg, NULL)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus send failed: %s\n", shortcut);
		dbus_message_unref(msg);
		return;
	}
	dbus_connection_flush(conn);
	dbus_message_unref(msg);
}

/* ── Desktop actions (DE-dispatch) ──────────────────────────────────── */
/*
 * Workspace switch / overview / show-desktop dispatch based on g_de.
 * KDE keeps the native D-Bus path (exact, no shortcut races, real
 * show-desktop toggle). Sway/Hyprland use their IPC CLIs. Everything
 * else taps keyboard shortcuts via uinput with DE-typical defaults.
 *
 * Defaults reflect each DE's out-of-the-box keymap. Users with custom
 * shortcuts can rebind their compositor instead — exposing per-profile
 * overrides in config is a follow-up phase.
 */

static void desktop_action_workspace(int direction)
{
	switch (g_de) {
	case DE_KDE:
		dbus_ensure_connected();
		if (g_dbus)
			dbus_call_kwin(g_dbus,
				direction > 0 ? "nextDesktop" : "previousDesktop");
		break;
	case DE_SWAY: {
		char *argv[] = { "swaymsg", "workspace",
			direction > 0 ? "next" : "prev", NULL };
		spawn_command(argv);
		break;
	}
	case DE_HYPRLAND: {
		char *argv[] = { "hyprctl", "dispatch", "workspace",
			direction > 0 ? "+1" : "-1", NULL };
		spawn_command(argv);
		break;
	}
	case DE_GNOME: {
		/* GNOME: Super+Page_Down/Up. Note: under default GNOME 40+ the
		 * workspace layout is horizontal, but the keyboard shortcuts
		 * keep the historical Page_Down/Up names. */
		int mods[] = { KEY_LEFTMETA };
		emit_key_combo(g_uinput_fd, mods, 1,
			direction > 0 ? KEY_PAGEDOWN : KEY_PAGEUP);
		break;
	}
	case DE_XFCE_X11:
	case DE_UNKNOWN:
	default: {
		/* XFCE / Cinnamon / MATE / LXQt and unknown desktops:
		 * Ctrl+Alt+Right/Left is the long-standing X11 default. */
		int mods[] = { KEY_LEFTCTRL, KEY_LEFTALT };
		emit_key_combo(g_uinput_fd, mods, 2,
			direction > 0 ? KEY_RIGHT : KEY_LEFT);
		break;
	}
	}
}

static void desktop_action_overview(void)
{
	switch (g_de) {
	case DE_KDE:
		dbus_ensure_connected();
		if (g_dbus)
			dbus_call_kglobalaccel(g_dbus, "ExposeAll");
		break;
	case DE_GNOME:
		/* Tapping Super opens Activities — closest GNOME equivalent. */
		emit_key_tap(g_uinput_fd, KEY_LEFTMETA);
		break;
	default:
		/* XFCE/Cinnamon/MATE/Sway/Hyprland have no canonical overview;
		 * Super alone is the most common user binding. */
		emit_key_tap(g_uinput_fd, KEY_LEFTMETA);
		break;
	}
}

static void desktop_action_show_desktop(int *state)
{
	switch (g_de) {
	case DE_KDE: {
		dbus_ensure_connected();
		if (!g_dbus) break;
		*state = !*state;
		DBusMessage *msg = dbus_message_new_method_call(
			"org.kde.KWin", "/KWin",
			"org.kde.KWin", "showDesktop");
		if (msg) {
			dbus_bool_t v = *state;
			dbus_message_append_args(msg,
				DBUS_TYPE_BOOLEAN, &v,
				DBUS_TYPE_INVALID);
			if (!dbus_connection_send(g_dbus, msg, NULL))
				fprintf(stderr, "spacemouse-desktop: D-Bus send failed: showDesktop\n");
			else
				dbus_connection_flush(g_dbus);
			dbus_message_unref(msg);
		}
		break;
	}
	default: {
		/* Super+D is wired up by default on GNOME, XFCE, Cinnamon,
		 * MATE. The DE itself owns the toggle state, so we don't
		 * track *state here. */
		(void)state;
		int mods[] = { KEY_LEFTMETA };
		emit_key_combo(g_uinput_fd, mods, 1, KEY_D);
		break;
	}
	}
}

/* ── Kernel input device (replaces libspnav for our daemon) ─────────── */

enum kinput_event_type { KIE_MOTION = 1, KIE_BUTTON = 2 };

struct kinput_motion {
	int x, y, z;
	int rx, ry, rz;
};

struct kinput_button {
	int bnum;
	int press;
};

struct kinput_event {
	int type;
	struct kinput_motion motion;
	struct kinput_button button;
};

static int g_kinput_state[6] = {0};
static int g_kinput_dirty = 0;

/* Locate a 3Dconnexion event-joystick node under /dev/input/by-id and open it.
 * Returns fd or -1. */
static int kinput_open(void)
{
	DIR *d = opendir("/dev/input/by-id");
	if (!d) {
		perror("spacemouse-desktop: opendir /dev/input/by-id");
		return -1;
	}

	char path[512] = {0};
	struct dirent *ent;
	while ((ent = readdir(d))) {
		if (strstr(ent->d_name, "3Dconnexion") &&
		    strstr(ent->d_name, "-event-")) {
			snprintf(path, sizeof(path), "/dev/input/by-id/%s", ent->d_name);
			break;
		}
	}
	closedir(d);

	if (!path[0]) {
		fprintf(stderr, "spacemouse-desktop: no 3Dconnexion event device under /dev/input/by-id\n");
		return -1;
	}

	int fd = open(path, O_RDONLY | O_NONBLOCK);
	if (fd < 0) {
		fprintf(stderr, "spacemouse-desktop: open %s: %s\n", path, strerror(errno));
		return -1;
	}

	fprintf(stderr, "spacemouse-desktop: kernel input opened: %s\n", path);
	return fd;
}

/* Read events from kernel device. Returns 1 if `out` was filled, 0 otherwise.
 * ABS events accumulate into a state[6] vector, emitted as a single KIE_MOTION
 * at SYN_REPORT. KEY events are emitted immediately as KIE_BUTTON. */
static int kinput_poll_event(int fd, struct kinput_event *out)
{
	struct input_event ie;
	while (read(fd, &ie, sizeof(ie)) == (ssize_t)sizeof(ie)) {
		if (ie.type == EV_ABS && ie.code <= 5) {
			g_kinput_state[ie.code] = ie.value;
			g_kinput_dirty = 1;
		} else if (ie.type == EV_KEY && ie.code >= BTN_0 && ie.code <= BTN_9) {
			out->type = KIE_BUTTON;
			out->button.bnum = ie.code - BTN_0;
			out->button.press = ie.value;
			return 1;
		} else if (ie.type == EV_SYN && ie.code == SYN_REPORT) {
			if (g_kinput_dirty) {
				out->type = KIE_MOTION;
				out->motion.x  = g_kinput_state[0];
				out->motion.y  = g_kinput_state[1];
				out->motion.z  = g_kinput_state[2];
				out->motion.rx = g_kinput_state[3];
				out->motion.ry = g_kinput_state[4];
				out->motion.rz = g_kinput_state[5];
				g_kinput_dirty = 0;
				return 1;
			}
		}
	}
	return 0;
}

/* ── Command socket ─────────────────────────────────────────────────── */

static int cmd_sock_open(const char *path)
{
	unlink(path);

	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0);
	if (fd < 0) {
		perror("spacemouse-desktop: socket");
		return -1;
	}

	struct sockaddr_un addr;
	memset(&addr, 0, sizeof(addr));
	addr.sun_family = AF_UNIX;
	size_t plen = strlen(path);
	if (plen >= sizeof(addr.sun_path)) {
		fprintf(stderr, "spacemouse-desktop: socket path too long: %s\n", path);
		close(fd);
		return -1;
	}
	memcpy(addr.sun_path, path, plen + 1);

	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		perror("spacemouse-desktop: bind");
		close(fd);
		return -1;
	}
	chmod(path, 0600);

	if (listen(fd, SOCK_BACKLOG) < 0) {
		perror("spacemouse-desktop: listen");
		close(fd);
		return -1;
	}

	return fd;
}

static void cmd_sock_close(int fd, const char *path)
{
	if (fd >= 0) close(fd);
	if (path[0]) unlink(path);
}

/* Handle a single client connection: read command, send response */
static void cmd_handle_client(int listen_fd)
{
	int cfd = accept(listen_fd, NULL, NULL);
	if (cfd < 0) return;

	char buf[CMD_BUF_SIZE] = {0};
	ssize_t n = read(cfd, buf, sizeof(buf) - 1);
	if (n <= 0) { close(cfd); return; }

	/* Strip trailing newline */
	while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r'))
		buf[--n] = '\0';

	char response[CMD_BUF_SIZE] = {0};

	if (strncmp(buf, "PROFILE ", 8) == 0) {
		const char *name = buf + 8;
		int found = -1;
		for (int i = 0; i < g_profile_count; i++) {
			if (strcasecmp(g_profiles[i].name, name) == 0) {
				found = i;
				break;
			}
		}
		if (found >= 0) {
			g_active_profile = found;
			snprintf(response, sizeof(response), "OK %s\n", g_profiles[found].name);
			fprintf(stderr, "spacemouse-desktop: switched to profile '%s'\n",
				g_profiles[found].name);
		} else {
			snprintf(response, sizeof(response), "ERR unknown profile '%.200s'\n", name);
		}
	}
	else if (strcmp(buf, "RELOAD") == 0) {
		g_reload = 1;
		snprintf(response, sizeof(response), "OK reloading\n");
	}
	else if (strcmp(buf, "STATUS") == 0) {
		snprintf(response, sizeof(response), "ACTIVE %s\nPROFILES",
			g_profiles[g_active_profile].name);
		for (int i = 0; i < g_profile_count; i++) {
			int rem = sizeof(response) - strlen(response) - 1;
			if (rem < 2) break;
			strncat(response, " ", rem);
			strncat(response, g_profiles[i].name, rem - 1);
		}
		strncat(response, "\n", sizeof(response) - strlen(response) - 1);
	}
	else {
		snprintf(response, sizeof(response), "ERR unknown command\n");
	}

	write(cfd, response, strlen(response));
	close(cfd);
}

/* ── Configuration ──────────────────────────────────────────────────── */

static enum axis_action parse_axis_action(const char *s)
{
	if (!s) return ACT_NONE;
	if (strcmp(s, "scroll_h") == 0) return ACT_SCROLL_H;
	if (strcmp(s, "scroll_v") == 0) return ACT_SCROLL_V;
	if (strcmp(s, "zoom") == 0) return ACT_ZOOM;
	if (strcmp(s, "desktop_switch") == 0) return ACT_DESKTOP_SWITCH;
	if (strcmp(s, "volume") == 0) return ACT_VOLUME;
	if (strcmp(s, "seek_auto") == 0) return ACT_SEEK_AUTO;
	return ACT_NONE;
}

static enum btn_action parse_btn_action(const char *s)
{
	if (!s) return BTNACT_NONE;
	if (strcmp(s, "overview") == 0) return BTNACT_OVERVIEW;
	if (strcmp(s, "show_desktop") == 0) return BTNACT_SHOW_DESKTOP;
	if (strcmp(s, "volume_up") == 0) return BTNACT_VOLUME_UP;
	if (strcmp(s, "volume_down") == 0) return BTNACT_VOLUME_DOWN;
	if (strcmp(s, "mute") == 0) return BTNACT_MUTE;
	if (strcmp(s, "play_pause") == 0) return BTNACT_PLAY_PAUSE;
	if (strcmp(s, "next_track") == 0) return BTNACT_NEXT_TRACK;
	if (strcmp(s, "prev_track") == 0) return BTNACT_PREV_TRACK;
	if (strcmp(s, "play_pause_auto") == 0) return BTNACT_PLAY_PAUSE_AUTO;
	return BTNACT_NONE;
}

/* Apply a full axis action string to slot idx of config c. Handles both
 * simple action names and the parameterized "key_pair:NEG,POS" format. */
static void apply_axis_action(struct config *c, int idx, const char *s)
{
	c->axis_key_neg[idx] = 0;
	c->axis_key_pos[idx] = 0;
	if (!s) { c->axis_map[idx] = ACT_NONE; return; }
	if (strncmp(s, "key_pair:", 9) == 0) {
		const char *rest = s + 9;
		const char *comma = strchr(rest, ',');
		if (comma) {
			char neg_name[32] = {0};
			size_t neg_len = (size_t)(comma - rest);
			if (neg_len > 0 && neg_len < sizeof(neg_name)) {
				memcpy(neg_name, rest, neg_len);
				int neg = lookup_key(neg_name);
				int pos = lookup_key(comma + 1);
				if (neg && pos) {
					c->axis_map[idx] = ACT_KEY_PAIR;
					c->axis_key_neg[idx] = neg;
					c->axis_key_pos[idx] = pos;
					return;
				}
			}
		}
		c->axis_map[idx] = ACT_NONE;
		return;
	}
	c->axis_map[idx] = parse_axis_action(s);
}

/* Apply a full button action string to slot idx of config c. Handles both
 * simple action names and the parameterized "key:NAME" format. */
static void apply_btn_action(struct config *c, int idx, const char *s)
{
	c->btn_key[idx] = 0;
	if (!s) { c->btn_map[idx] = BTNACT_NONE; return; }
	if (strncmp(s, "key:", 4) == 0) {
		int code = lookup_key(s + 4);
		if (code) {
			c->btn_map[idx] = BTNACT_KEY;
			c->btn_key[idx] = code;
			return;
		}
		c->btn_map[idx] = BTNACT_NONE;
		return;
	}
	c->btn_map[idx] = parse_btn_action(s);
}

static void config_defaults(struct config *cfg)
{
	memset(cfg, 0, sizeof(*cfg));
	cfg->deadzone = DEFAULT_DEADZONE;
	cfg->scroll_speed = DEFAULT_SCROLL_SPEED;
	cfg->scroll_exponent = DEFAULT_SCROLL_EXP;
	cfg->zoom_speed = DEFAULT_ZOOM_SPEED;
	cfg->dswitch_threshold = DEFAULT_DSWITCH_THRESH;
	cfg->dswitch_cooldown_ms = DEFAULT_DSWITCH_COOL_MS;
	cfg->axis_map[0] = ACT_SCROLL_H;
	cfg->axis_map[1] = ACT_SCROLL_V;
	cfg->axis_map[2] = ACT_ZOOM;
	cfg->axis_map[3] = ACT_NONE;
	cfg->axis_map[4] = ACT_DESKTOP_SWITCH;
	cfg->axis_map[5] = ACT_NONE;
	cfg->btn_map[0] = BTNACT_OVERVIEW;
	cfg->btn_map[1] = BTNACT_SHOW_DESKTOP;
	cfg->sensitivity = DEFAULT_SENSITIVITY;
}

static void profile_free(struct profile *p)
{
	for (int i = 0; i < p->wm_class_count; i++)
		free(p->wm_classes[i]);
	p->wm_class_count = 0;
}

static void profiles_free_all(void)
{
	for (int i = 0; i < g_profile_count; i++)
		profile_free(&g_profiles[i]);
	g_profile_count = 0;
}

/* Parse a single profile JSON object into a profile struct.
 * If defaults is non-NULL, inherit from it first. */
static void parse_profile_obj(struct json_object *obj, struct profile *p,
                              const struct config *defaults)
{
	if (defaults)
		memcpy(&p->cfg, defaults, sizeof(p->cfg));
	else
		config_defaults(&p->cfg);

	struct json_object *val;
	struct config *c = &p->cfg;

	if (json_object_object_get_ex(obj, "deadzone", &val))
		c->deadzone = json_object_get_int(val);
	if (json_object_object_get_ex(obj, "scroll_speed", &val))
		c->scroll_speed = json_object_get_double(val);
	if (json_object_object_get_ex(obj, "scroll_exponent", &val))
		c->scroll_exponent = json_object_get_double(val);
	if (json_object_object_get_ex(obj, "zoom_speed", &val))
		c->zoom_speed = json_object_get_double(val);
	if (json_object_object_get_ex(obj, "desktop_switch_threshold", &val))
		c->dswitch_threshold = json_object_get_int(val);
	if (json_object_object_get_ex(obj, "desktop_switch_cooldown_ms", &val))
		c->dswitch_cooldown_ms = json_object_get_int(val);
	if (json_object_object_get_ex(obj, "invert_scroll_x", &val))
		c->invert_scroll_x = json_object_get_boolean(val);
	if (json_object_object_get_ex(obj, "invert_scroll_y", &val))
		c->invert_scroll_y = json_object_get_boolean(val);
	if (json_object_object_get_ex(obj, "sensitivity", &val))
		c->sensitivity = json_object_get_double(val);

	struct json_object *adz;
	if (json_object_object_get_ex(obj, "axis_deadzone", &adz)) {
		struct json_object *dv;
		const char *dz_keys[] = {"tx", "ty", "tz", "rx", "ry", "rz"};
		for (int i = 0; i < 6; i++) {
			if (json_object_object_get_ex(adz, dz_keys[i], &dv))
				c->axis_deadzone[i] = json_object_get_int(dv);
		}
	}

	struct json_object *amap;
	if (json_object_object_get_ex(obj, "axis_mapping", &amap)) {
		struct json_object *ax;
		const char *axis_keys[6] = {"tx", "ty", "tz", "rx", "ry", "rz"};
		for (int i = 0; i < 6; i++) {
			if (json_object_object_get_ex(amap, axis_keys[i], &ax))
				apply_axis_action(c, i, json_object_get_string(ax));
		}
	}

	struct json_object *bmap;
	if (json_object_object_get_ex(obj, "button_mapping", &bmap)) {
		struct json_object_iterator it = json_object_iter_begin(bmap);
		struct json_object_iterator end = json_object_iter_end(bmap);
		while (!json_object_iter_equal(&it, &end)) {
			int bnum = atoi(json_object_iter_peek_name(&it));
			struct json_object *bval = json_object_iter_peek_value(&it);
			if (bnum >= 0 && bnum < 16)
				apply_btn_action(c, bnum, json_object_get_string(bval));
			json_object_iter_next(&it);
		}
	}

	/* Parse WM class match list */
	struct json_object *wmarr;
	if (json_object_object_get_ex(obj, "match_wm_class", &wmarr)) {
		int n = json_object_array_length(wmarr);
		if (n > MAX_WM_CLASSES) n = MAX_WM_CLASSES;
		for (int i = 0; i < n; i++) {
			const char *s = json_object_get_string(
				json_object_array_get_idx(wmarr, i));
			if (s)
				p->wm_classes[p->wm_class_count++] = strdup(s);
		}
	}

	/* Browser-key flag: smart actions emit Space/Arrow keys when this profile is active */
	struct json_object *bkv;
	p->browser_keys = 0;
	if (json_object_object_get_ex(obj, "browser_keys", &bkv))
		p->browser_keys = json_object_get_boolean(bkv);

	/* Detect passthrough profiles (all axes+buttons none) — skip event processing */
	p->passthrough = 1;
	for (int i = 0; i < 6; i++) {
		if (c->axis_map[i] != ACT_NONE) { p->passthrough = 0; break; }
	}
	if (p->passthrough) {
		for (int i = 0; i < 16; i++) {
			if (c->btn_map[i] != BTNACT_NONE) { p->passthrough = 0; break; }
		}
	}
}

static int config_load_all(const char *path)
{
	profiles_free_all();
	g_active_profile = 0;

	struct json_object *root = json_object_from_file(path);
	if (!root) {
		fprintf(stderr, "spacemouse-desktop: config not found at %s, using defaults\n", path);
		snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
		config_defaults(&g_profiles[0].cfg);
		g_profile_count = 1;
		return 0;
	}

	struct json_object *profiles_obj;
	if (json_object_object_get_ex(root, "profiles", &profiles_obj)) {
		/* New multi-profile format */

		/* Parse "default" first (always index 0) */
		struct json_object *def_obj;
		snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
		if (json_object_object_get_ex(profiles_obj, "default", &def_obj))
			parse_profile_obj(def_obj, &g_profiles[0], NULL);
		else
			config_defaults(&g_profiles[0].cfg);
		g_profile_count = 1;

		/* Parse remaining profiles (inherit from default) */
		struct json_object_iterator it = json_object_iter_begin(profiles_obj);
		struct json_object_iterator end = json_object_iter_end(profiles_obj);
		while (!json_object_iter_equal(&it, &end)) {
			const char *pname = json_object_iter_peek_name(&it);
			if (strcmp(pname, "default") != 0 && g_profile_count < MAX_PROFILES) {
				struct profile *p = &g_profiles[g_profile_count];
				memset(p, 0, sizeof(*p));
				snprintf(p->name, sizeof(p->name), "%s", pname);
				parse_profile_obj(json_object_iter_peek_value(&it),
					p, &g_profiles[0].cfg);
				g_profile_count++;
			}
			json_object_iter_next(&it);
		}
	} else {
		/* Legacy flat format: single profile */
		snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
		parse_profile_obj(root, &g_profiles[0], NULL);
		g_profile_count = 1;
	}

	json_object_put(root);
	/* Add built-in _passthrough profile (GUI uses this while settings are open) */
	if (g_profile_count < MAX_PROFILES) {
		struct profile *pt = &g_profiles[g_profile_count];
		memset(pt, 0, sizeof(*pt));
		snprintf(pt->name, sizeof(pt->name), "_passthrough");
		/* All axes and buttons default to 0 (ACT_NONE/BTNACT_NONE) from memset */
		pt->passthrough = 1;
		g_profile_count++;
	}

	fprintf(stderr, "spacemouse-desktop: loaded %d profile(s) from %s\n",
		g_profile_count, path);
	for (int i = 0; i < g_profile_count; i++)
		fprintf(stderr, "  [%d] %s%s (wm_classes: %d)\n",
			i, g_profiles[i].name,
			g_profiles[i].passthrough ? " [passthrough]" : "",
			g_profiles[i].wm_class_count);
	return 0;
}

/* ── Scroll accumulator ─────────────────────────────────────────────── */

static void scroll_acc_reset(struct scroll_acc *sa)
{
	sa->acc_x = sa->acc_y = sa->acc_z = 0;
}

static int scroll_acc_consume(double *acc)
{
	int val = (int)*acc;
	*acc -= val;
	return val;
}

/* ── Main ───────────────────────────────────────────────────────────── */

static void usage(const char *prog)
{
	fprintf(stderr, "Usage: %s [-f] [-c config.json] [--version]\n", prog);
	fprintf(stderr, "  -f         run in foreground\n");
	fprintf(stderr, "  -c FILE    config file (default: ~/.config/spacemouse/config.json)\n");
	fprintf(stderr, "  --version  print version and exit\n");
}

int main(int argc, char **argv)
{
	if (argc == 2 && strcmp(argv[1], "--version") == 0) {
		printf("spacemouse-desktop %s\n", SPACEMOUSE_VERSION);
		return 0;
	}

	int foreground = 0;
	const char *home = getenv("HOME");

	if (home)
		snprintf(g_config_path, sizeof(g_config_path),
			"%s/.config/spacemouse/config.json", home);
	else
		snprintf(g_config_path, sizeof(g_config_path),
			"/etc/spacemouse-desktop.conf");

	int opt;
	while ((opt = getopt(argc, argv, "fc:h")) != -1) {
		switch (opt) {
		case 'f': foreground = 1; break;
		case 'c': snprintf(g_config_path, sizeof(g_config_path), "%s", optarg); break;
		case 'h': default: usage(argv[0]); return opt == 'h' ? 0 : 1;
		}
	}

	fprintf(stderr, "spacemouse-desktop %s starting\n", SPACEMOUSE_VERSION);

	/* Load profiles */
	config_load_all(g_config_path);

	/* Signals */
	struct sigaction sa;
	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_sigterm;
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	sa.sa_handler = on_sighup;
	sigaction(SIGHUP, &sa, NULL);

	/* SIGCHLD = SIG_IGN tells the kernel to auto-reap children, which
	 * keeps spawn_command() (swaymsg / hyprctl) zombie-free without a
	 * dedicated reaper loop. */
	sa.sa_handler = SIG_IGN;
	sigaction(SIGCHLD, &sa, NULL);

	/* Detect desktop environment once at startup. Influences which
	 * backend desktop_action_*() uses. */
	g_de = detect_desktop_env();
	fprintf(stderr, "spacemouse-desktop: desktop environment: %s\n", de_name(g_de));

	/* Open kernel input device directly (bypasses spacenavd). */
	g_kinput_fd = kinput_open();
	if (g_kinput_fd < 0) {
		fprintf(stderr, "spacemouse-desktop: cannot open kernel input device\n");
		return 1;
	}

	/* uinput */
	g_uinput_fd = uinput_open();
	if (g_uinput_fd < 0)
		fprintf(stderr, "spacemouse-desktop: uinput failed, scroll/zoom disabled\n");

	/* D-Bus */
	g_dbus = dbus_connect();
	if (!g_dbus)
		fprintf(stderr, "spacemouse-desktop: D-Bus failed, desktop actions disabled\n");

	/* Command socket */
	uid_t uid = getuid();
	snprintf(g_sock_path, sizeof(g_sock_path),
		"/run/user/%u/spacemouse-cmd.sock", uid);
	int cmd_fd = cmd_sock_open(g_sock_path);
	if (cmd_fd < 0)
		fprintf(stderr, "spacemouse-desktop: command socket failed\n");
	else
		fprintf(stderr, "spacemouse-desktop: command socket at %s\n", g_sock_path);

	/* Daemonize */
	if (!foreground) {
		pid_t pid = fork();
		if (pid < 0) { perror("fork"); goto cleanup; }
		if (pid > 0) _exit(0);
		setsid();
	}

	fprintf(stderr, "spacemouse-desktop: running (PID %d), active profile: %s\n",
		getpid(), g_profiles[g_active_profile].name);

	/* State */
	struct scroll_acc sacc;
	scroll_acc_reset(&sacc);
	long long last_dswitch = 0;
	long long last_volume = 0;
	long long last_keypair[6] = {0};
	int desktop_shown = 0;

	while (g_running) {
		if (g_reload) {
			g_reload = 0;
			int old_active = g_active_profile;
			char old_name[64];
			snprintf(old_name, sizeof(old_name), "%s",
				g_profiles[g_active_profile].name);
			config_load_all(g_config_path);
			/* Try to keep same profile active after reload */
			g_active_profile = 0;
			for (int i = 0; i < g_profile_count; i++) {
				if (strcmp(g_profiles[i].name, old_name) == 0) {
					g_active_profile = i;
					break;
				}
			}
			(void)old_active;
			scroll_acc_reset(&sacc);
		}

		/* Direct kernel read — no disconnect/reconnect dance.
		 * Other clients (Blender/FreeCAD via spacenavd) read independently
		 * from the same kernel device, so we never starve them. */

		struct pollfd fds[2];
		int nfds = 0;

		fds[nfds].fd = g_kinput_fd;
		fds[nfds].events = POLLIN;
		int kinput_idx = nfds;
		nfds++;

		int cmd_idx = -1;
		if (cmd_fd >= 0) {
			cmd_idx = nfds;
			fds[nfds].fd = cmd_fd;
			fds[nfds].events = POLLIN;
			nfds++;
		}

		int ret = poll(fds, nfds, 100); /* 100ms timeout for signal handling */
		if (ret < 0) {
			if (errno == EINTR) continue;
			break;
		}
		if (ret == 0) {
			/* Reconnect D-Bus if needed, drain incoming messages */
			dbus_ensure_connected();
			if (g_dbus && dbus_connection_get_is_connected(g_dbus))
				while (dbus_connection_dispatch(g_dbus) == DBUS_DISPATCH_DATA_REMAINS)
					;
			continue;
		}

		/* Handle command socket */
		if (cmd_idx >= 0 && (fds[cmd_idx].revents & POLLIN)) {
			cmd_handle_client(cmd_fd);
			scroll_acc_reset(&sacc);
		}

		/* Handle kernel input events. In passthrough profiles we still
		 * drain the device (to keep its read buffer empty) but skip
		 * action dispatch — all axis_map entries are ACT_NONE anyway. */
		if (fds[kinput_idx].revents & POLLIN) {
			struct kinput_event ev;

			while (kinput_poll_event(g_kinput_fd, &ev)) {
				struct config *c = &g_profiles[g_active_profile].cfg;

				if (ev.type == KIE_MOTION) {
					int axes[6] = {
						ev.motion.x, ev.motion.y, ev.motion.z,
						ev.motion.rx, ev.motion.ry, ev.motion.rz
					};

					for (int i = 0; i < 6; i++) {
						int dz = c->axis_deadzone[i] > 0 ? c->axis_deadzone[i] : c->deadzone;
						if (abs(axes[i]) < dz) continue;
						double val;
						switch (c->axis_map[i]) {
						case ACT_SCROLL_H:
							val = apply_curve(axes[i], dz,
								c->scroll_exponent, c->scroll_speed)
								* c->sensitivity;
							if (c->invert_scroll_x) val = -val;
							sacc.acc_x += val;
							break;
						case ACT_SCROLL_V:
							val = apply_curve(axes[i], dz,
								c->scroll_exponent, c->scroll_speed)
								* c->sensitivity;
							if (c->invert_scroll_y) val = -val;
							sacc.acc_y -= val;
							break;
						case ACT_ZOOM:
							val = apply_curve(axes[i], dz,
								c->scroll_exponent, c->zoom_speed)
								* c->sensitivity;
							sacc.acc_z += val;
							break;
						case ACT_DESKTOP_SWITCH: {
							long long now = time_ms();
							long long elapsed = now - last_dswitch;
							int val = abs(axes[i]);
							if (val > c->dswitch_threshold &&
							    elapsed > c->dswitch_cooldown_ms) {
								const char *dir = axes[i] > 0 ? "next" : "prev";
								fprintf(stderr, "spacemouse-desktop: dswitch axis=%d val=%d thresh=%d elapsed=%lldms -> %s\n",
									i, axes[i], c->dswitch_threshold, elapsed, dir);
								desktop_action_workspace(axes[i] > 0 ? 1 : -1);
								last_dswitch = now;
							}
							break;
						}
						case ACT_VOLUME: {
							long long now = time_ms();
							long long elapsed = now - last_volume;
							int val = abs(axes[i]);
							if (val > VOLUME_THRESHOLD &&
							    elapsed > VOLUME_COOLDOWN_MS) {
								int up = axes[i] > 0;
								fprintf(stderr, "spacemouse-desktop: volume axis=%d val=%d -> %s\n",
									i, axes[i], up ? "up" : "down");
								emit_key_tap(g_uinput_fd,
									up ? KEY_VOLUMEUP : KEY_VOLUMEDOWN);
								last_volume = now;
							}
							break;
						}
						case ACT_KEY_PAIR: {
							long long now = time_ms();
							long long elapsed = now - last_keypair[i];
							int val = abs(axes[i]);
							if (val > KEY_PAIR_THRESHOLD &&
							    elapsed > c->dswitch_cooldown_ms) {
								int code = axes[i] > 0
									? c->axis_key_pos[i]
									: c->axis_key_neg[i];
								if (code) emit_key_tap(g_uinput_fd, code);
								last_keypair[i] = now;
							}
							break;
						}
						case ACT_SEEK_AUTO: {
							long long now = time_ms();
							long long elapsed = now - last_keypair[i];
							int val = abs(axes[i]);
							if (val > KEY_PAIR_THRESHOLD &&
							    elapsed > c->dswitch_cooldown_ms) {
								int forward = axes[i] > 0;
								int code;
								if (g_profiles[g_active_profile].browser_keys)
									code = forward ? KEY_RIGHT : KEY_LEFT;
								else
									code = forward ? KEY_FASTFORWARD : KEY_REWIND;
								emit_key_tap(g_uinput_fd, code);
								last_keypair[i] = now;
							}
							break;
						}
						case ACT_NONE: default: break;
						}
					}

					if (g_uinput_fd >= 0) {
						int sx = scroll_acc_consume(&sacc.acc_x);
						int sy = scroll_acc_consume(&sacc.acc_y);
						int sz = scroll_acc_consume(&sacc.acc_z);
						emit_scroll(g_uinput_fd, sx, sy);
						if (sz != 0) emit_zoom(g_uinput_fd, sz);
					}
				}
				else if (ev.type == KIE_BUTTON) {
					if (!ev.button.press) continue;
					int bnum = ev.button.bnum;
					if (bnum < 0 || bnum >= 16) continue;

					switch (c->btn_map[bnum]) {
					case BTNACT_OVERVIEW:
						desktop_action_overview();
						break;
					case BTNACT_SHOW_DESKTOP:
						desktop_action_show_desktop(&desktop_shown);
						break;
					case BTNACT_VOLUME_UP:
						emit_key_tap(g_uinput_fd, KEY_VOLUMEUP);
						break;
					case BTNACT_VOLUME_DOWN:
						emit_key_tap(g_uinput_fd, KEY_VOLUMEDOWN);
						break;
					case BTNACT_MUTE:
						emit_key_tap(g_uinput_fd, KEY_MUTE);
						break;
					case BTNACT_PLAY_PAUSE:
						emit_key_tap(g_uinput_fd, KEY_PLAYPAUSE);
						break;
					case BTNACT_NEXT_TRACK:
						emit_key_tap(g_uinput_fd, KEY_NEXTSONG);
						break;
					case BTNACT_PREV_TRACK:
						emit_key_tap(g_uinput_fd, KEY_PREVIOUSSONG);
						break;
					case BTNACT_KEY:
						if (c->btn_key[bnum])
							emit_key_tap(g_uinput_fd, c->btn_key[bnum]);
						break;
					case BTNACT_PLAY_PAUSE_AUTO:
						emit_key_tap(g_uinput_fd,
							g_profiles[g_active_profile].browser_keys
								? KEY_SPACE : KEY_PLAYPAUSE);
						break;
					case BTNACT_NONE: default: break;
					}
				}
			}
		}

		/* Drain D-Bus incoming messages after processing events
		 * (prevents message buildup that kills the connection) */
		if (g_dbus && dbus_connection_get_is_connected(g_dbus))
			while (dbus_connection_dispatch(g_dbus) == DBUS_DISPATCH_DATA_REMAINS)
				;
	}

cleanup:
	fprintf(stderr, "spacemouse-desktop: shutting down\n");
	if (g_kinput_fd >= 0) close(g_kinput_fd);
	uinput_close(g_uinput_fd);
	cmd_sock_close(cmd_fd, g_sock_path);
	if (g_dbus) dbus_connection_unref(g_dbus);
	profiles_free_all();
	return 0;
}
