"""Dialog for managing the 3D apps list (add + remove via checkboxes).

Two tabs:
  * Known Apps — category-grouped checkboxes from APP_CATALOG. Pre-checked
                 for apps already in the list. Unchecking removes them.
  * Custom    — at top: existing non-catalog entries with pre-checked
                 checkboxes (uncheck to remove). Below: free-form input
                 for adding new custom WM class strings.

``result_list()`` returns the full desired state on accept — caller
replaces the chip list contents with that.
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

from .app_catalog import APP_CATALOG, app_owns_class


def _wm_in_catalog(wm_class):
    """True if wm_class belongs to any known app in APP_CATALOG."""
    for category in APP_CATALOG.values():
        for classes in category.values():
            if app_owns_class(classes, wm_class):
                return True
    return False


class AddAppDialog(QDialog):
    """Unified add+remove dialog for the 3D apps list.

    ``current_wm_classes`` is the profile's current entries. Catalog
    matches show as pre-checked enabled checkboxes; unchecking removes
    them. Non-catalog (custom) entries appear at the top of the Custom
    tab with their own pre-checked checkboxes. ``result_list()`` returns
    the full desired state on accept.
    """

    def __init__(self, current_wm_classes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage 3D Apps")
        self.setMinimumSize(560, 540)
        self._current = list(current_wm_classes)
        self._known_checkboxes = []  # list of (QCheckBox, [wm_classes])
        self._custom_existing_checkboxes = []  # list of (QCheckBox, wm_class)
        self._custom_input = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Check apps to keep them in the list, uncheck to remove. "
            "Use the Custom tab to add or remove unusual apps that aren't "
            "in the catalog."
        )
        intro.setStyleSheet("color: #a6adc8; font-size: 12px;")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._build_known_tab(), "Known Apps")
        tabs.addTab(self._build_custom_tab(), "Custom")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Apply")
        ok_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Known Apps tab ────────────────────────────────────────────────

    def _build_known_tab(self):
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(14)

        for category, apps in APP_CATALOG.items():
            cat_label = QLabel(category)
            cat_label.setStyleSheet(
                "color: #89b4fa; font-weight: bold; font-size: 12px; "
                "padding: 2px 0;"
            )
            layout.addWidget(cat_label)

            grid = QGridLayout()
            grid.setSpacing(6)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            row = 0
            col = 0
            for name, classes in apps.items():
                cb = QCheckBox(name)
                already_listed = any(
                    app_owns_class(classes, w) for w in self._current
                )
                cb.setChecked(already_listed)
                cb.setToolTip("WM classes: " + ", ".join(classes))
                self._known_checkboxes.append((cb, classes))
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

        # Existing custom entries (current list items not in catalog)
        existing_custom = [w for w in self._current if not _wm_in_catalog(w)]
        if existing_custom:
            section = QLabel("In list (custom entries — uncheck to remove):")
            section.setStyleSheet(
                "color: #89b4fa; font-weight: bold; font-size: 12px;"
            )
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

        for cb, classes in self._known_checkboxes:
            if cb.isChecked():
                for c in classes:
                    maybe_add(c)

        for cb, wm in self._custom_existing_checkboxes:
            if cb.isChecked():
                maybe_add(wm)

        if self._custom_input is not None:
            text = self._custom_input.text().strip()
            if text:
                maybe_add(text)

        return out
