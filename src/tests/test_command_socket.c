/* Tests for cmd_handle_client() — protocol parsing boundary cases.
 *
 * The command socket is the trust boundary between the GUI and the
 * daemon: profile names traverse it as plain text and drive runtime
 * behaviour. Boundary inputs (empty name, missing newline, oversized
 * payload, unknown profile, unknown command) must all hit the well-
 * defined error branches without reading past the buffer or crashing.
 */

#define _GNU_SOURCE
#include "command_socket.h"
#include "config.h"

#include <assert.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

/* Provided by spacemouse-desktop.c in production builds; stubbed here so
 * the test binary can link without dragging in the whole daemon. */
volatile sig_atomic_t g_reload = 0;

/* Bind a fresh listening socket at an abstract address, spawn a client
 * connection, send `request`, run cmd_handle_client() on the listener,
 * and return the server's response in `response_out` (NUL-terminated).
 * `request_len` lets the caller send payloads that contain NULs. */
static void roundtrip(const char *request, size_t request_len, char *response_out,
		      size_t response_out_size)
{
	int listen_fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0);
	assert(listen_fd >= 0);

	struct sockaddr_un addr;
	memset(&addr, 0, sizeof(addr));
	addr.sun_family = AF_UNIX;
	/* Linux-abstract socket: path starts with NUL, no filesystem entry. */
	snprintf(addr.sun_path + 1, sizeof(addr.sun_path) - 1, "spm-cmd-test-%d", getpid());
	socklen_t addrlen = (socklen_t)(sizeof(sa_family_t) + 1 + strlen(addr.sun_path + 1));

	assert(bind(listen_fd, (struct sockaddr *)&addr, addrlen) == 0);
	assert(listen(listen_fd, 1) == 0);

	int client_fd = socket(AF_UNIX, SOCK_STREAM, 0);
	assert(client_fd >= 0);
	assert(connect(client_fd, (struct sockaddr *)&addr, addrlen) == 0);

	ssize_t w = write(client_fd, request, request_len);
	assert(w == (ssize_t)request_len);

	cmd_handle_client(listen_fd);

	ssize_t n = read(client_fd, response_out, response_out_size - 1);
	assert(n >= 0);
	response_out[n] = '\0';

	close(client_fd);
	close(listen_fd);
}

/* Install two profiles directly into the daemon's global table — easier
 * than driving config_load_all() through a temp file, and the only thing
 * cmd_handle_client cares about is g_profiles/g_profile_count. */
static void install_test_profiles(void)
{
	memset(g_profiles, 0, sizeof(g_profiles));
	snprintf(g_profiles[0].name, sizeof(g_profiles[0].name), "default");
	snprintf(g_profiles[1].name, sizeof(g_profiles[1].name), "blender");
	g_profile_count = 2;
	g_active_profile = 0;
}

int main(void)
{
	char resp[CMD_BUF_SIZE];

	install_test_profiles();

	/* Valid PROFILE switches the active profile and echoes its name. */
	roundtrip("PROFILE blender\n", strlen("PROFILE blender\n"), resp, sizeof(resp));
	assert(strncmp(resp, "OK blender", 10) == 0);
	assert(g_active_profile == 1);

	/* Case-insensitive name match: PROFILE DEFAULT must hit "default". */
	roundtrip("PROFILE DEFAULT\n", strlen("PROFILE DEFAULT\n"), resp, sizeof(resp));
	assert(strncmp(resp, "OK default", 10) == 0);
	assert(g_active_profile == 0);

	/* Unknown profile name → ERR response, no profile change. */
	g_active_profile = 0;
	roundtrip("PROFILE nope\n", strlen("PROFILE nope\n"), resp, sizeof(resp));
	assert(strncmp(resp, "ERR unknown profile", 19) == 0);
	assert(g_active_profile == 0);

	/* Empty profile name (PROFILE followed by nothing) → ERR, no change. */
	roundtrip("PROFILE \n", strlen("PROFILE \n"), resp, sizeof(resp));
	assert(strncmp(resp, "ERR unknown profile", 19) == 0);
	assert(g_active_profile == 0);

	/* Missing trailing newline must not break parsing — the daemon strips
	 * \n/\r off the end but tolerates absence. */
	roundtrip("PROFILE blender", strlen("PROFILE blender"), resp, sizeof(resp));
	assert(strncmp(resp, "OK blender", 10) == 0);

	/* Oversized request: send more bytes than the daemon's read buffer.
	 * The daemon caps read() at CMD_BUF_SIZE-1, so the tail past that is
	 * silently dropped. The exact response depends on where the truncation
	 * lands inside the payload — what matters is that the response is a
	 * well-formed protocol string and the daemon does not overrun the
	 * buffer. We accept either "OK" or "ERR" prefix and require a newline
	 * terminator. */
	char big[CMD_BUF_SIZE * 2];
	memset(big, 'x', sizeof(big));
	memcpy(big, "PROFILE ", 8);
	roundtrip(big, sizeof(big), resp, sizeof(resp));
	assert(strncmp(resp, "OK ", 3) == 0 || strncmp(resp, "ERR ", 4) == 0);
	assert(strchr(resp, '\n') != NULL);

	/* A junk command of the same oversized shape must also be handled
	 * gracefully. Daemon strips the trailing run of 'x' as a single
	 * unknown command rather than dispatching anything. */
	memset(big, 'x', sizeof(big));
	roundtrip(big, sizeof(big), resp, sizeof(resp));
	assert(strncmp(resp, "ERR unknown command", 19) == 0);

	/* RELOAD sets the global flag and acknowledges. */
	g_reload = 0;
	roundtrip("RELOAD\n", strlen("RELOAD\n"), resp, sizeof(resp));
	assert(strncmp(resp, "OK reloading", 12) == 0);
	assert(g_reload == 1);

	/* STATUS lists every loaded profile. */
	roundtrip("STATUS\n", strlen("STATUS\n"), resp, sizeof(resp));
	assert(strstr(resp, "ACTIVE ") != NULL);
	assert(strstr(resp, "PROFILES") != NULL);
	assert(strstr(resp, "default") != NULL);
	assert(strstr(resp, "blender") != NULL);

	/* Unknown command → generic error, no state change. */
	roundtrip("WHATEVER\n", strlen("WHATEVER\n"), resp, sizeof(resp));
	assert(strncmp(resp, "ERR unknown command", 19) == 0);

	printf("test_command_socket: all assertions passed\n");
	return 0;
}
