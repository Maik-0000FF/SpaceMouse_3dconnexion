/*
 * dbus_actions - KDE-specific D-Bus calls (KWin + KGlobalAccel).
 *
 * Owns the session-bus connection and reconnects transparently when
 * the bus drops. All public functions are no-ops when disconnected, so
 * callers don't have to guard each call.
 */
#ifndef SPACEMOUSE_DBUS_ACTIONS_H
#define SPACEMOUSE_DBUS_ACTIONS_H

/* Connect to the session bus. Subsequent calls are idempotent. */
void dbus_actions_init(void);

/* Disconnect and free the connection (called at shutdown). */
void dbus_actions_close(void);

/* Reconnect if the bus dropped. Cheap to call before each batch of
 * calls — it short-circuits when already connected. */
void dbus_actions_ensure_connected(void);

/* True if there is an active session-bus connection. */
int dbus_actions_is_connected(void);

/* Fire-and-forget call to org.kde.KWin.<method> on /KWin.
 * No-op if disconnected. */
void dbus_kwin_call(const char *method);

/* Fire-and-forget call to org.kde.kglobalaccel.Component.invokeShortcut
 * on /component/kwin. No-op if disconnected. */
void dbus_kglobalaccel_call(const char *shortcut);

/* Set KWin's show-desktop state (true = show desktop, false = restore).
 * KWin is the only DE we drive this way; everywhere else we tap a
 * keybind and let the DE manage state. */
void dbus_kwin_show_desktop(int active);

/* Drain pending incoming messages from the bus. Called from the main
 * poll loop's idle tick. No-op if disconnected. */
void dbus_actions_pump(void);

#endif /* SPACEMOUSE_DBUS_ACTIONS_H */
