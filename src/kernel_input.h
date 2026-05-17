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

/* Discover the first 3Dconnexion event device under /dev/input/by-id
 * and open it O_NONBLOCK. Returns fd or -1 on error.
 *
 * verbose=1 prints diagnostic messages (use at startup). verbose=0
 * suppresses the "no device found" message so reconnect retries don't
 * spam the journal while the device is unplugged. */
int kinput_open(int verbose);

/* Drain pending events from `fd`. On the first SYN_REPORT or BTN event
 * fills *out and returns 1. Returns 0 if the input buffer drained
 * without producing a complete event. Safe to call repeatedly. */
int kinput_poll_event(int fd, struct kinput_event *out);

/* Zero the internal axis-state cache and dirty flag. kinput_open() calls
 * this on every successful open so a reconnect doesn't replay stale
 * pre-disconnect values; tests call it to put the module into a known
 * baseline before exercising kinput_poll_event(). */
void kinput_reset_state(void);

#endif /* SPACEMOUSE_KERNEL_INPUT_H */
