"""Exec-action configuration dialog with XDG application picker.

Used by the Buttons card on the Desktop page when a row's action is set
to ``exec``. The dialog edits a single command line, parses it with
shlex into argv (which is what the daemon stores and what ``execvp``
consumes), and offers a "From installed app…" shortcut that scans the
XDG ``.desktop`` files.

The pure parse/format helpers live in :mod:`cmdline` so the pytest
job can exercise them without a PySide6 install. The dialog itself
is self-contained: callers pass the current argv in and read the
parsed argv out via :meth:`ExecConfigDialog.argv`. Cancel leaves the
row unchanged.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .cmdline import format_cmdline, parse_cmdline, parse_xdg_exec
from .constants import COLOR_ERROR, COLOR_TEXT_DIM, COLOR_TEXT_MUTED
from .helpers import NoScrollComboBox
from .installed_apps import group_by_category, scan_installed_apps

# Re-export the pure helpers so existing callers (pages.py, tests
# touching the dialog) keep working with `from .exec_dialog import …`.
__all__ = ["ExecConfigDialog", "format_cmdline", "parse_cmdline", "parse_xdg_exec"]


class ExecConfigDialog(QDialog):
    """Edit the command line bound to one button-row's exec action.

    Layout:
      - Cmdline text field (single line, shlex-parsed).
      - Live preview row showing the parsed argv as a numbered list.
      - "From installed app…" combo + Apply button → fills the cmdline
        from a scanned ``.desktop`` Exec= entry.
      - OK / Cancel buttons.
    """

    def __init__(self, current_argv=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Run command")
        self.setMinimumWidth(560)
        self._argv = list(current_argv or [])

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)
        self.cmdline_edit = QLineEdit(format_cmdline(self._argv))
        self.cmdline_edit.setPlaceholderText("e.g. firefox --new-window https://obsproject.com")
        self.cmdline_edit.textChanged.connect(self._refresh_preview)
        form.addRow("Command:", self.cmdline_edit)
        outer.addLayout(form)

        # Live preview of the parsed argv. Shown in monospace so users
        # can see exactly how shlex split their input — quoting issues
        # are obvious at a glance instead of biting at runtime.
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("monospace")
        self.preview_label.setFont(mono)
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.preview_label)

        # XDG picker: scan installed apps, group by category, pick one
        # to prefill the cmdline. The combo carries the parsed argv as
        # itemData so we don't re-parse on Apply.
        picker_row = QHBoxLayout()
        picker_row.setSpacing(6)
        picker_label = QLabel("From installed app:")
        picker_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        picker_row.addWidget(picker_label)
        self.app_combo = NoScrollComboBox()
        self.app_combo.setMinimumWidth(280)
        self._populate_apps()
        picker_row.addWidget(self.app_combo, 1)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_selected_app)
        picker_row.addWidget(apply_btn)
        outer.addLayout(picker_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._refresh_preview(self.cmdline_edit.text())

    def _populate_apps(self):
        """Fill the picker combo with installed XDG apps, grouped by category.

        Each entry carries the parsed argv as itemData. Apps whose
        ``Exec=`` parses to an empty argv are skipped — there's nothing
        to launch.
        """
        self.app_combo.addItem("— Select an app —", None)
        try:
            apps = scan_installed_apps()
        except OSError:
            apps = []
        grouped = group_by_category(apps)
        for category in sorted(grouped):
            for app in grouped[category]:
                argv = parse_xdg_exec(app.get("exec", ""))
                if not argv:
                    continue
                label = f"{category} — {app['name']}"
                self.app_combo.addItem(label, argv)

    def _apply_selected_app(self):
        argv = self.app_combo.currentData()
        if not argv:
            return
        self.cmdline_edit.setText(format_cmdline(argv))

    def _refresh_preview(self, text):
        argv = parse_cmdline(text)
        if not argv:
            self.preview_label.setText("(empty command)")
            self.preview_label.setStyleSheet(f"color: {COLOR_ERROR}; font-size: 11px;")
            return
        lines = [f"argv[{i}] = {a}" for i, a in enumerate(argv)]
        self.preview_label.setText("\n".join(lines))
        self.preview_label.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")

    def argv(self):
        """Return the configured argv, or empty list on parse failure."""
        return parse_cmdline(self.cmdline_edit.text())
