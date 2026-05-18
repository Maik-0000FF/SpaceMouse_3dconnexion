/*
 * config - JSON profile loader. See config.h for the API contract.
 */
#define _GNU_SOURCE
#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <json-c/json.h>

#include "spacemouse-core.h"

/* ── Profile table (definitions for the externs in config.h) ────────── */

struct profile g_profiles[MAX_PROFILES];
int g_profile_count = 0;
int g_active_profile = 0;

/* ── Action-string parsing ──────────────────────────────────────────── */

static enum axis_action parse_axis_action(const char *s)
{
	if (!s)
		return ACT_NONE;
	if (strcmp(s, "scroll_h") == 0)
		return ACT_SCROLL_H;
	if (strcmp(s, "scroll_v") == 0)
		return ACT_SCROLL_V;
	if (strcmp(s, "zoom") == 0)
		return ACT_ZOOM;
	if (strcmp(s, "desktop_switch") == 0)
		return ACT_DESKTOP_SWITCH;
	if (strcmp(s, "volume") == 0)
		return ACT_VOLUME;
	return ACT_NONE;
}

static enum btn_action parse_btn_action(const char *s)
{
	if (!s)
		return BTNACT_NONE;
	if (strcmp(s, "overview") == 0)
		return BTNACT_OVERVIEW;
	if (strcmp(s, "show_desktop") == 0)
		return BTNACT_SHOW_DESKTOP;
	if (strcmp(s, "volume_up") == 0)
		return BTNACT_VOLUME_UP;
	if (strcmp(s, "volume_down") == 0)
		return BTNACT_VOLUME_DOWN;
	if (strcmp(s, "mute") == 0)
		return BTNACT_MUTE;
	if (strcmp(s, "play_pause") == 0)
		return BTNACT_PLAY_PAUSE;
	if (strcmp(s, "next_track") == 0)
		return BTNACT_NEXT_TRACK;
	if (strcmp(s, "prev_track") == 0)
		return BTNACT_PREV_TRACK;
	return BTNACT_NONE;
}

/* Apply a full axis action string to slot idx of config c. Handles both
 * simple action names and the parameterized "key_pair:NEG,POS" format. */
static void apply_axis_action(struct config *c, int idx, const char *s)
{
	c->axis_key_neg[idx] = 0;
	c->axis_key_pos[idx] = 0;
	if (!s) {
		c->axis_map[idx] = ACT_NONE;
		return;
	}
	if (strncmp(s, "key_pair:", 9) == 0) {
		const char *rest = s + 9;
		const char *comma = strchr(rest, ',');
		if (comma) {
			char neg_name[32] = {0};
			size_t neg_len = (size_t)(comma - rest);
			if (neg_len > 0 && neg_len < sizeof(neg_name)) {
				memcpy(neg_name, rest, neg_len);
				int neg = lookup_key(neg_name);
				int pos = lookup_key(comma + 1);
				if (neg && pos) {
					c->axis_map[idx] = ACT_KEY_PAIR;
					c->axis_key_neg[idx] = neg;
					c->axis_key_pos[idx] = pos;
					return;
				}
			}
		}
		c->axis_map[idx] = ACT_NONE;
		return;
	}
	c->axis_map[idx] = parse_axis_action(s);
}

/* Apply a full button action string to slot idx of config c. Handles both
 * simple action names and the parameterized "key:NAME" format. */
static void apply_btn_action(struct config *c, int idx, const char *s)
{
	c->btn_key[idx] = 0;
	if (!s) {
		c->btn_map[idx] = BTNACT_NONE;
		return;
	}
	if (strncmp(s, "key:", 4) == 0) {
		int code = lookup_key(s + 4);
		if (code) {
			c->btn_map[idx] = BTNACT_KEY;
			c->btn_key[idx] = code;
			return;
		}
		c->btn_map[idx] = BTNACT_NONE;
		return;
	}
	c->btn_map[idx] = parse_btn_action(s);
}

/* ── Defaults + profile lifecycle ───────────────────────────────────── */

