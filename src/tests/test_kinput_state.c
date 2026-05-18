/* Tests for kernel_input.c:
 *   1. kinput_reset_state() — disconnect-fix correctness.
 *      Without this reset, axis values from before a USB disconnect
 *      would persist in the module-local g_kinput_state[] cache and
 *      replay themselves on the first SYN_REPORT after reconnect.
 *   2. EV_KEY → bnum mapping — covers BTN_0..BTN_9, BTN_TRIGGER_HAPPY1+
 *      and the MAX_BUTTONS clamp. Indirect: exercises the internal
 *      kinput_code_to_bnum() via kinput_poll_event() with crafted
 *      EV_KEY events on the pipe fixture.
 */

#include "config.h"
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

	/* Phase 4 — EV_KEY → bnum mapping.
	 *
	 * BTN_0..BTN_9 map straight to bnums 0..9, BTN_TRIGGER_HAPPY1+
	 * picks up at bnum 10. Codes that overshoot MAX_BUTTONS must be
	 * dropped (returns 0 from kinput_poll_event with no event emitted).
	 * Codes outside both ranges (e.g. BTN_LEFT) must also be dropped.
	 */
	kinput_reset_state();

	/* BTN_0 press → bnum 0. */
	push(wfd, EV_KEY, BTN_0, 1);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_BUTTON);
	assert(ev.button.bnum == 0);
	assert(ev.button.press == 1);

	/* BTN_9 release → bnum 9. */
	push(wfd, EV_KEY, BTN_9, 0);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_BUTTON);
	assert(ev.button.bnum == 9);
	assert(ev.button.press == 0);

	/* BTN_TRIGGER_HAPPY1 → bnum 10 (the first overflow button). */
	int happy_base = BTN_TRIGGER_HAPPY1;
	push(wfd, EV_KEY, happy_base, 1);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_BUTTON);
	assert(ev.button.bnum == 10);

	/* Highest in-range HAPPY code = MAX_BUTTONS - 1. */
	push(wfd, EV_KEY, happy_base + (MAX_BUTTONS - 11), 1);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_BUTTON);
	assert(ev.button.bnum == MAX_BUTTONS - 1);

	/* Just past the clamp: bnum would be MAX_BUTTONS → dropped.
	 * Push a sentinel motion event after it so we can distinguish
	 * "dropped" from "queue empty" — the motion must come back,
	 * proving the loop kept reading past the rejected EV_KEY. */
	push(wfd, EV_KEY, happy_base + (MAX_BUTTONS - 10), 1);
	push(wfd, EV_ABS, 2, 7);
	push(wfd, EV_SYN, SYN_REPORT, 0);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_MOTION);
	assert(ev.motion.z == 7);

	/* Out-of-range EV_KEY (e.g. BTN_LEFT) — also dropped, again
	 * proven by the sentinel motion that follows. */
	push(wfd, EV_KEY, BTN_LEFT, 1);
	push(wfd, EV_ABS, 3, 11);
	push(wfd, EV_SYN, SYN_REPORT, 0);
	assert(kinput_poll_event(rfd, &ev) == 1);
	assert(ev.type == KIE_MOTION);
	assert(ev.motion.rx == 11);

	close(rfd);
	close(wfd);

	printf("test_kinput_state: all assertions passed\n");
	return 0;
}
