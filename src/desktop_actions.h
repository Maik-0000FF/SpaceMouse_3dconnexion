/*
 * desktop_actions - DE-aware dispatch for workspace switch, overview
 * and show-desktop.
 *
 * KDE → KWin D-Bus (atomic, exact, real toggle).
 * Sway/Hyprland → IPC CLIs via spawn_command.
 * Everything else → uinput key combos with DE-typical defaults.
 *
 * The active backend is selected by g_de (set at startup by main).
 */
#ifndef SPACEMOUSE_DESKTOP_ACTIONS_H
#define SPACEMOUSE_DESKTOP_ACTIONS_H

#include "spacemouse-core.h"

/* Selected once at startup, drives every dispatch in this file. */
extern enum desktop_env g_de;

/* uinput fd used by the key-tap backends. Owned by main, set via
 * desktop_actions_set_uinput before any dispatch call. -1 disables
 * the key-emitting backends; D-Bus / IPC paths still work. */
void desktop_actions_set_uinput(int fd);

/* direction > 0 → next workspace, < 0 → previous. */
void desktop_action_workspace(int direction);

/* Open the overview / Activities equivalent. */
void desktop_action_overview(void);

/* Show desktop. *state is the daemon-tracked toggle for KDE; on every
 * other DE the call is a stateless keybind tap and *state is unused. */
void desktop_action_show_desktop(int *state);

#endif /* SPACEMOUSE_DESKTOP_ACTIONS_H */
