/*
 * dbus_actions - implementation. See dbus_actions.h.
 */
#define _GNU_SOURCE
#include "dbus_actions.h"

#include <stdio.h>

#include <dbus/dbus.h>

static DBusConnection *g_dbus = NULL;

static DBusConnection *dbus_connect(void)
{
	DBusError err;
	dbus_error_init(&err);
	DBusConnection *conn = dbus_bus_get(DBUS_BUS_SESSION, &err);
	if (dbus_error_is_set(&err)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus error: %s\n", err.message);
		dbus_error_free(&err);
		return NULL;
	}
	dbus_connection_set_exit_on_disconnect(conn, FALSE);
	return conn;
}

void dbus_actions_init(void)
{
	if (!g_dbus)
		g_dbus = dbus_connect();
}

void dbus_actions_close(void)
{
	if (g_dbus) {
		dbus_connection_unref(g_dbus);
		g_dbus = NULL;
	}
}

void dbus_actions_ensure_connected(void)
{
	if (g_dbus && dbus_connection_get_is_connected(g_dbus))
		return;
	if (g_dbus) {
		dbus_connection_unref(g_dbus);
		g_dbus = NULL;
	}
	g_dbus = dbus_connect();
	if (g_dbus)
		fprintf(stderr, "spacemouse-desktop: D-Bus reconnected\n");
	else
		fprintf(stderr, "spacemouse-desktop: D-Bus reconnect failed\n");
}

int dbus_actions_is_connected(void)
{
	return g_dbus && dbus_connection_get_is_connected(g_dbus);
}

void dbus_kwin_call(const char *method)
{
	if (!dbus_actions_is_connected())
		return;
	DBusMessage *msg =
		dbus_message_new_method_call("org.kde.KWin", "/KWin", "org.kde.KWin", method);
	if (!msg)
		return;
	dbus_message_set_no_reply(msg, TRUE);
	if (!dbus_connection_send(g_dbus, msg, NULL)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus send failed: %s\n", method);
		dbus_message_unref(msg);
		return;
	}
	dbus_connection_flush(g_dbus);
	dbus_message_unref(msg);
}

void dbus_kglobalaccel_call(const char *shortcut)
{
	if (!dbus_actions_is_connected())
		return;
	DBusMessage *msg =
		dbus_message_new_method_call("org.kde.kglobalaccel", "/component/kwin",
					     "org.kde.kglobalaccel.Component", "invokeShortcut");
	if (!msg)
		return;
	dbus_message_append_args(msg, DBUS_TYPE_STRING, &shortcut, DBUS_TYPE_INVALID);
	dbus_message_set_no_reply(msg, TRUE);
	if (!dbus_connection_send(g_dbus, msg, NULL)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus send failed: %s\n", shortcut);
		dbus_message_unref(msg);
		return;
	}
	dbus_connection_flush(g_dbus);
	dbus_message_unref(msg);
}

void dbus_kwin_show_desktop(int active)
{
	if (!dbus_actions_is_connected())
		return;
	DBusMessage *msg = dbus_message_new_method_call("org.kde.KWin", "/KWin", "org.kde.KWin",
							"showDesktop");
	if (!msg)
		return;
	dbus_bool_t v = active ? TRUE : FALSE;
	dbus_message_append_args(msg, DBUS_TYPE_BOOLEAN, &v, DBUS_TYPE_INVALID);
	if (!dbus_connection_send(g_dbus, msg, NULL)) {
		fprintf(stderr, "spacemouse-desktop: D-Bus send failed: showDesktop\n");
		dbus_message_unref(msg);
		return;
	}
	dbus_connection_flush(g_dbus);
	dbus_message_unref(msg);
}

void dbus_actions_pump(void)
{
	if (!dbus_actions_is_connected())
		return;
	while (dbus_connection_dispatch(g_dbus) == DBUS_DISPATCH_DATA_REMAINS)
		;
}
