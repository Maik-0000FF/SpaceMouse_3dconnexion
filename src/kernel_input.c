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

#include "config.h"
#include "device.h"

/* Per-axis state cached between axis events; flushed at SYN_REPORT. */
static int g_kinput_state[6] = {0};
static int g_kinput_dirty = 0;

/* EV_REL devices (observed on the SpaceMouse Compact).
 *
 * The puck axes arrive as EV_REL codes 0..5 carrying the current deflection.
 * Three properties of the stream shape the handling below:
 *   - The input core drops EV_REL events whose value is 0, so an axis at
 *     rest is simply absent from its frame.
 *   - Translation (codes 0..2) and rotation (codes 3..5) arrive in separate
 *     HID reports, hence separate frames; with both groups active they
 *     alternate frame by frame (about 8 ms apart on a Compact).
 *   - Nothing is sent when the puck returns to centre, so a released group
 *     never reports zeros.
 * Each group is therefore tracked on its own: a frame mentioning a group
 * replaces that group's values (unmentioned axes in it are at rest), and a
 * group that has not been refreshed for REL_GROUP_STALE_MS is read as zero
 * so a released group cannot stay stuck while the other group keeps moving. */
#define REL_GROUPS 2
#define REL_GROUP_SIZE 3
#define REL_GROUP_STALE_MS 50

static int g_rel_frame[6] = {0};
static int g_rel_group_seen[REL_GROUPS] = {0};
static long long g_rel_stamp_ms[REL_GROUPS] = {0};

void kinput_reset_state(void)
{
	for (int i = 0; i < 6; i++) {
		g_kinput_state[i] = 0;
		g_rel_frame[i] = 0;
	}
	for (int g = 0; g < REL_GROUPS; g++) {
		g_rel_group_seen[g] = 0;
		g_rel_stamp_ms[g] = 0;
	}
	g_kinput_dirty = 0;
}

/* Fold the EV_REL frame collected since the last SYN_REPORT into
 * g_kinput_state[]. now_ms is the frame's kernel timestamp. */
static void kinput_apply_rel_frame(long long now_ms)
{
	for (int g = 0; g < REL_GROUPS; g++) {
		int zero_group = 0;

		if (g_rel_group_seen[g])
			g_rel_stamp_ms[g] = now_ms;
		else
			zero_group = now_ms - g_rel_stamp_ms[g] > REL_GROUP_STALE_MS;

		for (int i = g * REL_GROUP_SIZE; i < (g + 1) * REL_GROUP_SIZE; i++) {
			int v = g_rel_group_seen[g] ? g_rel_frame[i] : g_kinput_state[i];

			if (zero_group)
				v = 0;
			if (g_kinput_state[i] != v)
				g_kinput_dirty = 1;
			g_kinput_state[i] = v;
			g_rel_frame[i] = 0;
		}
		g_rel_group_seen[g] = 0;
	}
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
		fprintf(stderr, "spacemouse-desktop: detected %s (%04x:%04x), %d buttons\n",
			info.display_name, info.vid, info.pid, info.button_count);
	}

	fprintf(stderr, "spacemouse-desktop: kernel input opened: %s\n", path);
	return fd;
}

/* Map a Linux EV_KEY code to a 0-based bnum for SpaceMouse devices.
 *
 * The HID layer assigns the first 10 puck buttons to BTN_0..BTN_9
 * (0x100..0x109). For devices with more buttons (SpacePilot Pro = 31,
 * SpaceMouse Enterprise = 31) the kernel uses BTN_TRIGGER_HAPPY1+
 * (0x2c0..0x2e7) for buttons 10..49. Anything outside both ranges is
 * not a SpaceMouse button (returns -1). Matches spacenavd's mapping.
 *
 * Result is clamped to MAX_BUTTONS so the effective button cap matches
 * the config arrays (no current device exceeds 31; the clamp guards
 * against future hardware advertising the full HAPPY range).
 */
static int kinput_code_to_bnum(int code)
{
	int bnum = -1;
	if (code >= BTN_0 && code <= BTN_9)
		bnum = code - BTN_0;
	else if (code >= BTN_TRIGGER_HAPPY1 && code <= BTN_TRIGGER_HAPPY40)
		bnum = 10 + (code - BTN_TRIGGER_HAPPY1);
	if (bnum >= MAX_BUTTONS)
		return -1;
	return bnum;
}

int kinput_poll_event(int fd, struct kinput_event *out)
{
	struct input_event ie;
	while (read(fd, &ie, sizeof(ie)) == (ssize_t)sizeof(ie)) {
		if (ie.type == EV_ABS && ie.code <= 5) {
			g_kinput_state[ie.code] = ie.value;
			g_kinput_dirty = 1;
		} else if (ie.type == EV_REL && ie.code <= 5) {
			g_rel_frame[ie.code] = ie.value;
			g_rel_group_seen[ie.code / REL_GROUP_SIZE] = 1;
		} else if (ie.type == EV_KEY) {
			int bnum = kinput_code_to_bnum(ie.code);
			if (bnum < 0)
				continue;
			out->type = KIE_BUTTON;
			out->button.bnum = bnum;
			out->button.press = ie.value;
			return 1;
		} else if (ie.type == EV_SYN && ie.code == SYN_REPORT) {
			if (g_rel_group_seen[0] || g_rel_group_seen[1])
				kinput_apply_rel_frame((long long)ie.time.tv_sec * 1000 +
						       ie.time.tv_usec / 1000);
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
