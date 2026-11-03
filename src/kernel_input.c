/*
 * kernel_input - implementation. See kernel_input.h.
 */
#define _GNU_SOURCE
#include "kernel_input.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <linux/input.h>

#include "config.h"
#include "device.h"

/* Device discovery. The axis node is found by its udev by-id name; its
 * button siblings are found among all event nodes and matched by
 * identity (see open_button_siblings), because udev does not give every
 * interface of a composite device its own by-id link. */
#define BY_ID_DIR "/dev/input/by-id"
#define BY_ID_VENDOR_TAG "3Dconnexion"
#define BY_ID_EVENT_TAG "-event-"
#define EVENT_DIR "/dev/input"
#define EVENT_NODE_PREFIX "event"
#define PHYS_INTERFACE_SEP "/input"
/* Buffer for EVIOCGPHYS / EVIOCGUNIQ strings and the derived group key. */
#define NODE_ID_LEN 128

#define BITS_PER_ULONG (8 * sizeof(unsigned long))
#define BITMAP_LONGS(max) ((max) / BITS_PER_ULONG + 1)

static int kinput_code_to_bnum(int code);

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

static int bitmap_test(const unsigned long *bits, int code)
{
	return (bits[code / BITS_PER_ULONG] >> (code % BITS_PER_ULONG)) & 1UL;
}

/* True when the node reports the puck's 6DOF: ABS_X, or the relative
 * rotational trio REL_RX/RY/RZ. An ordinary mouse has neither (it reports
 * REL_X/REL_Y and wheels), so a Logitech mouse never passes. */
static int node_has_axes(int fd)
{
	unsigned long absbits[BITMAP_LONGS(ABS_MAX)] = {0};
	if (ioctl(fd, EVIOCGBIT(EV_ABS, sizeof(absbits)), absbits) >= 0 &&
	    bitmap_test(absbits, ABS_X))
		return 1;

	unsigned long relbits[BITMAP_LONGS(REL_MAX)] = {0};
	if (ioctl(fd, EVIOCGBIT(EV_REL, sizeof(relbits)), relbits) < 0)
		return 0;
	return bitmap_test(relbits, REL_RX) && bitmap_test(relbits, REL_RY) &&
	       bitmap_test(relbits, REL_RZ);
}

/* True when the node exposes at least one code kinput_code_to_bnum maps
 * to a SpaceMouse button. Mouse buttons (BTN_LEFT, ...) do not count. */
static int node_has_buttons(int fd)
{
	unsigned long keybits[BITMAP_LONGS(KEY_MAX)] = {0};
	if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(keybits)), keybits) < 0)
		return 0;
	for (int code = 0; code <= KEY_MAX; code++)
		if (bitmap_test(keybits, code) && kinput_code_to_bnum(code) >= 0)
			return 1;
	return 0;
}

/* Inputs and results of kinput_phys_group:
 *
 *   "usb-0000:00:14.0-1.2/input0"  -> 1, "usb-0000:00:14.0-1.2"
 *   "usb-0000:00:14.0-1.2/input1"  -> 1, same key: sibling interface
 *   "usb-0000:00:14.0-1.3/input0"  -> 1, "usb-0000:00:14.0-1.3": other port
 *   "isa0060/serio0/input0"        -> 1, "isa0060/serio0": first "/input"
 *   "aa:bb:cc:dd:ee:ff"            -> 1, whole string (no separator;
 *                                     Bluetooth reports the adapter address
 *                                     here, which is why siblings must also
 *                                     match on uniq)
 *   "/input0"                      -> 0, nothing before the separator
 *   ""                             -> 0
 *   NULL, out NULL, len 0          -> 0
 *   key of len or more characters  -> 0, a truncated key could merge two
 *                                     devices */
int kinput_phys_group(const char *phys, char *out, size_t len)
{
	if (!phys || !out || len == 0)
		return 0;
	const char *sep = strstr(phys, PHYS_INTERFACE_SEP);
	size_t n = sep ? (size_t)(sep - phys) : strlen(phys);
	if (n == 0 || n >= len)
		return 0;
	memcpy(out, phys, n);
	out[n] = '\0';
	return 1;
}

/* What ties the nodes of one physical device together. */
struct node_identity {
	unsigned short vendor;
	char group[NODE_ID_LEN]; /* kinput_phys_group of EVIOCGPHYS */
	char uniq[NODE_ID_LEN];	 /* EVIOCGUNIQ, empty when the device has none */
};

/* Fill *id for the node behind `fd`. Returns 0 when the node has no
 * usable topology path; such a node is never matched as a sibling. */
static int node_identity_get(int fd, struct node_identity *id)
{
	memset(id, 0, sizeof(*id));

	struct input_id iid;
	if (ioctl(fd, EVIOCGID, &iid) < 0)
		return 0;
	id->vendor = iid.vendor;

	char phys[NODE_ID_LEN] = {0};
	if (ioctl(fd, EVIOCGPHYS(sizeof(phys) - 1), phys) < 0)
		return 0;
	if (!kinput_phys_group(phys, id->group, sizeof(id->group)))
		return 0;

	/* Most USB pucks report no uniq (ENOENT); both sides then compare
	 * equal as empty strings. */
	if (ioctl(fd, EVIOCGUNIQ(sizeof(id->uniq) - 1), id->uniq) < 0)
		id->uniq[0] = '\0';
	return 1;
}

