/* Tests for the legacy invert_scroll_x/y → axis_invert[6] migration in
 * config.c, plus the button-mapping parser surface:
 *   - "key:Ctrl+Shift+S" combo parsing (modifiers + end key)
 *   - "key:F" plain-key parsing (back-compat with pre-combo configs)
 *   - {"type":"exec","cmd":[...]} object-form action
 *   - graceful failure on malformed combos / unknown modifiers
 *   - reload doesn't leak per-button heap state (exec argv)
 *   - derived profiles deep-copy inherited exec argv (no alias/double-free)
 *   - exec cmd with a non-string element is rejected, not coerced */

#include "config.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <linux/input-event-codes.h>

/* Caller-owned path buffer so each invocation gets a fresh mkstemp
 * template (the trailing XXXXXX is rewritten in place). Sized for the
 * fixed prefix used here. */
static void write_tmp_config(char path[64], const char *body)
{
	strcpy(path, "/tmp/spacemouse-mig-XXXXXX");
	int fd = mkstemp(path);
	assert(fd >= 0);
	ssize_t n = write(fd, body, strlen(body));
	(void)n; /* body is bounded; partial writes ignored for this fixture */
	close(fd);
}

static const struct profile *find_profile(const char *name)
{
	for (int i = 0; i < g_profile_count; i++)
		if (strcmp(g_profiles[i].name, name) == 0)
			return &g_profiles[i];
	return NULL;
}

