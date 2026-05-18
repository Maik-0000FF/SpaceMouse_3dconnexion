/*
 * kernel_input - implementation. See kernel_input.h.
 */
#define _GNU_SOURCE
#include "kernel_input.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <linux/input.h>

#include "device.h"

/* Per-axis state cached between EV_ABS events; flushed at SYN_REPORT. */
static int g_kinput_state[6] = {0};
static int g_kinput_dirty = 0;

void kinput_reset_state(void)
{
	for (int i = 0; i < 6; i++)
		g_kinput_state[i] = 0;
	g_kinput_dirty = 0;
}

int kinput_open(int verbose)
{
	DIR *d = opendir("/dev/input/by-id");
	if (!d) {
		if (verbose)
			perror("spacemouse-desktop: opendir /dev/input/by-id");
		return -1;
	}

	char path[512] = {0};
	struct dirent *ent;
	while ((ent = readdir(d))) {
		if (strstr(ent->d_name, "3Dconnexion") && strstr(ent->d_name, "-event-")) {
			snprintf(path, sizeof(path), "/dev/input/by-id/%s", ent->d_name);
			break;
		}
	}
	closedir(d);

	if (!path[0]) {
		if (verbose)
			fprintf(stderr, "spacemouse-desktop: no 3Dconnexion event device under "
					"/dev/input/by-id\n");
		return -1;
	}

	int fd = open(path, O_RDONLY | O_NONBLOCK);
	if (fd < 0) {
		if (verbose)
			fprintf(stderr, "spacemouse-desktop: open %s: %s\n", path, strerror(errno));
		return -1;
	}

	/* Reset cached state — after a reconnect the device starts fresh. */
	kinput_reset_state();

	struct device_info info;
	if (device_detect_from_fd(fd, &info) == 0 && verbose) {
		fprintf(stderr,
			"spacemouse-desktop: detected %s (%04x:%04x), %d buttons\n",
			info.display_name, info.vid, info.pid,
			info.button_count);
	}

	fprintf(stderr, "spacemouse-desktop: kernel input opened: %s\n", path);
	return fd;
}

/* Map a Linux EV_KEY code to a 0-based bnum for SpaceMouse devices.
 *
 * The HID layer assigns the first 10 puck buttons to BTN_0..BTN_9
 * (0x100..0x109). For devices with more buttons (SpacePilot Pro = 31,
 * SpaceMouse Enterprise = 31) the kernel uses BTN_TRIGGER_HAPPY1+
 * (0x2c1..0x2e8) for buttons 10..49. Anything outside both ranges is
 * not a SpaceMouse button (returns -1). Matches spacenavd's mapping.
 */
static int kinput_code_to_bnum(int code)
{
	if (code >= BTN_0 && code <= BTN_9)
		return code - BTN_0;
	if (code >= BTN_TRIGGER_HAPPY1 && code <= BTN_TRIGGER_HAPPY40)
		return 10 + (code - BTN_TRIGGER_HAPPY1);
	return -1;
}

int kinput_poll_event(int fd, struct kinput_event *out)
{
	struct input_event ie;
	while (read(fd, &ie, sizeof(ie)) == (ssize_t)sizeof(ie)) {
		if (ie.type == EV_ABS && ie.code <= 5) {
			g_kinput_state[ie.code] = ie.value;
			g_kinput_dirty = 1;
		} else if (ie.type == EV_KEY) {
			int bnum = kinput_code_to_bnum(ie.code);
			if (bnum < 0)
				continue;
			out->type = KIE_BUTTON;
			out->button.bnum = bnum;
			out->button.press = ie.value;
			return 1;
		} else if (ie.type == EV_SYN && ie.code == SYN_REPORT) {
			if (g_kinput_dirty) {
				out->type = KIE_MOTION;
				out->motion.x = g_kinput_state[0];
				out->motion.y = g_kinput_state[1];
				out->motion.z = g_kinput_state[2];
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
