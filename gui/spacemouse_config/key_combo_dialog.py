"""Key-combo configuration dialog and pure parse/format helpers.

The daemon's combo parser (src/config.c::parse_key_combo) accepts
strings like ``Ctrl+Shift+S`` — zero or more modifiers joined by ``+``
followed by the end key. This dialog lets the user assemble such a
string visually with four checkboxes (Ctrl/Shift/Alt/Meta) and a
combobox listing every key the daemon knows. The parse/format
functions are pure so they round-trip against the daemon wire format
without needing a running Qt loop.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from .constants import COLOR_ERROR, COLOR_TEXT_DIM, COMBO_KEY_NAMES, COMBO_MODIFIER_NAMES
from .helpers import NoScrollComboBox

# Map every modifier spelling the daemon parser accepts onto the
# canonical name we emit. Lower-cased lookup so case in the source
# config doesn't matter. The canonical names are exactly those in
# COMBO_MODIFIER_NAMES so format_combo can reuse that ordering.
_MOD_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "meta": "Meta",
    "super": "Meta",
    "win": "Meta",
    "cmd": "Meta",
}

# Lower-case → canonical-display mapping so parse can accept any case
# (the daemon's lookup_key uses strcasecmp) and emit the readable form
# back from COMBO_KEY_NAMES.
_KEY_CANONICAL = {k.lower(): k for k in COMBO_KEY_NAMES}


def parse_combo_string(s):
    """Parse a combo body like ``Ctrl+Shift+S`` into ``(mods, key)``.

    The body is the part after the ``key:`` prefix the daemon expects.
    Modifier spellings (Ctrl/Control, Meta/Super/Win/Cmd, …) are
    normalised onto the canonical names listed in
    :data:`constants.COMBO_MODIFIER_NAMES`. Returns ``([], "")`` on
    parse failure so a caller editing a malformed config doesn't
    crash — the dialog re-opens with empty state.
    """
    if not isinstance(s, str) or not s.strip():
        return [], ""
    parts = [p.strip() for p in s.split("+") if p.strip()]
    if not parts:
        return [], ""
    end = _KEY_CANONICAL.get(parts[-1].lower())
    if end is None:
        return [], ""
    seen = set()
    mods = []
    for raw in parts[:-1]:
        canonical = _MOD_ALIASES.get(raw.lower())
        if canonical is None:
            return [], ""
        if canonical in seen:
            # Duplicate modifier — daemon parser rejects this too, so
            # mirror that behaviour rather than silently dedup'ing.
            return [], ""
        seen.add(canonical)
        mods.append(canonical)
    return mods, end


def format_combo(mods, key):
    """Build a canonical combo string from a list/set of modifiers and
    end key. Modifier order is forced to Ctrl→Shift→Alt→Meta so the
    written config is stable regardless of which order the dialog's
    checkboxes were toggled in. Empty key returns the empty string —
    the caller will treat the row as unconfigured."""
    if not key:
        return ""
    mods_set = {m for m in (mods or []) if m in COMBO_MODIFIER_NAMES}
    ordered = [m for m in COMBO_MODIFIER_NAMES if m in mods_set]
    return "+".join([*ordered, key])


class KeyComboDialog(QDialog):
    """Edit the key combo bound to one button row.

    Layout:
      - Four modifier checkboxes in a row (Ctrl, Shift, Alt, Meta).
      - End-key combobox showing every entry from COMBO_KEY_NAMES.
      - Live preview of the canonical combo string.
      - OK / Cancel buttons.
    """

    def __init__(self, current_combo=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom key combo")
        self.setMinimumWidth(420)

        mods, key = parse_combo_string(current_combo or "")

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # Modifier row — four side-by-side checkboxes. Toggling any
        # one refreshes the preview so the user sees the result before
        # confirming.
        mod_row = QHBoxLayout()
        mod_row.setSpacing(12)
        mod_label = QLabel("Modifiers:")
        mod_label.setMinimumWidth(72)
        mod_row.addWidget(mod_label)
        self.mod_checks = {}
        for name in COMBO_MODIFIER_NAMES:
            cb = QCheckBox(name)
            cb.setChecked(name in mods)
            cb.stateChanged.connect(self._refresh_preview)
            self.mod_checks[name] = cb
            mod_row.addWidget(cb)
        mod_row.addStretch()
        outer.addLayout(mod_row)

        # End-key combobox. Uses NoScrollComboBox so a stray wheel
        # event doesn't silently change the binding while the user
        # scrolls a parent area.
        form = QFormLayout()
        form.setSpacing(8)
        self.key_combo = NoScrollComboBox()
        self.key_combo.addItems(COMBO_KEY_NAMES)
        if key in COMBO_KEY_NAMES:
            self.key_combo.setCurrentIndex(COMBO_KEY_NAMES.index(key))
        self.key_combo.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("Key:", self.key_combo)
        outer.addLayout(form)

        self.preview_label = QLabel()
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.preview_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._refresh_preview()

    def _selected_mods(self):
        return [name for name in COMBO_MODIFIER_NAMES if self.mod_checks[name].isChecked()]

    def _refresh_preview(self, *_):
        key = self.key_combo.currentText()
        text = format_combo(self._selected_mods(), key)
        if text:
            self.preview_label.setText(f"Preview: {text}")
            self.preview_label.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px;")
        else:
            self.preview_label.setText("Preview: (no key selected)")
            self.preview_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 12px;")

    def combo_string(self):
        """Return the canonical combo body (no ``key:`` prefix), or
        empty string if the user didn't pick a valid end key."""
        return format_combo(self._selected_mods(), self.key_combo.currentText())
