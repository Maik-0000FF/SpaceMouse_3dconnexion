/*
 * spacemouse-test - Diagnostic and live-monitor tool for SpaceMouse devices
 *
 * Modes:
 *   --check   Run all checks, report pass/fail, exit with 0 or 1
 *   --live    Show real-time axis values and button states
 *   --led     Toggle LED on/off test
 *
 * Build: make spacemouse-test
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <dirent.h>
#include <sys/stat.h>
#include <spnav.h>

#define COL_RESET  "\033[0m"
#define COL_GREEN  "\033[32m"
#define COL_RED    "\033[31m"
#define COL_YELLOW "\033[33m"
#define COL_BOLD   "\033[1m"
#define COL_CYAN   "\033[36m"

static volatile sig_atomic_t g_running = 1;

static void on_signal(int sig) { (void)sig; g_running = 0; }

/* ── USB device detection via sysfs ─────────────────────────────────── */

struct usb_match {
	const char *vendor;
	const char *product;
	const char *name;
};

static const struct usb_match known_devices[] = {
	{ "256f", "c635", "SpaceMouse Compact" },
	{ "256f", "c62e", "SpaceMouse Wireless (cabled)" },
	{ "256f", "c62f", "SpaceMouse Wireless Receiver" },
	{ "256f", "c631", "SpaceMouse Pro Wireless (cabled)" },
	{ "256f", "c632", "SpaceMouse Pro Wireless Receiver" },
	{ "256f", "c633", "SpaceMouse Enterprise" },
	{ "256f", "c641", "SpaceMouse Module" },
	{ "046d", "c603", "SpaceMouse Plus XT" },
	{ "046d", "c605", "SpaceMouse CADMan" },
	{ "046d", "c606", "SpaceMouse Classic" },
	{ "046d", "c621", "SpaceBall 5000" },
	{ "046d", "c623", "Space Traveller" },
	{ "046d", "c625", "SpacePilot Pro" },
	{ "046d", "c626", "SpaceNavigator" },
	{ "046d", "c627", "SpaceExplorer" },
	{ "046d", "c628", "SpaceNavigator for Notebooks" },
	{ "046d", "c629", "SpacePilot Pro" },
	{ "046d", "c62b", "SpaceMouse Pro" },
	{ NULL, NULL, NULL }
};

static int read_sysfs(const char *path, char *buf, int bufsz)
{
	FILE *f = fopen(path, "r");
	if (!f) return -1;
	if (!fgets(buf, bufsz, f)) {
		fclose(f);
		return -1;
	}
	fclose(f);
	/* strip newline */
	char *nl = strchr(buf, '\n');
	if (nl) *nl = '\0';
	return 0;
}

static int check_usb_device(void)
{
	DIR *dir = opendir("/sys/bus/usb/devices");
	if (!dir) {
		printf("  " COL_RED "[FAIL]" COL_RESET " Cannot read /sys/bus/usb/devices\n");
		return 0;
	}

	int found = 0;
	struct dirent *ent;
	while ((ent = readdir(dir)) != NULL) {
		if (ent->d_name[0] == '.') continue;

		char vpath[512], ppath[512];
		char vendor[16], product[16];

		snprintf(vpath, sizeof(vpath), "/sys/bus/usb/devices/%s/idVendor", ent->d_name);
		snprintf(ppath, sizeof(ppath), "/sys/bus/usb/devices/%s/idProduct", ent->d_name);

		if (read_sysfs(vpath, vendor, sizeof(vendor)) < 0) continue;
		if (read_sysfs(ppath, product, sizeof(product)) < 0) continue;

		for (const struct usb_match *m = known_devices; m->vendor; m++) {
			if (strcasecmp(vendor, m->vendor) == 0 &&
			    strcasecmp(product, m->product) == 0) {
				printf("  " COL_GREEN "[OK]" COL_RESET " USB device found: %s (%s:%s)\n",
					m->name, vendor, product);
				found = 1;
			}
		}
	}
	closedir(dir);

	if (!found)
		printf("  " COL_RED "[FAIL]" COL_RESET " No 3Dconnexion device found via USB\n");

	return found;
}

/* ── spacenavd daemon check ─────────────────────────────────────────── */

static int check_spacenavd(void)
{
	int ok = 1;

	/* Check if service is active via simple process check */
	FILE *f = popen("systemctl is-active spacenavd.service 2>/dev/null", "r");
	if (f) {
		char buf[64] = {0};
		if (fgets(buf, sizeof(buf), f)) {
			char *nl = strchr(buf, '\n');
			if (nl) *nl = '\0';
			if (strcmp(buf, "active") == 0) {
				printf("  " COL_GREEN "[OK]" COL_RESET " spacenavd.service is active\n");
			} else {
				printf("  " COL_RED "[FAIL]" COL_RESET " spacenavd.service is %s\n", buf);
				ok = 0;
			}
		}
		pclose(f);
	}

	/* Check socket */
	const char *sock_paths[] = {
		"/run/spnav.sock",
		"/var/run/spnav.sock",
		"/tmp/.spnav.sock",
		NULL
	};
	int sock_found = 0;
	for (const char **p = sock_paths; *p; p++) {
		struct stat st;
		if (stat(*p, &st) == 0 && (st.st_mode & S_IFSOCK)) {
			printf("  " COL_GREEN "[OK]" COL_RESET " Socket found: %s\n", *p);
			sock_found = 1;
			break;
		}
	}
	if (!sock_found) {
		printf("  " COL_YELLOW "[WARN]" COL_RESET " No spacenavd socket found\n");
		ok = 0;
	}

	return ok;
}

/* ── libspnav connection check ──────────────────────────────────────── */

