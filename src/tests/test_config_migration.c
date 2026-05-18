/* Tests for the legacy invert_scroll_x/y → axis_invert[6] migration in
 * config.c.
 *
 * Pre-PR-#8 configs used the global "invert_scroll_x" / "invert_scroll_y"
 * keys. The new format stores invert state per axis. The loader migrates
 * legacy keys onto whichever axes are mapped to scroll_h / scroll_v at
 * the time of the load. Explicit per-axis entries take precedence. */

#include "config.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

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

	printf("test_config_migration: all assertions passed\n");
	return 0;
}
