/*
 * kernel_input - Direct read of /dev/input event device for SpaceMouse.
 *
 * Bypasses libspnav so the daemon does not have to coexist with
 * spacenavd's grab. Maintains an internal 6-axis state vector that
 * collapses ABS events into one motion event per SYN_REPORT — the
 * SpaceMouse reports absolute deflection, so we only need the latest
 * state per syn boundary.
 */
#ifndef SPACEMOUSE_KERNEL_INPUT_H
#define SPACEMOUSE_KERNEL_INPUT_H

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
	int type; /* enum kinput_event_type */
	struct kinput_motion motion;
	struct kinput_button button;
};

#include <stddef.h>

/* Most evdev nodes one SpaceMouse is read from: the axis node plus the
 * sibling button nodes a composite device (wireless receiver) splits
 * off. A cabled puck is one combined node. */
#define KINPUT_MAX_FDS 4

/* Open the SpaceMouse O_NONBLOCK. The axis node is the 3Dconnexion event
 * device under /dev/input/by-id that reports 6DOF axes (EV_ABS, or the
 * EV_REL rotational trio). When that node carries no SpaceMouse buttons,
 * sibling nodes of the same physical device that do are opened as well
 * (see kinput_phys_group). Stores up to `max` fds in `fds`, axis node
 * first, and returns how many, or -1 when no device is found.
 *
 * verbose=1 prints diagnostic messages (use at startup). verbose=0
 * suppresses the "no device found" message so reconnect retries don't
 * spam the journal while the device is unplugged. */
int kinput_open(int verbose, int *fds, int max);

/* Close the `*n` fds in `fds` and set *n to 0. */
void kinput_close(int *fds, int *n);

/* Reduce an EVIOCGPHYS topology path to the part sibling interfaces of
 * one physical device share: everything before "/input". Fills `out` and
 * returns 1, or returns 0 when nothing usable remains (NULL, empty, or
 * a path that starts with "/input"). */
int kinput_phys_group(const char *phys, char *out, size_t len);

/* Drain pending events from `fd`. On the first SYN_REPORT or BTN event
 * fills *out and returns 1. Returns 0 if the input buffer drained
 * without producing a complete event. Safe to call repeatedly. All nodes
 * of one device share the axis state, so axes and buttons may come from
 * different fds. */
int kinput_poll_event(int fd, struct kinput_event *out);

/* Zero the internal axis-state cache and dirty flag. kinput_open() calls
 * this on every successful open so a reconnect doesn't replay stale
 * pre-disconnect values; tests call it to put the module into a known
 * baseline before exercising kinput_poll_event(). */
void kinput_reset_state(void);

#endif /* SPACEMOUSE_KERNEL_INPUT_H */