static int check_connection(void)
{
	if (spnav_open() == -1) {
		printf("  " COL_RED "[FAIL]" COL_RESET " Cannot connect to spacenavd via libspnav\n");
		return 0;
	}

	printf("  " COL_GREEN "[OK]" COL_RESET " Connected to spacenavd (protocol v%d)\n",
		spnav_protocol());

	char devname[256] = {0};
	unsigned int vid = 0, pid = 0;
	int naxes, nbuttons;

	spnav_dev_name(devname, sizeof(devname));
	spnav_dev_usbid(&vid, &pid);
	naxes = spnav_dev_axes();
	nbuttons = spnav_dev_buttons();

	printf("  " COL_GREEN "[OK]" COL_RESET " Device: %s\n", devname);
	printf("  " COL_GREEN "[OK]" COL_RESET " USB ID: %04x:%04x\n", vid, pid);
	printf("  " COL_GREEN "[OK]" COL_RESET " Axes: %d, Buttons: %d\n", naxes, nbuttons);

	spnav_close();
	return 1;
}

/* ── Check mode ─────────────────────────────────────────────────────── */

static int mode_check(void)
{
	int errors = 0;

	printf(COL_BOLD "\n=== SpaceMouse Diagnostic Check ===" COL_RESET "\n\n");

	printf(COL_CYAN "1. USB Device Detection:" COL_RESET "\n");
	if (!check_usb_device()) errors++;

	printf(COL_CYAN "\n2. spacenavd Daemon:" COL_RESET "\n");
	if (!check_spacenavd()) errors++;

	printf(COL_CYAN "\n3. libspnav Connection:" COL_RESET "\n");
	if (!check_connection()) errors++;

	printf("\n" COL_BOLD "=== Result: ");
	if (errors == 0)
		printf(COL_GREEN "ALL CHECKS PASSED" COL_RESET COL_BOLD " ===" COL_RESET "\n\n");
	else
		printf(COL_RED "%d CHECK(S) FAILED" COL_RESET COL_BOLD " ===" COL_RESET "\n\n", errors);

	return errors == 0 ? 0 : 1;
}

/* ── Live mode ──────────────────────────────────────────────────────── */

static int mode_live(void)
{
	if (spnav_open() == -1) {
		fprintf(stderr, "Cannot connect to spacenavd. Is it running?\n");
		return 1;
	}

	char devname[256] = {0};
	spnav_dev_name(devname, sizeof(devname));

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	printf(COL_BOLD "\n=== %s - Live Event Monitor ===" COL_RESET "\n", devname);
	printf("Press Ctrl+C to exit\n\n");

	/* Hide cursor */
	printf("\033[?25l");

	int btn0 = 0, btn1 = 0;
	spnav_event ev;

	while (g_running) {
		int evtype = spnav_wait_event(&ev);
		if (!g_running) break;

		if (evtype == SPNAV_EVENT_MOTION) {
			/* Move cursor up 3 lines and redraw */
			printf("\033[3A\033[K");
			printf(COL_CYAN "TX:" COL_RESET " %+6d  "
			       COL_CYAN "TY:" COL_RESET " %+6d  "
			       COL_CYAN "TZ:" COL_RESET " %+6d\n",
				ev.motion.x, ev.motion.y, ev.motion.z);
			printf("\033[K");
			printf(COL_CYAN "RX:" COL_RESET " %+6d  "
			       COL_CYAN "RY:" COL_RESET " %+6d  "
			       COL_CYAN "RZ:" COL_RESET " %+6d\n",
				ev.motion.rx, ev.motion.ry, ev.motion.rz);
			printf("\033[K");

			/* Visual bar indicators */
			printf("Btn0: %s  Btn1: %s  Period: %ums\n",
				btn0 ? COL_GREEN "[X]" COL_RESET : "[ ]",
				btn1 ? COL_GREEN "[X]" COL_RESET : "[ ]",
				ev.motion.period);
			fflush(stdout);
		}
		else if (evtype == SPNAV_EVENT_BUTTON) {
			if (ev.button.bnum == 0) btn0 = ev.button.press;
			else if (ev.button.bnum == 1) btn1 = ev.button.press;
		}
	}

	/* Show cursor again */
	printf("\033[?25h\n");

	spnav_close();
	return 0;
}

/* ── LED test mode ──────────────────────────────────────────────────── */

static int mode_led(void)
{
	if (spnav_open() == -1) {
		fprintf(stderr, "Cannot connect to spacenavd. Is it running?\n");
		return 1;
	}

	printf("LED test: toggling LED...\n");

	printf("  LED OFF\n");
	spnav_cfg_set_led(SPNAV_CFG_LED_OFF);
	sleep(1);

	printf("  LED ON\n");
	spnav_cfg_set_led(SPNAV_CFG_LED_ON);
	sleep(1);

	printf("  LED AUTO (default)\n");
	spnav_cfg_set_led(SPNAV_CFG_LED_AUTO);

	printf("LED test done.\n");
	spnav_close();
	return 0;
}

/* ── Main ───────────────────────────────────────────────────────────── */

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "Usage: %s --check | --live | --led\n", argv[0]);
		fprintf(stderr, "  --check  Run diagnostic checks\n");
		fprintf(stderr, "  --live   Live event monitor\n");
		fprintf(stderr, "  --led    LED toggle test\n");
		return 1;
	}

	/* Need initial lines for live mode cursor movement */
	if (strcmp(argv[1], "--live") == 0) {
		printf("\n\n\n");
		return mode_live();
	}

	if (strcmp(argv[1], "--check") == 0)
		return mode_check();
	if (strcmp(argv[1], "--led") == 0)
		return mode_led();

	fprintf(stderr, "Unknown option: %s\n", argv[1]);
	return 1;
}
