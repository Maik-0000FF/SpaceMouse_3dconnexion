"""Dialog for adding apps to a ChipList.

Two tabs:
  * Known Apps — category-grouped checkboxes from APP_CATALOG
  * Custom    — free-form WM class entry for unusual apps

A Running Windows tab is planned (KWin live query) but not yet wired up.
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


class AddAppDialog(QDialog):
    """Pick one or more apps to add to a profile's match list.

    ``current_wm_classes`` is the profile's current entries — used to
    pre-check / dim presets that are already in the list. ``selected()``
    returns the list of WM classes to add on accept.
    """

    def __init__(self, current_wm_classes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Application")
        self.setMinimumSize(560, 520)
        self._current = list(current_wm_classes)
        self._known_checkboxes = []  # list of (QCheckBox, [wm_classes])
        self._custom_input = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Pick an application from the catalog or enter a custom WM class."
        )
        intro.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._build_known_tab(), "Known Apps")
        tabs.addTab(self._build_custom_tab(), "Custom")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Add Selected")
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
                if already_listed:
                    cb.setChecked(True)
                    cb.setEnabled(False)
                    cb.setToolTip("Already in this profile")
                else:
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

        hint = QLabel(
            "Enter a WM class string. The matcher is case-insensitive "
            "and matches via equal, prefix or substring — so a short "
            "canonical name usually covers all variants of an app."
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

    def selected(self):
        """Return all WM class strings the user picked.

        Filters duplicates and entries already present in ``current``.
        Preserves catalog order, with custom entries appended at the end.
        """
        out = []
        seen = {c.lower() for c in self._current}

        def maybe_add(wc):
            if not wc:
                return
            key = wc.lower()
            if key in seen:
                return
            seen.add(key)
            out.append(wc)

        for cb, classes in self._known_checkboxes:
            if cb.isEnabled() and cb.isChecked():
                for c in classes:
                    maybe_add(c)

        if self._custom_input is not None:
            text = self._custom_input.text().strip()
            if text:
                maybe_add(text)

        return out
