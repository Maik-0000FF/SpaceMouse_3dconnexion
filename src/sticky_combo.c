/*
 * sticky_combo - implementation. See sticky_combo.h.
 */
#define _GNU_SOURCE
#include "sticky_combo.h"

#include <string.h>

#include "uinput.h"

static int mods_match(const struct sticky_combo_state *s, const struct btn_key_combo *combo)
{
	if (s->n_mods != combo->n_mods)
		return 0;
	for (int i = 0; i < s->n_mods; i++)
		if (s->mods[i] != combo->mods[i])
			return 0;
	return 1;
}

void sticky_combo_init(struct sticky_combo_state *s)
{
	memset(s, 0, sizeof(*s));
}

void sticky_combo_release_now(struct sticky_combo_state *s, int fd)
{
	if (!s->active)
		return;
	/* Settle before release so the compositor doesn't merge the
	 * mod-up into the same input batch as whatever fired the
	 * release call (profile switch / shutdown). */
	emit_settle_after_mods();
	emit_keys_release(fd, s->mods, s->n_mods);
	s->active = 0;
	s->n_mods = 0;
}

void sticky_combo_press(struct sticky_combo_state *s, int fd, const struct btn_key_combo *combo,
			long long now_ms)
{
	if (!combo || !combo->key)
		return;

	if (s->active && !mods_match(s, combo)) {
		/* Different chord while another is sticky — drop the
		 * old one cleanly before starting fresh. */
		sticky_combo_release_now(s, fd);
	}

	if (!s->active) {
		if (combo->n_mods > 0) {
			emit_keys_press(fd, combo->mods, combo->n_mods);
			emit_settle_after_mods();
		}
		memcpy(s->mods, combo->mods, sizeof(int) * (size_t)combo->n_mods);
		s->n_mods = combo->n_mods;
		s->active = 1;
	}

	emit_key_tap_held(fd, combo->key);
	s->deadline_ms = now_ms + STICKY_COMBO_TIMEOUT_MS;
}

void sticky_combo_tick(struct sticky_combo_state *s, int fd, long long now_ms)
{
	if (!s->active)
		return;
	if (now_ms < s->deadline_ms)
		return;
	sticky_combo_release_now(s, fd);
}

long long sticky_combo_ms_until_deadline(const struct sticky_combo_state *s, long long now_ms)
{
	if (!s->active)
		return -1;
	long long delta = s->deadline_ms - now_ms;
	return delta < 0 ? 0 : delta;
}
