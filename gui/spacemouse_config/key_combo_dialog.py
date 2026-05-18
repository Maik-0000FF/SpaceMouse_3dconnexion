"""Key-combo configuration dialog.

The daemon's combo parser (src/config.c::parse_key_combo) accepts
strings like ``Ctrl+Shift+S`` — zero or more modifiers joined by ``+``
followed by the end key. This dialog lets the user assemble such a
string visually with four checkboxes (Ctrl/Shift/Alt/Meta) and a
combobox listing every key the daemon knows.

The pure parse/format helpers live in :mod:`key_combo` so the pytest
job can exercise them without a PySide6 install — the dialog UI is
the only piece in here that needs Qt.
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
from .key_combo import format_combo, parse_combo_string

# Re-export so existing callers (pages.py) keep working with
# `from .key_combo_dialog import format_combo, parse_combo_string`.
__all__ = ["KeyComboDialog", "format_combo", "parse_combo_string"]


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
