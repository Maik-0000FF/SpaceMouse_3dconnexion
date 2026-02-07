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
#include <spnav.h>
#include <dbus/dbus.h>
#include <json-c/json.h>

/* ── Constants ──────────────────────────────────────────────────────── */

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
	ACT_DESKTOP_SWITCH
};

enum btn_action {
	BTNACT_NONE = 0,
	BTNACT_OVERVIEW,
	BTNACT_SHOW_DESKTOP
};

struct config {
	int deadzone;
	double scroll_speed;
	double scroll_exponent;
	double zoom_speed;
	int dswitch_threshold;
	int dswitch_cooldown_ms;
	enum axis_action axis_map[6];
	enum btn_action btn_map[16];
	int invert_scroll_x;
	int invert_scroll_y;
	double sensitivity;
};

struct profile {
	char name[64];
	char *wm_classes[MAX_WM_CLASSES];
	int wm_class_count;
	struct config cfg;
};

struct scroll_acc {
	double acc_x, acc_y, acc_z;
};

/* ── Globals ────────────────────────────────────────────────────────── */

static volatile sig_atomic_t g_running = 1;
static volatile sig_atomic_t g_reload = 0;

static int g_uinput_fd = -1;
static DBusConnection *g_dbus = NULL;
static char g_config_path[512];
static char g_sock_path[256];

static struct profile g_profiles[MAX_PROFILES];
static int g_profile_count = 0;
static int g_active_profile = 0;

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

	struct uinput_setup usetup;
	memset(&usetup, 0, sizeof(usetup));
	usetup.id.bustype = BUS_VIRTUAL;
	usetup.id.vendor = 0x256f;
	usetup.id.product = 0x0001;
	snprintf(usetup.name, UINPUT_MAX_NAME_SIZE, "SpaceMouse Desktop Scroll");

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
	return conn;
}

static void dbus_call_kwin(DBusConnection *conn, const char *method)
{
	if (!conn) return;
	DBusMessage *msg = dbus_message_new_method_call(
		"org.kde.KWin", "/KWin", "org.kde.KWin", method);
	if (!msg) return;
	DBusPendingCall *pending = NULL;
	dbus_connection_send_with_reply(conn, msg, &pending, 200);
	dbus_message_unref(msg);
	if (pending) {
		dbus_connection_flush(conn);
		dbus_pending_call_cancel(pending);
		dbus_pending_call_unref(pending);
	}
}

static void dbus_call_kglobalaccel(DBusConnection *conn, const char *shortcut)
{
	if (!conn) return;
	DBusMessage *msg = dbus_message_new_method_call(
		"org.kde.kglobalaccel", "/component/kwin",
		"org.kde.kglobalaccel.Component", "invokeShortcut");
	if (!msg) return;
	dbus_message_append_args(msg, DBUS_TYPE_STRING, &shortcut, DBUS_TYPE_INVALID);
	DBusPendingCall *pending = NULL;
	dbus_connection_send_with_reply(conn, msg, &pending, 200);
	dbus_message_unref(msg);
	if (pending) {
		dbus_connection_flush(conn);
		dbus_pending_call_cancel(pending);
		dbus_pending_call_unref(pending);
	}
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
	snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);

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
			snprintf(response, sizeof(response), "ERR unknown profile '%s'\n", name);
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
	return ACT_NONE;
}

static enum btn_action parse_btn_action(const char *s)
{
	if (!s) return BTNACT_NONE;
	if (strcmp(s, "overview") == 0) return BTNACT_OVERVIEW;
	if (strcmp(s, "show_desktop") == 0) return BTNACT_SHOW_DESKTOP;
	return BTNACT_NONE;
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

	struct json_object *amap;
	if (json_object_object_get_ex(obj, "axis_mapping", &amap)) {
		struct json_object *ax;
		if (json_object_object_get_ex(amap, "tx", &ax))
			c->axis_map[0] = parse_axis_action(json_object_get_string(ax));
		if (json_object_object_get_ex(amap, "ty", &ax))
			c->axis_map[1] = parse_axis_action(json_object_get_string(ax));
		if (json_object_object_get_ex(amap, "tz", &ax))
			c->axis_map[2] = parse_axis_action(json_object_get_string(ax));
		if (json_object_object_get_ex(amap, "rx", &ax))
			c->axis_map[3] = parse_axis_action(json_object_get_string(ax));
		if (json_object_object_get_ex(amap, "ry", &ax))
			c->axis_map[4] = parse_axis_action(json_object_get_string(ax));
		if (json_object_object_get_ex(amap, "rz", &ax))
			c->axis_map[5] = parse_axis_action(json_object_get_string(ax));
	}

