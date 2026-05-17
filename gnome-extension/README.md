# SpaceMouse Focus Bridge

Minimal GNOME Shell extension that publishes the focused window's `wm_class` on the session bus. The SpaceMouse Control GUI subscribes to that signal and switches the daemon profile when Blender or FreeCAD gains focus. Independent from the rest of this project — only needed on GNOME-Wayland.

## Why this exists

KDE Plasma exposes window activation via KWin scripts and D-Bus; X11 desktops expose `_NET_ACTIVE_WINDOW` through xprop; Sway and Hyprland have native socket APIs. GNOME-Wayland has none of that, and `org.gnome.Shell.Eval` — the historical workaround — has been policy-disabled since GNOME 41. The only portable way to read focus events out of GNOME-Wayland is a Shell extension.

Polling-based extensions (like the third-party Window Calls) work but force Mutter to serialise the full window list on the compositor thread on every poll tick — Blender visibly stutters during navigation. This extension goes push-based instead: it subscribes to Mutter's `notify::focus-window` on `global.display`, emits a D-Bus signal on change, and adds zero compositor load between focus changes.

## Layout

```
gnome-extension/
└── spacemouse-focus@maik-0000ff/
    ├── extension.js     ~120 lines, the whole extension
    └── metadata.json    UUID, name, supported GNOME shell-version range
```

## Install

`install.sh` in the repo root copies the extension into `~/.local/share/gnome-shell/extensions/` and enables it via `gnome-extensions enable` (with a dconf fallback for first-install). **Log out and back in once after install** — Mutter cannot live-load extensions on Wayland for security reasons.

Manual install, if you skip `install.sh`:

```bash
cp -r gnome-extension/spacemouse-focus@maik-0000ff \
    ~/.local/share/gnome-shell/extensions/
gnome-extensions enable spacemouse-focus@maik-0000ff
# log out and back in
```

## D-Bus interface

- Bus name: `org.gnome.Shell` (GNOME Shell hosts the extension)
- Object path: `/io/github/maik_0000ff/SpaceMouseFocus`
- Interface: `io.github.maik_0000ff.SpaceMouseFocus`

| Member | Kind | Returns | Description |
|---|---|---|---|
| `FocusChanged` | signal | `s` | Emitted when the focused window changes; argument is the new `wm_class` |
| `GetFocused` | method | `s` | Current `wm_class` — for late subscribers that connect after a focus change |
| `List` | method | `s` (JSON) | All windows on the active workspace, same JSON schema as the Window Calls extension |

## Debugging

Watch focus changes live:

```bash
gdbus monitor --session --dest org.gnome.Shell \
  --object-path /io/github/maik_0000ff/SpaceMouseFocus
```

Query the current focus:

```bash
gdbus call --session --dest org.gnome.Shell \
  --object-path /io/github/maik_0000ff/SpaceMouseFocus \
  --method io.github.maik_0000ff.SpaceMouseFocus.GetFocused
```

If the extension fails to load, GNOME Shell errors show up in `journalctl --user -t gnome-shell -b`.

## Supporting new GNOME releases

When a new major GNOME release ships, append its version number to the `shell-version` array in `metadata.json` — GNOME Shell refuses to load an extension whose `shell-version` list does not include the running version.
