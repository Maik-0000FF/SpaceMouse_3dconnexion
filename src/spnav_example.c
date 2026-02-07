/*
 * spnav_example.c - libspnav client example for custom applications
 *
 * Demonstrates:
 * - Connecting to spacenavd via UNIX socket
 * - Reading motion events (6DOF translation + rotation)
 * - Reading button events
 * - Querying device information
 * - Proper cleanup on exit
 *
 * Build: make spnav_example
 * Run:   ./spnav_example
 */

#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <spnav.h>

static volatile sig_atomic_t running = 1;

static void sig_handler(int sig)
{
	(void)sig;
	running = 0;
}

int main(void)
{
	spnav_event ev;
	char devname[256];
	unsigned int vid, pid;

	signal(SIGINT, sig_handler);
	signal(SIGTERM, sig_handler);

	/* Connect to spacenavd via UNIX socket */
	if (spnav_open() == -1) {
		fprintf(stderr, "Failed to connect to spacenavd.\n");
		fprintf(stderr, "Is spacenavd running? Check: systemctl status spacenavd\n");
		return 1;
	}

	/* Set client name (visible in spacenavd logs) */
	spnav_client_name("spnav_example");

	/* Query and display device info */
	spnav_dev_name(devname, sizeof(devname));
	spnav_dev_usbid(&vid, &pid);

	printf("Device:   %s\n", devname);
	printf("USB ID:   %04x:%04x\n", vid, pid);
	printf("Axes:     %d\n", spnav_dev_axes());
	printf("Buttons:  %d\n", spnav_dev_buttons());
	printf("Protocol: %d\n", spnav_protocol());
	printf("\nWaiting for events (Ctrl+C to quit)...\n\n");

	/* Set client-specific sensitivity (does not affect other clients) */
	spnav_sensitivity(1.0);

	/* Main event loop - spnav_wait_event blocks until an event arrives */
	while (running) {
		int evtype = spnav_wait_event(&ev);
		if (!running) break;

		switch (evtype) {
		case SPNAV_EVENT_MOTION:
			printf("\rT(%+6d %+6d %+6d) R(%+6d %+6d %+6d) dt=%ums   ",
				ev.motion.x, ev.motion.y, ev.motion.z,
				ev.motion.rx, ev.motion.ry, ev.motion.rz,
				ev.motion.period);
			fflush(stdout);
			break;

		case SPNAV_EVENT_BUTTON:
			printf("\nButton %d %s\n",
				ev.button.bnum,
				ev.button.press ? "pressed" : "released");
			break;

		default:
			break;
		}
	}

	printf("\nDone.\n");
	spnav_close();
	return 0;
}