	struct json_object *bmap;
	if (json_object_object_get_ex(obj, "button_mapping", &bmap)) {
		struct json_object_iterator it = json_object_iter_begin(bmap);
		struct json_object_iterator end = json_object_iter_end(bmap);
		while (!json_object_iter_equal(&it, &end)) {
			int bnum = atoi(json_object_iter_peek_name(&it));
			struct json_object *bval = json_object_iter_peek_value(&it);
			if (bnum >= 0 && bnum < 16)
				c->btn_map[bnum] = parse_btn_action(json_object_get_string(bval));
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
	fprintf(stderr, "spacemouse-desktop: loaded %d profile(s) from %s\n",
		g_profile_count, path);
	for (int i = 0; i < g_profile_count; i++)
		fprintf(stderr, "  [%d] %s (wm_classes: %d)\n",
			i, g_profiles[i].name, g_profiles[i].wm_class_count);
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
	fprintf(stderr, "Usage: %s [-f] [-c config.json]\n", prog);
	fprintf(stderr, "  -f  run in foreground\n");
	fprintf(stderr, "  -c  config file (default: ~/.config/spacemouse/config.json)\n");
}

int main(int argc, char **argv)
{
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

	/* Connect to spacenavd */
	if (spnav_open() == -1) {
		fprintf(stderr, "spacemouse-desktop: cannot connect to spacenavd\n");
		return 1;
	}
	spnav_client_name("spacemouse-desktop");
	fprintf(stderr, "spacemouse-desktop: connected to spacenavd\n");

	{
		char devname[256] = {0};
		unsigned int vid = 0, pid = 0;
		spnav_dev_name(devname, sizeof(devname));
		spnav_dev_usbid(&vid, &pid);
		fprintf(stderr, "spacemouse-desktop: device: %s (%04x:%04x)\n",
			devname, vid, pid);
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
	int desktop_shown = 0;

	/* poll()-based main loop */
	int spnav_fdesc = spnav_fd();

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

		struct pollfd fds[2];
		int nfds = 0;

		fds[0].fd = spnav_fdesc;
		fds[0].events = POLLIN;
		nfds = 1;

		if (cmd_fd >= 0) {
			fds[1].fd = cmd_fd;
			fds[1].events = POLLIN;
			nfds = 2;
		}

		int ret = poll(fds, nfds, 100); /* 100ms timeout for signal handling */
		if (ret < 0) {
			if (errno == EINTR) continue;
			break;
		}
		if (ret == 0) continue; /* timeout */

		/* Handle command socket */
		if (nfds > 1 && (fds[1].revents & POLLIN)) {
			cmd_handle_client(cmd_fd);
			scroll_acc_reset(&sacc);
		}

		/* Handle spnav events */
		if (fds[0].revents & POLLIN) {
			spnav_event ev;
			while (spnav_poll_event(&ev)) {
				struct config *c = &g_profiles[g_active_profile].cfg;

				if (ev.type == SPNAV_EVENT_MOTION) {
					int axes[6] = {
						ev.motion.x, ev.motion.y, ev.motion.z,
						ev.motion.rx, ev.motion.ry, ev.motion.rz
					};

					for (int i = 0; i < 6; i++) {
						double val;
						switch (c->axis_map[i]) {
						case ACT_SCROLL_H:
							val = apply_curve(axes[i], c->deadzone,
								c->scroll_exponent, c->scroll_speed)
								* c->sensitivity;
							if (c->invert_scroll_x) val = -val;
							sacc.acc_x += val;
							break;
						case ACT_SCROLL_V:
							val = apply_curve(axes[i], c->deadzone,
								c->scroll_exponent, c->scroll_speed)
								* c->sensitivity;
							if (c->invert_scroll_y) val = -val;
							sacc.acc_y -= val;
							break;
						case ACT_ZOOM:
							val = apply_curve(axes[i], c->deadzone,
								c->scroll_exponent, c->zoom_speed)
								* c->sensitivity;
							sacc.acc_z += val;
							break;
						case ACT_DESKTOP_SWITCH: {
							long long now = time_ms();
							if (abs(axes[i]) > c->dswitch_threshold &&
							    (now - last_dswitch) > c->dswitch_cooldown_ms) {
								if (axes[i] > 0)
									dbus_call_kwin(g_dbus, "nextDesktop");
								else
									dbus_call_kwin(g_dbus, "previousDesktop");
								last_dswitch = now;
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
				else if (ev.type == SPNAV_EVENT_BUTTON) {
					if (!ev.button.press) continue;
					int bnum = ev.button.bnum;
					if (bnum < 0 || bnum >= 16) continue;

					switch (c->btn_map[bnum]) {
					case BTNACT_OVERVIEW:
						dbus_call_kglobalaccel(g_dbus, "ExposeAll");
						break;
					case BTNACT_SHOW_DESKTOP: {
						desktop_shown = !desktop_shown;
						DBusMessage *msg = dbus_message_new_method_call(
							"org.kde.KWin", "/KWin",
							"org.kde.KWin", "showDesktop");
						if (msg) {
							dbus_bool_t v = desktop_shown;
							dbus_message_append_args(msg,
								DBUS_TYPE_BOOLEAN, &v,
								DBUS_TYPE_INVALID);
							dbus_connection_send(g_dbus, msg, NULL);
							dbus_connection_flush(g_dbus);
							dbus_message_unref(msg);
						}
						break;
					}
					case BTNACT_NONE: default: break;
					}
				}
			}
		}
	}

cleanup:
	fprintf(stderr, "spacemouse-desktop: shutting down\n");
	spnav_close();
	uinput_close(g_uinput_fd);
	cmd_sock_close(cmd_fd, g_sock_path);
	if (g_dbus) dbus_connection_unref(g_dbus);
	profiles_free_all();
	return 0;
}