static void config_defaults(struct config *cfg)
{
	memset(cfg, 0, sizeof(*cfg));
	cfg->deadzone = DEFAULT_DEADZONE;
	cfg->scroll_speed = DEFAULT_SCROLL_SPEED;
	cfg->scroll_exponent = DEFAULT_SCROLL_EXP;
	cfg->zoom_speed = DEFAULT_ZOOM_SPEED;
	cfg->dswitch_threshold = DEFAULT_DSWITCH_THRESH;
	cfg->dswitch_cooldown_ms = DEFAULT_DSWITCH_COOL_MS;
	cfg->axis_map[0] = ACT_SCROLL_H;
	cfg->axis_map[1] = ACT_SCROLL_V;
	cfg->axis_map[2] = ACT_ZOOM;
	cfg->axis_map[3] = ACT_NONE;
	cfg->axis_map[4] = ACT_DESKTOP_SWITCH;
	cfg->axis_map[5] = ACT_NONE;
	cfg->btn_map[0] = BTNACT_OVERVIEW;
	cfg->btn_map[1] = BTNACT_SHOW_DESKTOP;
	cfg->sensitivity = DEFAULT_SENSITIVITY;
}

static void profile_free(struct profile *p)
{
	for (int i = 0; i < p->wm_class_count; i++)
		free(p->wm_classes[i]);
	p->wm_class_count = 0;
}

void profiles_free_all(void)
{
	for (int i = 0; i < g_profile_count; i++)
		profile_free(&g_profiles[i]);
	g_profile_count = 0;
}

/* ── JSON object → profile struct ───────────────────────────────────── */

/* Parse a single profile JSON object into a profile struct.
 * If defaults is non-NULL, inherit from it first. */
static void parse_profile_obj(struct json_object *obj, struct profile *p,
			      const struct config *defaults)
{
	if (defaults)
		memcpy(&p->cfg, defaults, sizeof(p->cfg));
	else
		config_defaults(&p->cfg);

	struct json_object *val;
	struct config *c = &p->cfg;

	if (json_object_object_get_ex(obj, "deadzone", &val))
		c->deadzone = json_object_get_int(val);
	if (json_object_object_get_ex(obj, "scroll_speed", &val))
		c->scroll_speed = json_object_get_double(val);
	if (json_object_object_get_ex(obj, "scroll_exponent", &val))
		c->scroll_exponent = json_object_get_double(val);
	if (json_object_object_get_ex(obj, "zoom_speed", &val))
		c->zoom_speed = json_object_get_double(val);
	if (json_object_object_get_ex(obj, "desktop_switch_threshold", &val))
		c->dswitch_threshold = json_object_get_int(val);
	if (json_object_object_get_ex(obj, "desktop_switch_cooldown_ms", &val))
		c->dswitch_cooldown_ms = json_object_get_int(val);
	if (json_object_object_get_ex(obj, "sensitivity", &val))
		c->sensitivity = json_object_get_double(val);

	struct json_object *adz;
	if (json_object_object_get_ex(obj, "axis_deadzone", &adz)) {
		struct json_object *dv;
		const char *dz_keys[] = {"tx", "ty", "tz", "rx", "ry", "rz"};
		for (int i = 0; i < 6; i++) {
			if (json_object_object_get_ex(adz, dz_keys[i], &dv))
				c->axis_deadzone[i] = json_object_get_int(dv);
		}
	}

	struct json_object *ainv;
	if (json_object_object_get_ex(obj, "axis_invert", &ainv)) {
		struct json_object *iv;
		const char *inv_keys[] = {"tx", "ty", "tz", "rx", "ry", "rz"};
		for (int i = 0; i < 6; i++) {
			if (json_object_object_get_ex(ainv, inv_keys[i], &iv))
				c->axis_invert[i] = json_object_get_boolean(iv) ? 1 : 0;
		}
	}

	struct json_object *amap;
	if (json_object_object_get_ex(obj, "axis_mapping", &amap)) {
		struct json_object *ax;
		const char *axis_keys[6] = {"tx", "ty", "tz", "rx", "ry", "rz"};
		for (int i = 0; i < 6; i++) {
			if (json_object_object_get_ex(amap, axis_keys[i], &ax))
				apply_axis_action(c, i, json_object_get_string(ax));
		}
	}

	/* Migrate legacy global invert_scroll_x/y onto axis_invert for whichever
	 * axes are mapped to scroll_h / scroll_v. Skips axes that already have
	 * an explicit axis_invert entry, so the new key always wins. */
	struct json_object *old_ix = NULL, *old_iy = NULL;
	int has_old_ix = json_object_object_get_ex(obj, "invert_scroll_x", &old_ix);
	int has_old_iy = json_object_object_get_ex(obj, "invert_scroll_y", &old_iy);
	if (has_old_ix || has_old_iy) {
		int legacy_ix = has_old_ix && json_object_get_boolean(old_ix);
		int legacy_iy = has_old_iy && json_object_get_boolean(old_iy);
		for (int i = 0; i < 6; i++) {
			if (c->axis_invert[i])
				continue;
			if (legacy_ix && c->axis_map[i] == ACT_SCROLL_H)
				c->axis_invert[i] = 1;
			if (legacy_iy && c->axis_map[i] == ACT_SCROLL_V)
				c->axis_invert[i] = 1;
		}
	}

	struct json_object *bmap;
	if (json_object_object_get_ex(obj, "button_mapping", &bmap)) {
		struct json_object_iterator it = json_object_iter_begin(bmap);
		struct json_object_iterator end = json_object_iter_end(bmap);
		while (!json_object_iter_equal(&it, &end)) {
			const char *key = json_object_iter_peek_name(&it);
			char *endp = NULL;
			long bnum = strtol(key, &endp, 10);
			struct json_object *bval = json_object_iter_peek_value(&it);
			if (endp != key && *endp == '\0' && bnum >= 0 && bnum < MAX_BUTTONS)
				apply_btn_action(c, (int)bnum, json_object_get_string(bval));
			json_object_iter_next(&it);
		}
	}

	struct json_object *wmarr;
	if (json_object_object_get_ex(obj, "match_wm_class", &wmarr)) {
		int n = json_object_array_length(wmarr);
		if (n > MAX_WM_CLASSES)
			n = MAX_WM_CLASSES;
		for (int i = 0; i < n; i++) {
			const char *s = json_object_get_string(json_object_array_get_idx(wmarr, i));
			if (s)
				p->wm_classes[p->wm_class_count++] = strdup(s);
		}
	}

	/* Detect passthrough profiles (all axes+buttons none) — skip event processing */
	p->passthrough = 1;
	for (int i = 0; i < 6; i++) {
		if (c->axis_map[i] != ACT_NONE) {
			p->passthrough = 0;
			break;
		}
	}
	if (p->passthrough) {
		for (int i = 0; i < MAX_BUTTONS; i++) {
			if (c->btn_map[i] != BTNACT_NONE) {
				p->passthrough = 0;
				break;
			}
		}
	}
}

