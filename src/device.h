/*
 * device - 3Dconnexion device identification.
 *
 * Reads VID/PID + kernel product string from an open evdev fd, looks
 * the PID up in a curated table and exposes the result via a thread-
 * unsafe-but-single-writer global. The PID table mirrors the udev
 * rules under config/99-spacemouse.rules — both are kept in sync by
 * hand and reflect the same vetted device list.
 *
 * The button_count is sourced from public docs and spacenavd's HID
 * device table. A zero count means "unknown" — the GUI falls back to
 * press-to-discover instead of pre-seeding rows. Universal Receiver
 * (256f:c652) and SpaceMouse Module (256f:c636) are intentionally
 * zero: they can proxy any 3Dconnexion puck, so the count depends on
 * what is actually paired, which we cannot tell from the receiver's
 * own descriptor.
 */
#ifndef SPACEMOUSE_DEVICE_H
#define SPACEMOUSE_DEVICE_H

#include <stdint.h>

struct device_info {
	uint16_t vid;
	uint16_t pid;
	char product[128];      /* EVIOCGNAME — raw kernel string */
	char display_name[64];  /* Curated name from table, or product if unknown */
	int button_count;       /* 0 = unknown, falls back to discovery */
	int known;              /* 1 if VID/PID matched the table, 0 otherwise */
};

/* Probe `fd` (an open /dev/input/eventN for a 3Dconnexion puck) via
 * EVIOCGID + EVIOCGNAME, fill *out and cache it globally. Returns 0
 * on success or -1 if either ioctl fails — *out is still zeroed. */
int device_detect_from_fd(int fd, struct device_info *out);

/* Read the most recently cached info (set by device_detect_from_fd
 * or zeroed by device_clear_cache). Safe to call any time. */
void device_get_cached(struct device_info *out);

/* Clear the cached info (call on disconnect so STATUS does not lie
 * about a device that is no longer plugged in). */
void device_clear_cache(void);

#endif /* SPACEMOUSE_DEVICE_H */
