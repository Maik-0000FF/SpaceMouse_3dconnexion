/* Tests for kinput_reset_state() — disconnect-fix correctness.
 *
 * Without this reset, axis values from before a USB disconnect would
 * persist in the module-local g_kinput_state[] cache and replay
 * themselves on the first SYN_REPORT after reconnect, producing a
 * spurious motion event with stale coordinates on a freshly opened
 * fd. The daemon calls kinput_reset_state() from kinput_open() so
 * reconnects start from a clean slate; this test pins that behaviour
 * down so a future refactor can't quietly drop it. */

#include "kernel_input.h"

#include <assert.h>
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* Push one input_event onto the pipe's write end. The daemon's poll_event
 * loop reads on the read end, so this is byte-equivalent to the kernel
 * delivering events via /dev/input/eventN. */
static void push(int wfd, int type, int code, int value)
{
	struct input_event ie;
	memset(&ie, 0, sizeof(ie));
	ie.type = (unsigned short)type;
	ie.code = (unsigned short)code;
	ie.value = value;
	ssize_t n = write(wfd, &ie, sizeof(ie));
	assert(n == (ssize_t)sizeof(ie));
}

int main(void)
{
	int fds[2];
	assert(pipe(fds) == 0);
	int rfd = fds[0];
	int wfd = fds[1];

	/* The daemon opens its real fd O_NONBLOCK so kinput_poll_event's read
	 * loop exits with EAGAIN once the buffer is drained. Mirror that here
	 * — without it the test hangs forever in read() after the last event. */
	int flags = fcntl(rfd, F_GETFL, 0);
	assert(fcntl(rfd, F_SETFL, flags | O_NONBLOCK) == 0);

	struct kinput_event ev;

	/* Start clean. */
	kinput_reset_state();

	/* Phase 1 — pre-disconnect: axis 0 ramps to 100, syn emits motion. */
	push(wfd, EV_ABS, 0, 100);
	push(wfd, EV_SYN, SYN_REPORT, 0);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_MOTION);
	assert(ev.motion.x == 100);
	assert(ev.motion.y == 0);

	/* The cache still holds x=100 between syn reports — by design,
	 * since SpaceMouse axis values are absolute deflection, not deltas.
	 * Verify that: a fresh syn with no new ABS would still emit x=100
	 * if dirty… but dirty was cleared by the previous syn, so this
	 * second syn alone should return 0 (no event). */
	push(wfd, EV_SYN, SYN_REPORT, 0);
	assert(kinput_poll_event(rfd, &ev) == 0);

	/* Phase 2 — simulate disconnect+reconnect: reset clears both the
	 * cached axis vector and the dirty flag. */
	kinput_reset_state();

	/* Phase 3 — post-reconnect: only axis 1 moves (y=50). The motion
	 * event must carry y=50 and *zero* for the other axes — particularly
	 * x must NOT replay the pre-disconnect 100. */
	push(wfd, EV_ABS, 1, 50);
	push(wfd, EV_SYN, SYN_REPORT, 0);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_MOTION);
	assert(ev.motion.x == 0);
	assert(ev.motion.y == 50);
	assert(ev.motion.z == 0);
	assert(ev.motion.rx == 0);
	assert(ev.motion.ry == 0);
	assert(ev.motion.rz == 0);

	close(rfd);
	close(wfd);

	printf("test_kinput_state: all assertions passed\n");
	return 0;
}
