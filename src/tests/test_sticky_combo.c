/* Tests for sticky_combo.c — modifier-holding combo dispatcher.
 *
 * The module emits via uinput.c helpers; in the test fixture we hand
 * it a pipe write-end as the "uinput fd" and read the resulting
 * struct input_event stream from the read-end to assert state
 * transitions:
 *   - first press            → mod_down, SYN, key_down, SYN, key_up, SYN
 *                              (NO mod_up — sticky)
 *   - same-combo repress     → key_down, SYN, key_up, SYN (no extra mod events)
 *   - different-combo repress → mod_up of old, SYN, mod_down of new, SYN, key tap
 *   - tick past deadline     → mod_up, SYN
 *   - release_now            → mod_up, SYN (idempotent)
 *
 * The KEY_COMBO_*_NS sleeps inside the helpers slow each press to
 * ~70 ms; that's tolerable for unit tests.
 */

#include "sticky_combo.h"
#include "uinput.h"

#include <assert.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <unistd.h>

#include <linux/input.h>

/* Read one full event in blocking mode. The fixture only reads after
 * a synchronous write from the same process, so the read returns
 * immediately with data — no need to handle EAGAIN. */
static void expect_event(int rfd, int type, int code, int value)
{
	struct input_event ev;
	ssize_t n = read(rfd, &ev, sizeof(ev));
	assert(n == (ssize_t)sizeof(ev));
	if (ev.type != type || ev.code != code || ev.value != value) {
		fprintf(stderr, "expected (type=%d code=%d val=%d) got (type=%d code=%d val=%d)\n",
			type, code, value, ev.type, ev.code, ev.value);
		assert(0);
	}
}

/* Assert the pipe has no more pending bytes. poll() with timeout 0
 * peeks at readability without blocking. */
static void expect_empty(int rfd)
{
	struct pollfd pfd = {.fd = rfd, .events = POLLIN};
	int rc = poll(&pfd, 1, 0);
	assert(rc == 0 && "expected event pipe to be drained");
}

/* Drain all pending events from the pipe — used after a press whose
 * exact byte stream isn't being asserted, so subsequent expectations
 * start fresh. */
static void drain(int rfd)
{
	struct pollfd pfd = {.fd = rfd, .events = POLLIN};
	struct input_event ev;
	while (poll(&pfd, 1, 0) > 0 && (pfd.revents & POLLIN)) {
		ssize_t n = read(rfd, &ev, sizeof(ev));
		if (n <= 0)
			break;
	}
}