int config_load_all(const char *path)
{
	profiles_free_all();
	g_active_profile = 0;

	struct json_object *root = json_object_from_file(path);
	if (!root) {
		fprintf(stderr, "spacemouse-desktop: config not found at %s, using defaults\n",
			path);
		snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
		config_defaults(&g_profiles[0].cfg);
		g_profile_count = 1;
		return 0;
	}

	struct json_object *profiles_obj;
	if (json_object_object_get_ex(root, "profiles", &profiles_obj)) {
		/* Multi-profile format */

		/* Parse "default" first (always index 0) */
		struct json_object *def_obj;
		snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
		if (json_object_object_get_ex(profiles_obj, "default", &def_obj))
			parse_profile_obj(def_obj, &g_profiles[0], NULL);
		else
			config_defaults(&g_profiles[0].cfg);
		g_profile_count = 1;

		/* Parse remaining profiles (inherit from default) */
		struct json_object_iterator it = json_object_iter_begin(profiles_obj);
		struct json_object_iterator end = json_object_iter_end(profiles_obj);
		while (!json_object_iter_equal(&it, &end)) {
			const char *pname = json_object_iter_peek_name(&it);
			if (strcmp(pname, "default") != 0 && g_profile_count < MAX_PROFILES) {
				struct profile *p = &g_profiles[g_profile_count];
				memset(p, 0, sizeof(*p));
				snprintf(p->name, sizeof(p->name), "%s", pname);
				parse_profile_obj(json_object_iter_peek_value(&it), p,
						  &g_profiles[0].cfg);
				g_profile_count++;
			}
			json_object_iter_next(&it);
		}
	} else {
		/* Legacy flat format: single profile */
		snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
		parse_profile_obj(root, &g_profiles[0], NULL);
		g_profile_count = 1;
	}

	json_object_put(root);

	/* Add built-in _passthrough profile (GUI uses this while settings are open) */
	if (g_profile_count < MAX_PROFILES) {
		struct profile *pt = &g_profiles[g_profile_count];
		memset(pt, 0, sizeof(*pt));
		snprintf(pt->name, sizeof(pt->name), "_passthrough");
		/* All axes and buttons default to 0 (ACT_NONE/BTNACT_NONE) from memset */
		pt->passthrough = 1;
		g_profile_count++;
	}

	fprintf(stderr, "spacemouse-desktop: loaded %d profile(s) from %s\n", g_profile_count,
		path);
	for (int i = 0; i < g_profile_count; i++)
		fprintf(stderr, "  [%d] %s%s (wm_classes: %d)\n", i, g_profiles[i].name,
			g_profiles[i].passthrough ? " [passthrough]" : "",
			g_profiles[i].wm_class_count);
	return 0;
}
