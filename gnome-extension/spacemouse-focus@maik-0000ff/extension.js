// SpaceMouse Focus Bridge — minimal GNOME Shell extension that exposes
// the focused window's wm_class on the session bus. The SpaceMouse
// desktop daemon listens for the FocusChanged signal to switch profiles
// when Blender or FreeCAD gains focus — push-based, so the compositor
// is not woken on a polling cadence (Blender otherwise stutters because
// Mutter has to serialise the window list every poll tick).
//
// List() is kept for compatibility with the third-party Window Calls
// extension (same JSON schema, same return type) and also serves as the
// initial-state query for clients that subscribe after a focus change.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE_NAME = 'io.github.maik_0000ff.SpaceMouseFocus';
const IFACE_PATH = '/io/github/maik_0000ff/SpaceMouseFocus';

const IFACE_XML = `
<node>
  <interface name="${IFACE_NAME}">
    <method name="List">
      <arg type="s" direction="out" name="windows"/>
    </method>
    <method name="GetFocused">
      <arg type="s" direction="out" name="wm_class"/>
    </method>
    <signal name="FocusChanged">
      <arg type="s" name="wm_class"/>
    </signal>
  </interface>
</node>`;

export default class SpaceMouseFocusExtension extends Extension {
    enable() {
        this._lastClass = '';
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this._dbus.export(Gio.DBus.session, IFACE_PATH);

        // Mutter notifies on focus changes via the `focus-window`
        // property on global.display. The handler is stored as an
        // instance property (not an inline arrow) so disable() can
        // drop the reference and let GC collect it deterministically;
        // a lingering closure would let a late-firing focus event run
        // handler code on a disabled extension.
        this._focusHandler = this._onFocusChanged.bind(this);
        this._focusHandlerId = global.display.connect(
            'notify::focus-window',
            this._focusHandler
        );
        if (!this._focusHandlerId) {
            // Older Mutter builds may not expose the signal under this
            // name. Surface the failure so the user knows auto profile
            // switching will not work, instead of appearing to succeed.
            console.warn(
                'spacemouse-focus: notify::focus-window not available on this GNOME Shell; ' +
                'auto profile switching will not work'
            );
            return;
        }
        // Emit the current state so a subscriber that connected before
        // the first user focus change still gets a value.
        this._onFocusChanged();
    }

    disable() {
        if (this._focusHandlerId) {
            global.display.disconnect(this._focusHandlerId);
            this._focusHandlerId = null;
        }
        this._focusHandler = null;
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        this._lastClass = '';
    }

    _onFocusChanged() {
        const w = global.display.focus_window;
        const cls = w ? (w.get_wm_class() || '') : '';
        if (cls === this._lastClass) return;
        this._lastClass = cls;
        if (this._dbus) {
            this._dbus.emit_signal(
                'FocusChanged',
                new GLib.Variant('(s)', [cls])
            );
        }
    }

    GetFocused() {
        return this._lastClass;
    }

    List() {
        const workspaceManager = global.workspace_manager;
        const activeWorkspace = workspaceManager.get_active_workspace();
        const result = [];
        for (const actor of global.get_window_actors()) {
            const w = actor.get_meta_window();
            if (!w) continue;
            const pid = w.get_pid();
            const workspace = w.get_workspace();
            result.push({
                wm_class: w.get_wm_class(),
                wm_class_instance: w.get_wm_class_instance(),
                focus: w.has_focus(),
                // X11 clients without _NET_WM_PID and override-redirect
                // windows return -1; normalise to null so consumers can
                // distinguish "unknown" from a real pid.
                pid: pid > 0 ? pid : null,
                id: w.get_id(),
                // Sticky windows have no workspace (get_workspace()
                // returns null); treat them as present in every workspace
                // so a consumer filtering by in_current_workspace still
                // sees them.
                in_current_workspace: w.is_on_all_workspaces()
                    || workspace === activeWorkspace,
            });
        }
        return JSON.stringify(result);
    }
}