static int node_identity_equal(const struct node_identity *a, const struct node_identity *b)
{
	return a->vendor == b->vendor && strcmp(a->group, b->group) == 0 &&
	       strcmp(a->uniq, b->uniq) == 0;
}

/* Open the axis node: the first 3Dconnexion by-id event link that reports
 * axes. When no link does, fall back to the first link at all, which is
 * how the node was chosen before axes were checked. Fills `path` and
 * returns the fd, or -1. */
static int open_axis_node(int verbose, char *path, size_t len)
{
	DIR *d = opendir(BY_ID_DIR);
	if (!d) {
		if (verbose)
			perror("spacemouse-desktop: opendir " BY_ID_DIR);
		return -1;
	}

	char first[PATH_MAX] = {0};
	int fd = -1;
	struct dirent *ent;
	while ((ent = readdir(d))) {
		if (!strstr(ent->d_name, BY_ID_VENDOR_TAG) || !strstr(ent->d_name, BY_ID_EVENT_TAG))
			continue;
		char link[PATH_MAX];
		snprintf(link, sizeof(link), "%s/%s", BY_ID_DIR, ent->d_name);
		if (!first[0])
			snprintf(first, sizeof(first), "%s", link);

		int cand = open(link, O_RDONLY | O_NONBLOCK);
		if (cand < 0)
			continue;
		if (node_has_axes(cand)) {
			fd = cand;
			snprintf(path, len, "%s", link);
			break;
		}
		close(cand);
	}
	closedir(d);
	if (fd >= 0)
		return fd;

	if (!first[0]) {
		if (verbose)
			fprintf(stderr,
				"spacemouse-desktop: no 3Dconnexion event device under " BY_ID_DIR
				"\n");
		return -1;
	}
	fd = open(first, O_RDONLY | O_NONBLOCK);
	if (fd < 0) {
		if (verbose)
			fprintf(stderr, "spacemouse-desktop: open %s: %s\n", first,
				strerror(errno));
		return -1;
	}
	snprintf(path, len, "%s", first);
	return fd;
}

/* A wireless receiver can split one puck over several event nodes, e.g.
 * axes on one and buttons on another. When the axis node has no buttons,
 * open every other event node that has SpaceMouse buttons and the same
 * identity (vendor, topology group, uniq) as the axis node. The identity
 * match keeps unrelated mice and keyboards out; a node without a topology
 * path is never matched. Appends to fds[n..max-1], returns the new n. */
static int open_button_siblings(int axis_fd, int *fds, int n, int max)
{
	struct node_identity axis_id;
	struct stat axis_st;
	if (node_has_buttons(axis_fd) || !node_identity_get(axis_fd, &axis_id) ||
	    fstat(axis_fd, &axis_st) < 0)
		return n;

	DIR *d = opendir(EVENT_DIR);
	if (!d)
		return n;

	struct dirent *ent;
	while (n < max && (ent = readdir(d))) {
		if (strncmp(ent->d_name, EVENT_NODE_PREFIX, strlen(EVENT_NODE_PREFIX)) != 0)
			continue;
		char path[PATH_MAX];
		snprintf(path, sizeof(path), "%s/%s", EVENT_DIR, ent->d_name);
		int fd = open(path, O_RDONLY | O_NONBLOCK);
		if (fd < 0)
			continue;

		struct stat st;
		struct node_identity id;
		int is_axis_node = fstat(fd, &st) == 0 && st.st_rdev == axis_st.st_rdev;
		if (!is_axis_node && node_has_buttons(fd) && node_identity_get(fd, &id) &&
		    node_identity_equal(&id, &axis_id)) {
			fds[n++] = fd;
			fprintf(stderr, "spacemouse-desktop: button node opened: %s\n", path);
			continue;
		}
		close(fd);
	}
	closedir(d);
	return n;
}

int kinput_open(int verbose, int *fds, int max)
{
	if (!fds || max < 1)
		return -1;

	char path[PATH_MAX];
	int fd = open_axis_node(verbose, path, sizeof(path));
	if (fd < 0)
		return -1;

	/* Reset cached state — after a reconnect the device starts fresh. */
	kinput_reset_state();

	struct device_info info;
	if (device_detect_from_fd(fd, &info) == 0 && verbose) {
		fprintf(stderr, "spacemouse-desktop: detected %s (%04x:%04x), %d buttons\n",
			info.display_name, info.vid, info.pid, info.button_count);
	}

	fprintf(stderr, "spacemouse-desktop: kernel input opened: %s\n", path);
	fds[0] = fd;
	return open_button_siblings(fd, fds, 1, max);
}

void kinput_close(int *fds, int *n)
{
	for (int i = 0; i < *n; i++)
		close(fds[i]);
	*n = 0;
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