int main(void)
{
	int pipefd[2];
	int rc = pipe(pipefd);
	assert(rc == 0);
	int rfd = pipefd[0];
	int wfd = pipefd[1];

	struct sticky_combo_state s;
	sticky_combo_init(&s);
	assert(s.active == 0);
	assert(sticky_combo_ms_until_deadline(&s, 1000) == -1);

	/* Case 1 — first press of Alt+Tab.
	 * Expected stream:
	 *   KEY LEFTALT 1, SYN, KEY TAB 1, SYN, KEY TAB 0, SYN
	 * Sticky stays active, modifier release is NOT emitted yet. */
	struct btn_key_combo alt_tab = {
		.mods = {KEY_LEFTALT},
		.n_mods = 1,
		.key = KEY_TAB,
	};
	sticky_combo_press(&s, wfd, &alt_tab, 1000);
	assert(s.active == 1);
	assert(s.n_mods == 1);
	assert(s.mods[0] == KEY_LEFTALT);
	assert(s.deadline_ms == 1000 + STICKY_COMBO_TIMEOUT_MS);

	expect_event(rfd, EV_KEY, KEY_LEFTALT, 1);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_event(rfd, EV_KEY, KEY_TAB, 1);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_event(rfd, EV_KEY, KEY_TAB, 0);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	/* No more events queued — modifier release is deferred. */
	expect_empty(rfd);

	/* Case 2 — same combo re-pressed inside the deadline.
	 * Only the key tap should fire; modifier stays held. */
	sticky_combo_press(&s, wfd, &alt_tab, 1100);
	assert(s.active == 1);
	assert(s.deadline_ms == 1100 + STICKY_COMBO_TIMEOUT_MS);

	expect_event(rfd, EV_KEY, KEY_TAB, 1);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_event(rfd, EV_KEY, KEY_TAB, 0);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_empty(rfd);

	/* Case 3 — tick with deadline not yet reached is a no-op. */
	sticky_combo_tick(&s, wfd, 1200);
	assert(s.active == 1);
	expect_empty(rfd);

	/* Case 4 — tick past the deadline releases the modifier. */
	sticky_combo_tick(&s, wfd, 1100 + STICKY_COMBO_TIMEOUT_MS + 1);
	assert(s.active == 0);
	assert(s.n_mods == 0);

	expect_event(rfd, EV_KEY, KEY_LEFTALT, 0);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_empty(rfd);

	/* Case 5 — release_now is idempotent on idle state. */
	sticky_combo_release_now(&s, wfd);
	assert(s.active == 0);
	expect_empty(rfd);

	/* Case 6 — switching to a different combo while sticky releases
	 * the old chord cleanly before pressing the new one. */
	sticky_combo_press(&s, wfd, &alt_tab, 2000);
	drain(rfd); /* consume the press events */

	struct btn_key_combo ctrl_shift_s = {
		.mods = {KEY_LEFTCTRL, KEY_LEFTSHIFT},
		.n_mods = 2,
		.key = KEY_S,
	};
	sticky_combo_press(&s, wfd, &ctrl_shift_s, 2050);
	assert(s.active == 1);
	assert(s.n_mods == 2);
	assert(s.mods[0] == KEY_LEFTCTRL);
	assert(s.mods[1] == KEY_LEFTSHIFT);

	/* Expected stream after the switch:
	 *   ALT 0, SYN          (old chord released)
	 *   CTRL 1, SHIFT 1, SYN (new mods pressed together)
	 *   S 1, SYN
	 *   S 0, SYN            (tap)
	 */
	expect_event(rfd, EV_KEY, KEY_LEFTALT, 0);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_event(rfd, EV_KEY, KEY_LEFTCTRL, 1);
	expect_event(rfd, EV_KEY, KEY_LEFTSHIFT, 1);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_event(rfd, EV_KEY, KEY_S, 1);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_event(rfd, EV_KEY, KEY_S, 0);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_empty(rfd);

	/* Case 7 — release_now while a chord is held emits a clean
	 * reverse-order modifier release. */
	sticky_combo_release_now(&s, wfd);
	assert(s.active == 0);

	expect_event(rfd, EV_KEY, KEY_LEFTSHIFT, 0);
	expect_event(rfd, EV_KEY, KEY_LEFTCTRL, 0);
	expect_event(rfd, EV_SYN, SYN_REPORT, 0);
	expect_empty(rfd);

	/* Case 8 — ms_until_deadline returns a sensible value and 0
	 * once the deadline has passed (clamped, never negative). */
	sticky_combo_press(&s, wfd, &alt_tab, 3000);
	drain(rfd);
	assert(sticky_combo_ms_until_deadline(&s, 3000) == STICKY_COMBO_TIMEOUT_MS);
	assert(sticky_combo_ms_until_deadline(&s, 3000 + STICKY_COMBO_TIMEOUT_MS - 50) == 50);
	assert(sticky_combo_ms_until_deadline(&s, 3000 + STICKY_COMBO_TIMEOUT_MS + 999) == 0);
	sticky_combo_release_now(&s, wfd);
	drain(rfd);
	assert(sticky_combo_ms_until_deadline(&s, 3500) == -1);

	close(rfd);
	close(wfd);

	printf("test_sticky_combo: all assertions passed\n");
	return 0;
}
