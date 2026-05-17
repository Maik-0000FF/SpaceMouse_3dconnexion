// SpaceMouse Focus Bridge — minimal GNOME Shell extension that exposes
// the focused window's wm_class on the session bus. The SpaceMouse
// desktop daemon polls this to switch profiles when Blender or FreeCAD
// gains focus. Output schema is intentionally identical to the
// `Window Calls` extension's List() method so the GUI's poller treats
// either backend identically — see gui/spacemouse_config/monitors.py.

import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE_NAME = 'io.github.maik_0000ff.SpaceMouseFocus';
const IFACE_PATH = '/io/github/maik_0000ff/SpaceMouseFocus';

const IFACE_XML = `
<node>
  <interface name="${IFACE_NAME}">
    <method name="List">
      <arg type="s" direction="out" name="windows"/>
    </method>
  </interface>
</node>`;

export default class SpaceMouseFocusExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this._dbus.export(Gio.DBus.session, IFACE_PATH);
    }

    disable() {
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
    }

    List() {
        const workspaceManager = global.workspace_manager;
        const activeWorkspace = workspaceManager.get_active_workspace();
        const result = [];
        for (const actor of global.get_window_actors()) {
            const w = actor.get_meta_window();
            if (!w) continue;
            result.push({
                wm_class: w.get_wm_class(),
                wm_class_instance: w.get_wm_class_instance(),
                focus: w.has_focus(),
                pid: w.get_pid(),
                id: w.get_id(),
                in_current_workspace: w.get_workspace() === activeWorkspace,
            });
        }
        return JSON.stringify(result);
    }
}
