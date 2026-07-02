/*
 * uinput - implementation. See uinput.h.
 */
#define _GNU_SOURCE
#include "uinput.h"

#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/ioctl.h>

#include <linux/input.h>
#include <linux/uinput.h>

#include "spacemouse-core.h"

/* Time-unit conversions. Kept local so callers can express the timing
 * constants in milliseconds (the only unit the values are tuned in)
 * while the kernel sleep API gets nanoseconds via sleep_ms below. */
#define MS_PER_SEC 1000L
#define NS_PER_MS 1000000L

/* Hold between key-combo transitions so compositors see Alt+Tab as a
 * deliberate sequence rather than a single input batch. Without these,
 * KWin's window-switcher overlay does not surface and the Walk-Through-
 * Windows shortcut fires sporadically. Both values are in milliseconds;
 * the total combo time of ~70 ms matches what a human-typed shortcut
 * looks like to the input layer. */
#define KEY_COMBO_MOD_HOLD_MS 20
#define KEY_COMBO_KEY_HOLD_MS 30

static void sleep_ms(long ms)
{
	if (ms <= 0)
		return;
	struct timespec ts = {
		.tv_sec = ms / MS_PER_SEC,
		.tv_nsec = (ms % MS_PER_SEC) * NS_PER_MS,
	};
	nanosleep(&ts, NULL);
}

int uinput_open(void)
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
	ioctl(fd, UI_SET_KEYBIT, KEY_LEFTSHIFT);
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
	usetup.id.vendor = 0x1209; /* pid.codes assigned for testing */
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

void uinput_close(int fd)
{
	if (fd >= 0) {
		ioctl(fd, UI_DEV_DESTROY);
		close(fd);
	}
}

void emit_event(int fd, int type, int code, int val)
{
	struct input_event ie;
	memset(&ie, 0, sizeof(ie));
	ie.type = type;
	ie.code = code;
	ie.value = val;
	write(fd, &ie, sizeof(ie));
}

void emit_scroll(int fd, int dx, int dy)
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

void emit_key_tap(int fd, int code)
{
	if (fd < 0)
		return;
	emit_event(fd, EV_KEY, code, 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_KEY, code, 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void emit_keys_press(int fd, const int *codes, int n)
{
	if (fd < 0 || n <= 0)
		return;
	for (int i = 0; i < n; i++)
		emit_event(fd, EV_KEY, codes[i], 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void emit_keys_release(int fd, const int *codes, int n)
{
	if (fd < 0 || n <= 0)
		return;
	/* Reverse order matches how a human releases a chord — pop the
	 * stack from the top so the compositor sees a clean unwind. */
	for (int i = n - 1; i >= 0; i--)
		emit_event(fd, EV_KEY, codes[i], 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void emit_key_tap_held(int fd, int code)
{
	if (fd < 0)
		return;
	emit_event(fd, EV_KEY, code, 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	sleep_ms(KEY_COMBO_KEY_HOLD_MS);
	emit_event(fd, EV_KEY, code, 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void emit_settle_after_mods(void)
{
	sleep_ms(KEY_COMBO_MOD_HOLD_MS);
}

void emit_key_combo(int fd, const int *mods, int n_mods, int key)
{
	if (fd < 0)
		return;
	/* One-shot chord: press mods, settle so the compositor sees the
	 * modifier state before the key arrives (Alt+Tab's window switcher
	 * overlay won't surface otherwise), tap the key with a brief hold,
	 * settle again so the switcher commits cleanly on mod-release. */
	if (n_mods > 0) {
		emit_keys_press(fd, mods, n_mods);
		emit_settle_after_mods();
	}
	emit_key_tap_held(fd, key);
	if (n_mods > 0) {
		emit_settle_after_mods();
		emit_keys_release(fd, mods, n_mods);
	}
}

void emit_zoom(int fd, int dz)
{
	if (dz == 0)
		return;
	emit_event(fd, EV_KEY, KEY_LEFTCTRL, 1);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_REL, REL_WHEEL, dz);
	emit_event(fd, EV_REL, REL_WHEEL_HI_RES, dz * 120);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
	emit_event(fd, EV_KEY, KEY_LEFTCTRL, 0);
	emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

void spawn_command(char *const argv[])
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
			if (devnull > STDERR_FILENO)
				close(devnull);
		}
		execvp(argv[0], argv);
		_exit(127);
	}
}
