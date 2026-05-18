/*
 * sticky_combo - "modifier holds across repeats" key-combo dispatch.
 *
 * Why this exists: a one-shot emit_key_combo() does the right thing
 * for shortcuts like Ctrl+C or Ctrl+Shift+S — press the chord, release,
 * done. It does the wrong thing for Alt+Tab and similar modal switchers:
 * pressing-and-immediately-releasing Alt+Tab swaps with the most-recently-
 * used window only; to cycle through more windows the compositor's
 * window-switcher overlay needs Alt to stay held while Tab is tapped
 * repeatedly.
 *
 * This module bridges the two worlds. A button-press of a key combo is
 * routed through sticky_combo_press(): the first press emits the
 * modifiers and then taps the key, but the modifiers stay held. Each
 * subsequent press of the same combo within the timeout window re-taps
 * the key (so the switcher overlay advances by one). When no new press
 * arrives for STICKY_COMBO_TIMEOUT_MS, sticky_combo_tick() finally
 * releases the modifiers and the overlay commits its selection.
 *
 * A press of a *different* combo while one is sticky releases the old
 * one immediately and starts the new one. sticky_combo_release_now()
 * lets the caller force-release on profile reload or shutdown so the
 * compositor never sees a daemon-held modifier that outlives the
 * process.
 *
 * One instance per daemon — the state is global to the input stream
 * by nature (you cannot meaningfully sticky two combos at once).
 */
#ifndef SPACEMOUSE_STICKY_COMBO_H
#define SPACEMOUSE_STICKY_COMBO_H

#include "config.h" /* struct btn_key_combo + BTN_KEY_MAX_MODS */

/* How long modifiers stay held after the last key tap before the
 * sticky auto-releases. 1 s gives the user comfortable time to
 * chain more Tabs through the window switcher overlay; the wait
 * after the final tap before the commit is the cost of admission. */
#define STICKY_COMBO_TIMEOUT_MS 1000

struct sticky_combo_state {
	int active;
	int mods[BTN_KEY_MAX_MODS];
	int n_mods;
	long long deadline_ms;
};

/* Zero out the state — equivalent to `= {0}` but spelled out so
 * callers don't need to know the struct layout. */
void sticky_combo_init(struct sticky_combo_state *s);

/* Handle a button press bound to *combo*. Emits modifier presses
 * (if the chord differs from any currently-held one), then taps the
 * combo's key. Refreshes the auto-release deadline. */
void sticky_combo_press(struct sticky_combo_state *s, int fd, const struct btn_key_combo *combo,
			long long now_ms);

/* Idempotent. If the sticky has expired (now_ms >= deadline) the
 * held modifiers are released. Cheap to call every loop iteration;
 * does no syscalls when nothing is pending. */
void sticky_combo_tick(struct sticky_combo_state *s, int fd, long long now_ms);

/* Release held modifiers unconditionally. Used on profile reload and
 * daemon shutdown so a held Alt does not survive the event that
 * triggered the reload. */
void sticky_combo_release_now(struct sticky_combo_state *s, int fd);

/* Milliseconds until the next mandatory tick, or -1 if no sticky is
 * active. Callers that want to clamp a poll() timeout to the sticky
 * deadline read this value; the existing 100 ms tick rhythm in
 * spacemouse-desktop.c is already short enough that clamping is
 * optional. */
long long sticky_combo_ms_until_deadline(const struct sticky_combo_state *s, long long now_ms);

#endif /* SPACEMOUSE_STICKY_COMBO_H */
