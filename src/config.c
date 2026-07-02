/*
 * config - JSON profile loader. See config.h for the API contract.
 */
#define _GNU_SOURCE
#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <json-c/json.h>

#include <linux/input-event-codes.h>

#include "spacemouse-core.h"

/* Modifier name → keycode. Kept local to the parser because KEY_NAMES
 * (in spacemouse-core.c) intentionally omits modifiers — those are
 * only meaningful as part of a combo, never standalone. */
struct mod_name {
	const char *name;
	int code;
};
static const struct mod_name MOD_NAMES[] = {
	{"CTRL", KEY_LEFTCTRL}, {"CONTROL", KEY_LEFTCTRL}, {"SHIFT", KEY_LEFTSHIFT},
	{"ALT", KEY_LEFTALT},	{"META", KEY_LEFTMETA},	   {"SUPER", KEY_LEFTMETA},
	{"WIN", KEY_LEFTMETA},	{"CMD", KEY_LEFTMETA},	   {NULL, 0},
};

static int lookup_modifier(const char *name)
{
	if (!name)
		return 0;
	for (const struct mod_name *m = MOD_NAMES; m->name; m++)
		if (strcasecmp(name, m->name) == 0)
			return m->code;
	return 0;
}

/* Parse "Ctrl+Shift+S" into combo. Returns 1 on success, 0 on bad
 * input. Caller has already stripped the "key:" prefix. The final
 * token is the end key (looked up via lookup_key); everything before
 * it is a modifier (looked up via lookup_modifier). Empty or
 * malformed strings, unknown names, or > BTN_KEY_MAX_MODS modifiers
 * all return 0 and leave *out untouched. */
static int parse_key_combo(const char *s, struct btn_key_combo *out)
{
	if (!s || !*s)
		return 0;
	char buf[128];
	size_t len = strnlen(s, sizeof(buf));
	if (len >= sizeof(buf))
		return 0;
	memcpy(buf, s, len);
	buf[len] = '\0';

	struct btn_key_combo tmp;
	memset(&tmp, 0, sizeof(tmp));

	char *save = NULL;
	char *tok = strtok_r(buf, "+", &save);
	char *prev = NULL;
	while (tok) {
		if (prev) {
			int mod = lookup_modifier(prev);
			if (!mod || tmp.n_mods >= BTN_KEY_MAX_MODS)
				return 0;
			/* Reject duplicate modifiers — keeps emit
			 * order stable and signals a typo. */
			for (int i = 0; i < tmp.n_mods; i++)
				if (tmp.mods[i] == mod)
					return 0;
			tmp.mods[tmp.n_mods++] = mod;
		}
		prev = tok;
		tok = strtok_r(NULL, "+", &save);
	}
	if (!prev)
		return 0;
	int key = lookup_key(prev);
	if (!key)
		return 0;
	tmp.key = key;
	*out = tmp;
	return 1;
}

/* Free a per-button argv allocated by parse_exec_argv. */
static void btn_exec_free(char **argv)
{
	if (!argv)
		return;
	for (char **p = argv; *p; p++)
		free(*p);
	free((void *)argv);
}

/* Parse a JSON array of strings into a NULL-terminated argv array.
 * Returns NULL on bad input. Caller owns the result and must free
 * with btn_exec_free. */
static char **parse_exec_argv(struct json_object *arr)
{
	if (!arr || json_object_get_type(arr) != json_type_array)
		return NULL;
	int n = json_object_array_length(arr);
	if (n <= 0)
		return NULL;
	char **argv = (char **)calloc((size_t)n + 1, sizeof(char *));
	if (!argv)
		return NULL;
	for (int i = 0; i < n; i++) {
		struct json_object *el = json_object_array_get_idx(arr, i);
		/* Reject non-string elements outright instead of letting
		 * json_object_get_string() coerce numbers/bools. A config
		 * like "cmd": [123, true] should fall back to NONE, not
		 * launch argv ["123", "true"]. */
		if (!el || json_object_get_type(el) != json_type_string) {
			btn_exec_free(argv);
			return NULL;
		}
		const char *s = json_object_get_string(el);
		if (!s) {
			btn_exec_free(argv);
			return NULL;
		}
		argv[i] = strdup(s);
		if (!argv[i]) {
			btn_exec_free(argv);
			return NULL;
		}
	}
	argv[n] = NULL;
	return argv;
}

/* Deep-copy a NULL-terminated argv array. Returns NULL on NULL input
 * or allocation failure. Caller owns the result and frees it with
 * btn_exec_free. */
static char **btn_exec_dup(char *const *argv)
{
	if (!argv)
		return NULL;
	int n = 0;
	while (argv[n])
		n++;
	char **copy = (char **)calloc((size_t)n + 1, sizeof(char *));
	if (!copy)
		return NULL;
	for (int i = 0; i < n; i++) {
		copy[i] = strdup(argv[i]);
		if (!copy[i]) {
			btn_exec_free(copy);
			return NULL;
		}
	}
	copy[n] = NULL;
	return copy;
}

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

