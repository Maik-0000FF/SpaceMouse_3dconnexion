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
#include <json-c/json.h>

#include "command_socket.h"
#include "config.h"
#include "dbus_actions.h"
#include "desktop_actions.h"
#include "device.h"
#include "kernel_input.h"
#include "spacemouse-core.h"
#include "sticky_combo.h"
#include "uinput.h"

/* ── Constants ──────────────────────────────────────────────────────── */

#define SPACEMOUSE_VERSION "0.1.0"

/* Profile-related constants, struct config / struct profile, action enums
 * and KEY_NAMES live in config.h and spacemouse-core.h respectively.
 * CMD_BUF_SIZE / SOCK_BACKLOG live in command_socket.h. */

/* ── Globals ────────────────────────────────────────────────────────── */

static volatile sig_atomic_t g_running = 1;
/* g_reload exported (declared extern in command_socket.h). The RELOAD
 * command socket handler sets it; the main loop polls and clears it. */
volatile sig_atomic_t g_reload = 0;

static int g_uinput_fd = -1;
static int g_kinput_fd = -1;
static char g_config_path[512];
static char g_sock_path[256];

/* g_profiles, g_profile_count, g_active_profile — owned by config.c.
 * g_de — owned by desktop_actions.c (set in main from detect_desktop_env). */

/* ── Signal handlers ────────────────────────────────────────────────── */

static void on_sigterm(int sig)
{
	(void)sig;
	g_running = 0;
}
static void on_sighup(int sig)
{
	(void)sig;
	g_reload = 1;
}

/* ── Time helpers ───────────────────────────────────────────────────── */

