/*
 * uinput - Virtual input device for emitting scroll wheel, modifier
 *          chords and discrete keys.
 *
 * The daemon owns one virtual device for the lifetime of the process.
 * Open it once at startup, pass the returned fd to every emit_*
 * function, close at shutdown.
 *
 * spawn_command lives here too because it is the same kind of "ask the
 * desktop to do something" effect — used for swaymsg/hyprctl when
 * uinput keys would be wrong (Wayland tilers route their own IPC).
 */
#ifndef SPACEMOUSE_UINPUT_H
#define SPACEMOUSE_UINPUT_H

/* Open and configure /dev/uinput as a virtual scroll/key emulator.
 * Registers REL_WHEEL family + every key in KEY_NAMES plus the
 * modifiers used by emit_key_combo. Returns fd or -1. */
int uinput_open(void);

/* Destroy the device and close its fd. */
void uinput_close(int fd);

/* Emit an evdev event of (type, code, val) plus a SYN_REPORT terminator
 * is the caller's responsibility — emit_event is the low-level helper.
 * Most callers prefer the higher-level emit_* helpers below. */
void emit_event(int fd, int type, int code, int val);

/* Horizontal/vertical wheel scroll. dx = HWHEEL, dy = WHEEL. Both also
 * emit the high-resolution variant (REL_*_HI_RES at 120-tick scale). */
void emit_scroll(int fd, int dx, int dy);

/* Tap a single key (down → up + SYN), no hold. Used for media keys
 * and other non-modal taps where timing doesn't matter. */
void emit_key_tap(int fd, int code);

/* Press n_mods modifiers, tap key, release modifiers. n_mods may be 0
 * (degenerates to a single held key tap). One-shot: drops modifiers
 * before returning, so nothing stays held between button presses. */
void emit_key_combo(int fd, const int *mods, int n_mods, int key);

/* Ctrl+wheel scroll, used by browsers/3D apps to mean "zoom". */
void emit_zoom(int fd, int dz);

/* Fork+exec a subprocess fire-and-forget. SIGCHLD must be set to
 * SIG_IGN at startup so the kernel auto-reaps. */
void spawn_command(char *const argv[]);

#endif /* SPACEMOUSE_UINPUT_H */