/* Reset a button slot to NONE and free any exec-argv that was hung
 * off it. Callers use this before re-binding so a profile reload
 * doesn't leak. */
static void btn_slot_reset(struct config *c, int idx)
{
	c->btn_map[idx] = BTNACT_NONE;
	memset(&c->btn_key[idx], 0, sizeof(c->btn_key[idx]));
	if (c->btn_exec_argv[idx]) {
		btn_exec_free(c->btn_exec_argv[idx]);
		c->btn_exec_argv[idx] = NULL;
	}
}

/* Apply a full button action string to slot idx of config c. Handles both
 * simple action names and the parameterized "key:NAME[+MOD...]" format. */
static void apply_btn_action(struct config *c, int idx, const char *s)
{
	btn_slot_reset(c, idx);
	if (!s)
		return;
	if (strncmp(s, "key:", 4) == 0) {
		struct btn_key_combo combo;
		if (parse_key_combo(s + 4, &combo)) {
			c->btn_map[idx] = BTNACT_KEY;
			c->btn_key[idx] = combo;
		}
		return;
	}
	c->btn_map[idx] = parse_btn_action(s);
}

/* ── Object-form button action handlers ──────────────────────────────
 *
 * Each handler takes the slot config + the JSON object and applies
 * its specific shape. Handlers always start by calling btn_slot_reset
 * so a malformed body leaves the slot at NONE rather than half-bound.
 * Register a new type by adding one entry to OBJ_HANDLERS. */

static void apply_obj_exec(struct config *c, int idx, struct json_object *obj)
{
	btn_slot_reset(c, idx);
	struct json_object *cmd_val;
	if (!json_object_object_get_ex(obj, "cmd", &cmd_val))
		return;
	char **argv = parse_exec_argv(cmd_val);
	if (!argv)
		return;
	c->btn_map[idx] = BTNACT_EXEC;
	c->btn_exec_argv[idx] = argv;
}

typedef void (*btn_obj_handler_fn)(struct config *c, int idx, struct json_object *obj);
struct btn_obj_handler {
	const char *type;
	btn_obj_handler_fn fn;
};
static const struct btn_obj_handler OBJ_HANDLERS[] = {
	{"exec", apply_obj_exec},
	{NULL, NULL},
};

/* Apply a JSON object-form button action {"type": "...", ...}. Returns
 * 1 if a handler matched the type (even if the body was malformed —
 * the slot is then reset to NONE), 0 if the type is unknown so the
 * caller can fall back to string parsing or log. */
static int apply_btn_action_obj(struct config *c, int idx, struct json_object *obj)
{
	struct json_object *type_val;
	if (!json_object_object_get_ex(obj, "type", &type_val))
		return 0;
	const char *type = json_object_get_string(type_val);
	if (!type)
		return 0;
	for (const struct btn_obj_handler *h = OBJ_HANDLERS; h->type; h++) {
		if (strcmp(h->type, type) == 0) {
			h->fn(c, idx, obj);
			return 1;
		}
	}
	return 0;
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
	/* Reset every button slot so per-action heap resources (exec argv
	 * today, plugin instances tomorrow) hit a single cleanup path. */
	for (int i = 0; i < MAX_BUTTONS; i++)
		btn_slot_reset(&p->cfg, i);
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
	if (defaults) {
		memcpy(&p->cfg, defaults, sizeof(p->cfg));
		/* The flat copy above aliased the owning btn_exec_argv pointers
		 * from the default profile. Give this profile its own deep
		 * copies so freeing (or re-binding) one profile never
		 * double-frees or dangles another profile's exec argv. */
		for (int i = 0; i < MAX_BUTTONS; i++) {
			if (!p->cfg.btn_exec_argv[i])
				continue;
			p->cfg.btn_exec_argv[i] = btn_exec_dup(p->cfg.btn_exec_argv[i]);
			if (!p->cfg.btn_exec_argv[i])
				p->cfg.btn_map[i] = BTNACT_NONE;
		}
	} else {
		config_defaults(&p->cfg);
	}

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
			if (endp != key && *endp == '\0' && bnum >= 0 && bnum < MAX_BUTTONS) {
				/* Two value shapes:
				 *   "overview" / "key:Ctrl+Shift+S"  → string parser
				 *   {"type": "exec", "cmd": [...]}    → object dispatcher
				 * Object with unknown type silently falls through
				 * to string parsing so a future GUI that emits
				 * objects we don't yet recognise degrades gracefully. */
				if (json_object_get_type(bval) == json_type_object &&
				    apply_btn_action_obj(c, (int)bnum, bval)) {
					/* handled */
				} else {
					apply_btn_action(c, (int)bnum,
							 json_object_get_string(bval));
				}
			}
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