static long long time_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* apply_curve / scroll_acc_* — see spacemouse-core. uinput helpers — see
 * uinput.c. D-Bus calls (dbus_kwin_*, dbus_kglobalaccel_*) live in
 * dbus_actions.c. Workspace / overview / show-desktop dispatch lives
 * in desktop_actions.c. Configuration loader lives in config.c. Command
 * socket in command_socket.c. Kernel input in kernel_input.c. */

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
	/* Sticky-combo state lives at function scope so the cleanup
	 * label can release any held modifiers regardless of which
	 * code path got us there. Zero-init = "no chord held". */
	struct sticky_combo_state sticky = {0};

	if (home)
		snprintf(g_config_path, sizeof(g_config_path), "%s/.config/spacemouse/config.json",
			 home);
	else
		snprintf(g_config_path, sizeof(g_config_path), "/etc/spacemouse-desktop.conf");

	int opt;
	while ((opt = getopt(argc, argv, "fc:h")) != -1) {
		switch (opt) {
		case 'f':
			foreground = 1;
			break;
		case 'c':
			snprintf(g_config_path, sizeof(g_config_path), "%s", optarg);
			break;
		case 'h':
		default:
			usage(argv[0]);
			return opt == 'h' ? 0 : 1;
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

	/* Open kernel input device directly (bypasses spacenavd).
	 * Missing at startup is non-fatal — the main loop will retry, so
	 * the daemon survives "device unplugged before service start". */
	g_kinput_fd = kinput_open(1);
	if (g_kinput_fd < 0)
		fprintf(stderr, "spacemouse-desktop: kernel input not available yet, will retry\n");

	/* uinput */
	g_uinput_fd = uinput_open();
	if (g_uinput_fd < 0)
		fprintf(stderr, "spacemouse-desktop: uinput failed, scroll/zoom disabled\n");
	desktop_actions_set_uinput(g_uinput_fd);

	/* D-Bus (KDE-only path; other DEs ignore this entirely). */
	dbus_actions_init();
	if (!dbus_actions_is_connected())
		fprintf(stderr, "spacemouse-desktop: D-Bus failed, desktop actions disabled\n");

	/* Command socket */
	uid_t uid = getuid();
	snprintf(g_sock_path, sizeof(g_sock_path), "/run/user/%u/spacemouse-cmd.sock", uid);
	int cmd_fd = cmd_sock_open(g_sock_path);
	if (cmd_fd < 0)
		fprintf(stderr, "spacemouse-desktop: command socket failed\n");
	else
		fprintf(stderr, "spacemouse-desktop: command socket at %s\n", g_sock_path);

	/* Daemonize */
	if (!foreground) {
		pid_t pid = fork();
		if (pid < 0) {
			perror("fork");
			goto cleanup;
		}
		if (pid > 0)
			_exit(0);
		setsid();
	}

	fprintf(stderr, "spacemouse-desktop: running (PID %d), active profile: %s\n", getpid(),
		g_profiles[g_active_profile].name);

	/* State */
	struct scroll_acc sacc;
	scroll_acc_reset(&sacc);
	long long last_dswitch = 0;
	long long last_volume = 0;
	long long last_keypair[6] = {0};
	long long last_kinput_retry = 0;
	int desktop_shown = 0;
	/* sticky declared and zero-initialised earlier so the cleanup
	 * label can call sticky_combo_release_now() even on the
	 * pre-loop goto paths (fork failure). */

	while (g_running) {
		if (g_reload) {
			g_reload = 0;
			/* Release any held sticky modifiers before the reload
			 * — a profile that drops the binding shouldn't leave
			 * Alt held forever. */
			sticky_combo_release_now(&sticky, g_uinput_fd);
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

		/* Auto-release sticky modifiers if their deadline passed.
		 * The 100 ms poll() rhythm is short enough that we accept
		 * the ≤100 ms latency instead of clamping the timeout. */
		sticky_combo_tick(&sticky, g_uinput_fd, time_ms());

		/* Direct kernel read. Other clients (Blender/FreeCAD via spacenavd)
		 * read independently from the same kernel device, so we never
		 * starve them. When the device is unplugged the fd starts
		 * returning POLLERR/POLLHUP — we close it and retry kinput_open()
		 * at most once per second until the device is back. */

		if (g_kinput_fd < 0) {
			long long now = time_ms();
			if (now - last_kinput_retry >= 1000) {
				last_kinput_retry = now;
				g_kinput_fd = kinput_open(0);
				if (g_kinput_fd >= 0) {
					fprintf(stderr,
						"spacemouse-desktop: kernel input reconnected\n");
					scroll_acc_reset(&sacc);
				}
			}
		}

		struct pollfd fds[2];
		int nfds = 0;
		int kinput_idx = -1;

		if (g_kinput_fd >= 0) {
			kinput_idx = nfds;
			fds[nfds].fd = g_kinput_fd;
			fds[nfds].events = POLLIN;
			nfds++;
		}

		int cmd_idx = -1;
		if (cmd_fd >= 0) {
			cmd_idx = nfds;
			fds[nfds].fd = cmd_fd;
			fds[nfds].events = POLLIN;
			nfds++;
		}

		int ret = poll(fds, nfds, 100); /* 100ms timeout for signal handling */
		if (ret < 0) {
			if (errno == EINTR)
				continue;
			break;
		}
		if (ret == 0) {
			/* Reconnect D-Bus if needed, drain incoming messages */
			dbus_actions_ensure_connected();
			dbus_actions_pump();
			continue;
		}

		/* Handle command socket */
		if (cmd_idx >= 0 && (fds[cmd_idx].revents & POLLIN)) {
			cmd_handle_client(cmd_fd);
			scroll_acc_reset(&sacc);
		}

		/* Detect device unplug: poll() flags the fd with POLLERR/POLLHUP
		 * once /dev/input/eventN is gone. Without this we'd spin at 100%
		 * CPU on the dead fd. */
		if (kinput_idx >= 0 && (fds[kinput_idx].revents & (POLLERR | POLLHUP | POLLNVAL))) {
			fprintf(stderr,
				"spacemouse-desktop: kernel input disconnected, will reconnect\n");
			close(g_kinput_fd);
			g_kinput_fd = -1;
			device_clear_cache();
			last_kinput_retry = time_ms();
			scroll_acc_reset(&sacc);
			continue;
		}

		/* Handle kernel input events. In passthrough profiles we still
		 * drain the device (to keep its read buffer empty) but skip
		 * action dispatch — all axis_map entries are ACT_NONE anyway. */
		if (kinput_idx >= 0 && (fds[kinput_idx].revents & POLLIN)) {
			struct kinput_event ev;

			while (kinput_poll_event(g_kinput_fd, &ev)) {
				struct config *c = &g_profiles[g_active_profile].cfg;

				if (ev.type == KIE_MOTION) {
					int axes[6] = {ev.motion.x,  ev.motion.y,  ev.motion.z,
						       ev.motion.rx, ev.motion.ry, ev.motion.rz};

					for (int i = 0; i < 6; i++) {
						int dz = c->axis_deadzone[i] > 0
								 ? c->axis_deadzone[i]
								 : c->deadzone;
						if (abs(axes[i]) < dz)
							continue;
						double val;
						switch (c->axis_map[i]) {
						case ACT_SCROLL_H:
							val = apply_curve(axes[i], dz,
									  c->scroll_exponent,
									  c->scroll_speed) *
							      c->sensitivity;
							if (c->axis_invert[i])
								val = -val;
							sacc.acc_x += val;
							break;
						case ACT_SCROLL_V:
							val = apply_curve(axes[i], dz,
									  c->scroll_exponent,
									  c->scroll_speed) *
							      c->sensitivity;
							if (c->axis_invert[i])
								val = -val;
							sacc.acc_y -= val;
							break;
						case ACT_ZOOM:
							val = apply_curve(axes[i], dz,
									  c->scroll_exponent,
									  c->zoom_speed) *
							      c->sensitivity;
							if (c->axis_invert[i])
								val = -val;
							sacc.acc_z += val;
							break;
						case ACT_DESKTOP_SWITCH: {
							long long now = time_ms();
							long long elapsed = now - last_dswitch;
							int val = abs(axes[i]);
							if (val > c->dswitch_threshold &&
							    elapsed > c->dswitch_cooldown_ms) {
								const char *dir = axes[i] > 0
											  ? "next"
											  : "prev";
								fprintf(stderr,
									"spacemouse-desktop: "
									"dswitch axis=%d val=%d "
									"thresh=%d elapsed=%lldms "
									"-> %s\n",
									i, axes[i],
									c->dswitch_threshold,
									elapsed, dir);
								desktop_action_workspace(
									axes[i] > 0 ? 1 : -1);
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
								fprintf(stderr,
									"spacemouse-desktop: "
									"volume axis=%d val=%d -> "
									"%s\n",
									i, axes[i],
									up ? "up" : "down");
								emit_key_tap(g_uinput_fd,
									     up ? KEY_VOLUMEUP
										: KEY_VOLUMEDOWN);
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
								int code =
									axes[i] > 0
										? c->axis_key_pos[i]
										: c->axis_key_neg
											  [i];
								if (code)
									emit_key_tap(g_uinput_fd,
										     code);
								last_keypair[i] = now;
							}
							break;
						}
						case ACT_NONE:
						default:
							break;
						}
					}

					if (g_uinput_fd >= 0) {
						int sx = scroll_acc_consume(&sacc.acc_x);
						int sy = scroll_acc_consume(&sacc.acc_y);
						int sz = scroll_acc_consume(&sacc.acc_z);
						emit_scroll(g_uinput_fd, sx, sy);
						if (sz != 0)
							emit_zoom(g_uinput_fd, sz);
					}
				} else if (ev.type == KIE_BUTTON) {
					if (!ev.button.press)
						continue;
					int bnum = ev.button.bnum;
					if (bnum < 0 || bnum >= MAX_BUTTONS)
						continue;

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
						if (c->btn_key[bnum].key)
							sticky_combo_press(&sticky, g_uinput_fd,
									   &c->btn_key[bnum],
									   time_ms());
						break;
					case BTNACT_EXEC:
						if (c->btn_exec_argv[bnum] &&
						    c->btn_exec_argv[bnum][0])
							spawn_command(c->btn_exec_argv[bnum]);
						break;
					case BTNACT_NONE:
					default:
						break;
					}
				}
			}
		}

		/* Drain D-Bus incoming messages after processing events
		 * (prevents message buildup that kills the connection) */
		dbus_actions_pump();
	}

cleanup:
	fprintf(stderr, "spacemouse-desktop: shutting down\n");
	/* Drop any held sticky modifiers before tearing down the uinput
	 * device so the compositor doesn't see Alt-down at our last gasp. */
	sticky_combo_release_now(&sticky, g_uinput_fd);
	if (g_kinput_fd >= 0)
		close(g_kinput_fd);
	uinput_close(g_uinput_fd);
	cmd_sock_close(cmd_fd, g_sock_path);
	dbus_actions_close();
	profiles_free_all();
	return 0;
}
