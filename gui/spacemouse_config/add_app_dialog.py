"""Dialog for managing the 3D apps list (add + remove via checkboxes).

Two tabs:
  * Installed — apps detected on the system via XDG .desktop files.
                Pre-checked for entries already in the current list.
                Unchecking removes them.
  * Custom    — at top: existing entries that are NOT installed apps
                (typed by the user previously, or detected via other
                means). Pre-checked, uncheck to remove. Below: free-form
                input for adding a new custom WM class string.

Each app appears in exactly one tab. ``result_list()`` returns the full
desired state on accept — caller replaces the chip list contents.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .installed_apps import group_by_category, scan_installed_apps


class AddAppDialog(QDialog):
    """Unified add+remove dialog for the 3D apps list."""

    def __init__(self, current_wm_classes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage 3D Apps")
        self.setMinimumSize(560, 540)
        self._current = list(current_wm_classes)

        # Scan once — both tabs read the same list.
        self._installed_apps = scan_installed_apps()
        self._installed_wm_lower = {a["wm_class"].lower() for a in self._installed_apps}

        self._installed_checkboxes = []  # list of (QCheckBox, wm_class)
        self._custom_existing_checkboxes = []  # list of (QCheckBox, wm_class)
        self._custom_input = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Check apps to keep them in the list, uncheck to remove. "
            "Use the Custom tab for apps that aren't detected on this "
            "system."
        )
        intro.setStyleSheet("color: #a6adc8; font-size: 12px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._build_installed_tab(), "Installed")
        tabs.addTab(self._build_custom_tab(), "Custom")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Apply")
        ok_btn.setDefault(True)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Installed tab (scanned from .desktop files) ───────────────────

    def _build_installed_tab(self):
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(0)

        grouped = group_by_category(self._installed_apps)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)

        if not self._installed_apps:
            empty = QLabel("No installed applications detected.")
            empty.setStyleSheet("color: #a6adc8; font-size: 12px;")
            layout.addWidget(empty)
        else:
            current_lower = [w.lower() for w in self._current]
            for category, cat_apps in grouped.items():
                cat_label = QLabel(category)
                cat_label.setStyleSheet(
                    "color: #89b4fa; font-weight: bold; font-size: 12px; padding: 2px 0;"
                )
                layout.addWidget(cat_label)

                grid = QGridLayout()
                grid.setSpacing(6)
                grid.setColumnStretch(0, 1)
                grid.setColumnStretch(1, 1)
                row = 0
                col = 0
                for app in cat_apps:
                    cb = QCheckBox(app["name"])
                    cb.setToolTip(f"WM class: {app['wm_class']}")
                    if app["wm_class"].lower() in current_lower:
                        cb.setChecked(True)
                    self._installed_checkboxes.append((cb, app["wm_class"]))
                    grid.addWidget(cb, row, col)
                    col += 1
                    if col >= 2:
                        col = 0
                        row += 1
                layout.addLayout(grid)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return wrap

    # ── Custom tab ────────────────────────────────────────────────────

    def _build_custom_tab(self):
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Current entries that aren't detected as installed apps.
        existing_custom = [w for w in self._current if w.lower() not in self._installed_wm_lower]
        if existing_custom:
            section = QLabel("In list (custom entries — uncheck to remove):")
            section.setStyleSheet("color: #89b4fa; font-weight: bold; font-size: 12px;")
            layout.addWidget(section)
            for wm in existing_custom:
                cb = QCheckBox(wm)
                cb.setChecked(True)
                cb.setToolTip(f"WM class: {wm}")
                self._custom_existing_checkboxes.append((cb, wm))
                layout.addWidget(cb)

            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setStyleSheet("color: #313244;")
            layout.addWidget(divider)

        hint = QLabel(
            "Add a new entry by typing a WM class. The matcher is "
            "case-insensitive and matches via equal, prefix or substring "
            "— so a short canonical name usually covers all variants of "
            "an app."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("e.g. libreoffice or org.kde.kate")
        form.addRow("WM class:", self._custom_input)
        layout.addLayout(form)

        tip = QLabel(
            "Tip: to find an app's WM class on KDE Wayland, focus its "
            "window and check the journal entry written by the "
            "spacemouse-wm-watch KWin script."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #6c7086; font-size: 11px; padding-top: 8px;")
        layout.addWidget(tip)

        layout.addStretch()
        return wrap

    # ── Result accessor ───────────────────────────────────────────────

    def result_list(self):
        """Return the desired WM class list after applying user changes.

        Caller should ``set_values`` the chip list to this list — it is
        the complete new state, not a diff. Dedupes by lowercase.
        """
        out = []
        seen = set()

        def maybe_add(wc):
            if not wc:
                return
            key = wc.lower()
            if key in seen:
                return
            seen.add(key)
            out.append(wc)

        for cb, wm in self._installed_checkboxes:
            if cb.isChecked():
                maybe_add(wm)

        for cb, wm in self._custom_existing_checkboxes:
            if cb.isChecked():
                maybe_add(wm)

        if self._custom_input is not None:
            text = self._custom_input.text().strip()
            if text:
                maybe_add(text)

        return out
