/*
 * command_socket - implementation. See command_socket.h for the wire
 * protocol and ownership rules.
 */
#define _GNU_SOURCE
#include "command_socket.h"

#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>

#include "config.h"
#include "device.h"

int cmd_sock_open(const char *path)
{
	unlink(path);

	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0);
	if (fd < 0) {
		perror("spacemouse-desktop: socket");
		return -1;
	}

	struct sockaddr_un addr;
	memset(&addr, 0, sizeof(addr));
	addr.sun_family = AF_UNIX;
	size_t plen = strlen(path);
	if (plen >= sizeof(addr.sun_path)) {
		fprintf(stderr, "spacemouse-desktop: socket path too long: %s\n", path);
		close(fd);
		return -1;
	}
	memcpy(addr.sun_path, path, plen + 1);

	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		perror("spacemouse-desktop: bind");
		close(fd);
		return -1;
	}
	chmod(path, 0600);

	if (listen(fd, SOCK_BACKLOG) < 0) {
		perror("spacemouse-desktop: listen");
		close(fd);
		return -1;
	}

	return fd;
}

void cmd_sock_close(int fd, const char *path)
{
	if (fd >= 0)
		close(fd);
	if (path[0])
		unlink(path);
}

void cmd_handle_client(int listen_fd)
{
	int cfd = accept(listen_fd, NULL, NULL);
	if (cfd < 0)
		return;

	char buf[CMD_BUF_SIZE] = {0};
	ssize_t n = read(cfd, buf, sizeof(buf) - 1);
	if (n <= 0) {
		close(cfd);
		return;
	}

	/* Strip trailing newline */
	while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r'))
		buf[--n] = '\0';

	char response[CMD_BUF_SIZE] = {0};

	if (strncmp(buf, "PROFILE ", 8) == 0) {
		const char *name = buf + 8;
		/* buf is zero-initialised and `read()` is capped at CMD_BUF_SIZE-1,
		 * so the final byte is always NUL — but bound the lookup explicitly
		 * so a future refactor that drops either invariant cannot turn
		 * strcasecmp into an out-of-bounds read. An empty name falls
		 * through to the "unknown profile" branch as intended.
		 */
		size_t name_len = strnlen(name, CMD_BUF_SIZE - 8);
		int found = -1;
		if (name_len > 0) {
			for (int i = 0; i < g_profile_count; i++) {
				if (strcasecmp(g_profiles[i].name, name) == 0) {
					found = i;
					break;
				}
			}
		}
		if (found >= 0) {
			g_active_profile = found;
			snprintf(response, sizeof(response), "OK %s\n", g_profiles[found].name);
			fprintf(stderr, "spacemouse-desktop: switched to profile '%s'\n",
				g_profiles[found].name);
		} else {
			snprintf(response, sizeof(response), "ERR unknown profile '%.200s'\n",
				 name);
		}
	} else if (strcmp(buf, "RELOAD") == 0) {
		g_reload = 1;
		snprintf(response, sizeof(response), "OK reloading\n");
	} else if (strcmp(buf, "DEVICE") == 0) {
		struct device_info info;
		device_get_cached(&info);
		if (info.vid == 0 && info.pid == 0) {
			snprintf(response, sizeof(response), "NONE\n");
		} else {
			snprintf(response, sizeof(response),
				 "OK vid=%04x pid=%04x buttons=%d known=%d name=%s\n",
				 info.vid, info.pid, info.button_count, info.known,
				 info.display_name);
		}
	} else if (strcmp(buf, "STATUS") == 0) {
		snprintf(response, sizeof(response), "ACTIVE %s\nPROFILES",
			 g_profiles[g_active_profile].name);
		for (int i = 0; i < g_profile_count; i++) {
			int rem = sizeof(response) - strlen(response) - 1;
			if (rem < 2)
				break;
			strncat(response, " ", rem);
			strncat(response, g_profiles[i].name, rem - 1);
		}
		strncat(response, "\n", sizeof(response) - strlen(response) - 1);
	} else {
		snprintf(response, sizeof(response), "ERR unknown command\n");
	}

	write(cfd, response, strlen(response));
	close(cfd);
}
