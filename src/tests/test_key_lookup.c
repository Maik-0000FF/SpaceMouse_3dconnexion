/* Tests for lookup_key() and the KEY_NAMES table. */

#include "spacemouse-core.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <linux/input.h>

int main(void)
{
	/* Known names resolve to their kernel keycodes. */
	assert(lookup_key("SPACE") == KEY_SPACE);
	assert(lookup_key("ENTER") == KEY_ENTER);
	assert(lookup_key("PAGEUP") == KEY_PAGEUP);
	assert(lookup_key("PAGEDOWN") == KEY_PAGEDOWN);
	assert(lookup_key("A") == KEY_A);
	assert(lookup_key("Z") == KEY_Z);
	assert(lookup_key("F1") == KEY_F1);
	assert(lookup_key("F12") == KEY_F12);

	/* Case-insensitive — config files use lowercase too. */
	assert(lookup_key("space") == KEY_SPACE);
	assert(lookup_key("Page_Down") == 0); /* underscore is not part of any name */
	assert(lookup_key("pagedown") == KEY_PAGEDOWN);
	assert(lookup_key("f5") == KEY_F5);

	/* NULL and unknown names return 0 — caller treats 0 as "no key". */
	assert(lookup_key(NULL) == 0);
	assert(lookup_key("") == 0);
	assert(lookup_key("NOPE") == 0);
	assert(lookup_key("F99") == 0);

	/* Table is sentinel-terminated; walking it must not crash. */
	int count = 0;
	for (const struct key_name_entry *e = KEY_NAMES; e->name; e++) {
		assert(strlen(e->name) > 0);
		assert(e->code > 0);
		count++;
	}
	/* Sanity floor — alphabet (26) + 12 F-keys + named keys. */
	assert(count >= 50);

	printf("test_key_lookup: all assertions passed (%d entries)\n", count);
	return 0;
}
