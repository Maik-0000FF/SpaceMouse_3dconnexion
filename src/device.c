/*
 * device - implementation. See device.h.
 */
#define _GNU_SOURCE
#include "device.h"

#include <stddef.h>
#include <string.h>
#include <sys/ioctl.h>

#include <linux/input.h>

/* PID → name + button count. Logitech-era VID 0x046d and 3Dconnexion-
 * era VID 0x256f. Mirrors the udev allow-list in config/99-spacemouse.rules.
 * Button counts come from public 3Dconnexion product pages and the
 * spacenavd HID device table; zero means unknown (use discovery). */
static const struct {
	const char *name;
	uint16_t vid;
	uint16_t pid;
	int button_count;
} g_device_table[] = {
	/* ── Logitech-era VID 046d ── */
	{"3Dconnexion CADman", 0x046d, 0xc603, 0},
	{"3Dconnexion 3D Mouse", 0x046d, 0xc605, 0},
	{"3Dconnexion SpaceMouse Classic", 0x046d, 0xc606, 9},
	{"3Dconnexion SpaceBall 5000", 0x046d, 0xc621, 12},
	{"3Dconnexion SpaceTraveler", 0x046d, 0xc623, 8},
	{"3Dconnexion SpacePilot", 0x046d, 0xc625, 21},
	{"3Dconnexion SpaceNavigator", 0x046d, 0xc626, 2},
	{"3Dconnexion SpaceExplorer", 0x046d, 0xc627, 15},
	{"3Dconnexion SpaceNavigator for Notebooks", 0x046d, 0xc628, 2},
	{"3Dconnexion SpacePilot Pro", 0x046d, 0xc629, 31},
	{"3Dconnexion SpaceMouse Pro", 0x046d, 0xc62b, 15},

	/* ── 3Dconnexion VID 256f ── */
	{"3Dconnexion SpaceMouse Wireless (cabled)", 0x256f, 0xc62e, 2},
	{"3Dconnexion SpaceMouse Wireless Receiver", 0x256f, 0xc62f, 2},
	{"3Dconnexion SpaceMouse Pro Wireless (cabled)", 0x256f, 0xc631, 15},
	{"3Dconnexion SpaceMouse Pro Wireless Receiver", 0x256f, 0xc632, 15},
	{"3Dconnexion SpaceMouse Enterprise", 0x256f, 0xc633, 31},
	{"3Dconnexion SpaceMouse Compact", 0x256f, 0xc635, 2},
	{"3Dconnexion SpaceMouse Module", 0x256f, 0xc636, 0},
	{"3Dconnexion SpaceMouse Wireless (Bluetooth)", 0x256f, 0xc63a, 2},
	{"3Dconnexion Universal Receiver", 0x256f, 0xc652, 0},
};

static struct device_info g_cached = {0};

static const char *lookup_name(uint16_t vid, uint16_t pid, int *button_count_out)
{
	size_t n = sizeof(g_device_table) / sizeof(g_device_table[0]);
	for (size_t i = 0; i < n; i++) {
		if (g_device_table[i].vid == vid && g_device_table[i].pid == pid) {
			if (button_count_out)
				*button_count_out = g_device_table[i].button_count;
			return g_device_table[i].name;
		}
	}
	if (button_count_out)
		*button_count_out = 0;
	return NULL;
}

int device_detect_from_fd(int fd, struct device_info *out)
{
	if (!out)
		return -1;
	memset(out, 0, sizeof(*out));

	struct input_id id;
	if (ioctl(fd, EVIOCGID, &id) < 0)
		return -1;
	out->vid = id.vendor;
	out->pid = id.product;

	char name[128] = {0};
	if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) < 0) {
		/* product/name lookups are tolerant — empty is fine */
		name[0] = '\0';
	}
	/* Strip the kernel's trailing duplicates if any (rare; defensive). */
	size_t nlen = strnlen(name, sizeof(out->product) - 1);
	memcpy(out->product, name, nlen);
	out->product[nlen] = '\0';

	int bcount = 0;
	const char *curated = lookup_name(out->vid, out->pid, &bcount);
	const char *src;
	if (curated) {
		out->known = 1;
		out->button_count = bcount;
		src = curated;
	} else {
		out->known = 0;
		out->button_count = 0;
		src = out->product[0] ? out->product : "Unknown SpaceMouse";
	}
	size_t dlen = strnlen(src, sizeof(out->display_name) - 1);
	memcpy(out->display_name, src, dlen);
	out->display_name[dlen] = '\0';

	memcpy(&g_cached, out, sizeof(g_cached));
	return 0;
}

void device_get_cached(struct device_info *out)
{
	if (out)
		memcpy(out, &g_cached, sizeof(*out));
}

void device_clear_cache(void)
{
	memset(&g_cached, 0, sizeof(g_cached));
}