int main(void)
{
	/* Case 1 — pure legacy keys map onto the matching scroll axes. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"axis_mapping\": {\n"
				  "        \"tx\": \"scroll_h\", \"ty\": \"scroll_v\",\n"
				  "        \"tz\": \"none\", \"rx\": \"none\",\n"
				  "        \"ry\": \"none\", \"rz\": \"none\"\n"
				  "      },\n"
				  "      \"invert_scroll_x\": true,\n"
				  "      \"invert_scroll_y\": true\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.axis_invert[0] == 1); /* tx → scroll_h, invert_x=true */
		assert(p->cfg.axis_invert[1] == 1); /* ty → scroll_v, invert_y=true */
		for (int i = 2; i < 6; i++)
			assert(p->cfg.axis_invert[i] == 0);
		unlink(path);
		profiles_free_all();
	}

	/* Case 2 — legacy keys only touch axes that are mapped to the
	 * matching scroll action. A non-scroll axis is never inverted by
	 * migration, even if the legacy flag is set. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"axis_mapping\": {\n"
				  "        \"tx\": \"zoom\", \"ty\": \"none\",\n"
				  "        \"tz\": \"none\", \"rx\": \"none\",\n"
				  "        \"ry\": \"none\", \"rz\": \"none\"\n"
				  "      },\n"
				  "      \"invert_scroll_x\": true\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		for (int i = 0; i < 6; i++)
			assert(p->cfg.axis_invert[i] == 0);
		unlink(path);
		profiles_free_all();
	}

	/* Case 3 — explicit axis_invert=true plus legacy invert_scroll_x:
	 * the new key wins (migration skips axes that already have a truthy
	 * entry). */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"axis_mapping\": {\n"
				  "        \"tx\": \"scroll_h\", \"ty\": \"none\",\n"
				  "        \"tz\": \"none\", \"rx\": \"none\",\n"
				  "        \"ry\": \"none\", \"rz\": \"none\"\n"
				  "      },\n"
				  "      \"axis_invert\": { \"tx\": true },\n"
				  "      \"invert_scroll_x\": true\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.axis_invert[0] == 1);
		unlink(path);
		profiles_free_all();
	}

	/* Case 4 — no legacy keys at all: axis_invert stays at the
	 * config_defaults() zero. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"axis_mapping\": {\n"
				  "        \"tx\": \"scroll_h\", \"ty\": \"scroll_v\",\n"
				  "        \"tz\": \"none\", \"rx\": \"none\",\n"
				  "        \"ry\": \"none\", \"rz\": \"none\"\n"
				  "      }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		for (int i = 0; i < 6; i++)
			assert(p->cfg.axis_invert[i] == 0);
		unlink(path);
		profiles_free_all();
	}

	/* Case 5 — axis_invert without legacy: explicit values are honored. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"axis_mapping\": {\n"
				  "        \"tx\": \"scroll_h\", \"ty\": \"none\",\n"
				  "        \"tz\": \"none\", \"rx\": \"none\",\n"
				  "        \"ry\": \"none\", \"rz\": \"none\"\n"
				  "      },\n"
				  "      \"axis_invert\": { \"tx\": true, \"rz\": true }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.axis_invert[0] == 1); /* tx */
		assert(p->cfg.axis_invert[5] == 1); /* rz */
		for (int i = 1; i < 5; i++)
			assert(p->cfg.axis_invert[i] == 0);
		unlink(path);
		profiles_free_all();
	}

	/* Case 6 — "key:Ctrl+Shift+S" combo: 2 modifiers + KEY_S. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": { \"0\": \"key:Ctrl+Shift+S\" }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.btn_map[0] == BTNACT_KEY);
		assert(p->cfg.btn_key[0].n_mods == 2);
		assert(p->cfg.btn_key[0].mods[0] == KEY_LEFTCTRL);
		assert(p->cfg.btn_key[0].mods[1] == KEY_LEFTSHIFT);
		assert(p->cfg.btn_key[0].key == KEY_S);
		unlink(path);
		profiles_free_all();
	}

	/* Case 7 — "key:F" plain key: zero modifiers, end key only. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": { \"0\": \"key:F\" }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.btn_map[0] == BTNACT_KEY);
		assert(p->cfg.btn_key[0].n_mods == 0);
		assert(p->cfg.btn_key[0].key == KEY_F);
		unlink(path);
		profiles_free_all();
	}

	/* Case 8 — unknown modifier name leaves the slot at NONE rather
	 * than half-binding. Same for unknown end key. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": {\n"
				  "        \"0\": \"key:WTF+S\",\n"
				  "        \"1\": \"key:Ctrl+NOTAKEY\"\n"
				  "      }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.btn_map[0] == BTNACT_NONE);
		assert(p->cfg.btn_map[1] == BTNACT_NONE);
		unlink(path);
		profiles_free_all();
	}

	/* Case 9 — object-form exec: argv round-trips, btn_map flips. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": {\n"
				  "        \"0\": { \"type\": \"exec\", "
				  "\"cmd\": [\"firefox\", \"--new-window\", \"https://x.com\"] }\n"
				  "      }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.btn_map[0] == BTNACT_EXEC);
		assert(p->cfg.btn_exec_argv[0] != NULL);
		assert(strcmp(p->cfg.btn_exec_argv[0][0], "firefox") == 0);
		assert(strcmp(p->cfg.btn_exec_argv[0][1], "--new-window") == 0);
		assert(strcmp(p->cfg.btn_exec_argv[0][2], "https://x.com") == 0);
		assert(p->cfg.btn_exec_argv[0][3] == NULL);
		unlink(path);
		profiles_free_all();
	}

	/* Case 10 — exec with empty cmd array leaves slot at NONE rather
	 * than registering an exec that would fork into nothing. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": {\n"
				  "        \"0\": { \"type\": \"exec\", \"cmd\": [] }\n"
				  "      }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.btn_map[0] == BTNACT_NONE);
		assert(p->cfg.btn_exec_argv[0] == NULL);
		unlink(path);
		profiles_free_all();
	}

	/* Case 11 — reload (config_load_all called twice) must not leak
	 * btn_exec_argv from the previous load. Hard to detect without
	 * valgrind, but the load-load-check-slot pattern still pins the
	 * second-load state correctly, which is what user-visible behaviour
	 * cares about. ASan in CI catches the leak. */
	{
		const char *cfg_with_exec =
			"{\n"
			"  \"profiles\": {\n"
			"    \"default\": {\n"
			"      \"button_mapping\": {\n"
			"        \"0\": { \"type\": \"exec\", \"cmd\": [\"true\"] }\n"
			"      }\n"
			"    }\n"
			"  }\n"
			"}\n";
		const char *cfg_no_exec = "{\n"
					  "  \"profiles\": {\n"
					  "    \"default\": {\n"
					  "      \"button_mapping\": { \"0\": \"none\" }\n"
					  "    }\n"
					  "  }\n"
					  "}\n";
		char path1[64];
		char path2[64];
		write_tmp_config(path1, cfg_with_exec);
		write_tmp_config(path2, cfg_no_exec);
		assert(config_load_all(path1) == 0);
		assert(find_profile("default")->cfg.btn_map[0] == BTNACT_EXEC);
		assert(config_load_all(path2) == 0);
		const struct profile *p = find_profile("default");
		assert(p->cfg.btn_map[0] == BTNACT_NONE);
		assert(p->cfg.btn_exec_argv[0] == NULL);
		unlink(path1);
		unlink(path2);
		profiles_free_all();
	}

	/* Case 12 — a derived profile that inherits an exec-bound button from
	 * default must own a *separate* argv copy, not alias default's. Before
	 * the deep-copy fix, parse_profile_obj's memcpy left both profiles
	 * pointing at the same heap block, so profiles_free_all double-freed
	 * it. The distinct-pointer assertion pins the fix deterministically;
	 * ASan in CI would also flag the double free on the free below. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": {\n"
				  "        \"0\": { \"type\": \"exec\", \"cmd\": [\"true\"] }\n"
				  "      }\n"
				  "    },\n"
				  "    \"app\": { \"match_wm_class\": [\"FreeCAD\"] }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *def = find_profile("default");
		const struct profile *app = find_profile("app");
		assert(def && app);
		/* Both bind button 0 to exec (app inherits it from default). */
		assert(def->cfg.btn_map[0] == BTNACT_EXEC);
		assert(app->cfg.btn_map[0] == BTNACT_EXEC);
		assert(def->cfg.btn_exec_argv[0] != NULL);
		assert(app->cfg.btn_exec_argv[0] != NULL);
		/* Same content ... */
		assert(strcmp(app->cfg.btn_exec_argv[0][0], "true") == 0);
		/* ... but distinct allocations (deep copy, not an alias). */
		assert(app->cfg.btn_exec_argv[0] != def->cfg.btn_exec_argv[0]);
		unlink(path);
		profiles_free_all();
	}

	/* Case 13 — a derived profile that *overrides* the inherited exec
	 * button (here to "none") must free only its own copy and leave
	 * default's argv intact. Before the fix, the override's btn_slot_reset
	 * freed the aliased block out from under default (use-after-free on the
	 * next press, double free on shutdown). */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": {\n"
				  "        \"0\": { \"type\": \"exec\", \"cmd\": [\"true\"] }\n"
				  "      }\n"
				  "    },\n"
				  "    \"app\": {\n"
				  "      \"button_mapping\": { \"0\": \"none\" },\n"
				  "      \"match_wm_class\": [\"FreeCAD\"]\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *def = find_profile("default");
		const struct profile *app = find_profile("app");
		assert(def && app);
		/* default keeps its exec binding + a valid argv ... */
		assert(def->cfg.btn_map[0] == BTNACT_EXEC);
		assert(def->cfg.btn_exec_argv[0] != NULL);
		assert(strcmp(def->cfg.btn_exec_argv[0][0], "true") == 0);
		/* ... while app dropped it to NONE with no owned argv. */
		assert(app->cfg.btn_map[0] == BTNACT_NONE);
		assert(app->cfg.btn_exec_argv[0] == NULL);
		unlink(path);
		profiles_free_all();
	}

	/* Case 14 — exec cmd containing a non-string element is rejected
	 * rather than coerced. {"cmd": [123, true]} must leave the slot at
	 * NONE instead of launching argv ["123", "true"]. */
	{
		const char *cfg = "{\n"
				  "  \"profiles\": {\n"
				  "    \"default\": {\n"
				  "      \"button_mapping\": {\n"
				  "        \"0\": { \"type\": \"exec\", \"cmd\": [123, true] }\n"
				  "      }\n"
				  "    }\n"
				  "  }\n"
				  "}\n";
		char path[64];
		write_tmp_config(path, cfg);
		assert(config_load_all(path) == 0);
		const struct profile *p = find_profile("default");
		assert(p);
		assert(p->cfg.btn_map[0] == BTNACT_NONE);
		assert(p->cfg.btn_exec_argv[0] == NULL);
		unlink(path);
		profiles_free_all();
	}

	printf("test_config_migration: all assertions passed\n");
	return 0;
}
