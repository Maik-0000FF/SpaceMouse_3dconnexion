/*
 * command_socket - UNIX domain socket for runtime daemon control.
 *
 * The GUI sends one-line text commands over /run/user/<UID>/spacemouse-cmd.sock
 * to switch profiles, reload config and query status. Protocol:
 *
 *   PROFILE <name>   → "OK <name>\n" or "ERR unknown profile '<name>'\n"
 *   RELOAD           → "OK reloading\n" (sets g_reload, main loop picks up)
 *   STATUS           → "ACTIVE <name>\nPROFILES <n1> <n2> …\n"
 *   DEVICE           → "OK vid=XXXX pid=XXXX buttons=N known=0|1 name=<str>\n"
 *                       or "NONE\n" when no device is currently open
 *
 * Connections are accept()ed one at a time from the daemon's main poll
 * loop; the socket is non-blocking so a stuck client cannot stall the
 * event loop.
 */
#ifndef SPACEMOUSE_COMMAND_SOCKET_H
#define SPACEMOUSE_COMMAND_SOCKET_H

#include <signal.h>

#define CMD_BUF_SIZE 256
#define SOCK_BACKLOG 4

/* Set by the RELOAD handler. Defined in spacemouse-desktop.c. */
extern volatile sig_atomic_t g_reload;

/* Bind, listen and chmod a non-blocking AF_UNIX SOCK_STREAM socket at
 * `path`. Returns the listening fd, or -1 on error. */
int cmd_sock_open(const char *path);

/* Close `fd` and unlink `path` (both safe on -1 / empty). */
void cmd_sock_close(int fd, const char *path);

/* Accept one client connection on `listen_fd`, parse one command line,
 * write the response and close. Errors are logged and swallowed. */
void cmd_handle_client(int listen_fd);

#endif /* SPACEMOUSE_COMMAND_SOCKET_H */
