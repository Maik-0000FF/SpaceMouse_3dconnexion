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

	fprintf(stderr, "spacemouse-desktop: kernel input opened: %s\n", path);
	return fd;
}

int kinput_poll_event(int fd, struct kinput_event *out)
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
