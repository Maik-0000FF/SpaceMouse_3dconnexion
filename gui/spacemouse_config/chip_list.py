"""Visual chip list widget for managing string sets in the GUI.

Replaces comma-separated QLineEdits in the MATCH APPS card. Each entry
renders as a removable pill ("chip") with a × button; wraps across rows
via a custom FlowLayout (Qt ships none).
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .app_catalog import display_name_for


# ── FlowLayout (wraps items to next line when row fills) ──────────────


class FlowLayout(QLayout):
    """Qt-example FlowLayout: lays widgets out left-to-right and wraps to
    the next row when the parent gets narrower than the next item.
    """

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_h = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > effective.right() and line_h > 0:
                x = effective.x()
                y += line_h + spacing
                next_x = x + hint.width() + spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + margins.bottom()


# ── Chip (single pill with × button) ──────────────────────────────────


class Chip(QFrame):
    """Removable pill: friendly app name + × button.

    Carries the original WM-class string so the parent can identify which
    entry to drop on removal.
    """

    removed = Signal(str)

    _STYLE = """
    Chip {
        background: #45475a;
        border-radius: 12px;
    }
    Chip:hover {
        background: #585b70;
    }
    Chip QLabel {
        color: #cdd6f4;
        background: transparent;
        padding-left: 4px;
    }
    Chip QPushButton {
        color: #cdd6f4;
        background: transparent;
        border: none;
        font-weight: bold;
        font-size: 13px;
    }
    Chip QPushButton:hover {
        color: #f38ba8;
    }
    """

    def __init__(self, wm_class, parent=None):
        super().__init__(parent)
        self._wm_class = wm_class
        self.setStyleSheet(self._STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(2)

        label = QLabel(display_name_for(wm_class))
        label.setToolTip(f"WM class: {wm_class}")
        layout.addWidget(label)

        btn = QPushButton("×")
        btn.setFixedSize(20, 20)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Remove")
        btn.clicked.connect(lambda: self.removed.emit(self._wm_class))
        layout.addWidget(btn)

    def wm_class(self):
        return self._wm_class


# ── ChipList (container of chips backed by an ordered set) ────────────


class ChipList(QWidget):
    """Manages an ordered, de-duplicated list of WM class strings as chips.

    Use ``set_values`` / ``get_values`` to read/write the underlying list,
    ``add`` / ``add_many`` to extend, and ``remove`` to drop entries.
    Emits ``changed`` whenever the contents are mutated.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = []
        self._layout = FlowLayout(self, margin=0, spacing=6)
        self.setMinimumHeight(34)

    def set_values(self, values):
        self._values = [v for v in dict.fromkeys(values) if v]
        self._rebuild()

    def get_values(self):
        return list(self._values)

    def add(self, wm_class):
        if not wm_class or wm_class in self._values:
            return
        self._values.append(wm_class)
        self._rebuild()
        self.changed.emit()

    def add_many(self, wm_classes):
        any_added = False
        for w in wm_classes:
            if w and w not in self._values:
                self._values.append(w)
                any_added = True
        if any_added:
            self._rebuild()
            self.changed.emit()

    def remove(self, wm_class):
        if wm_class not in self._values:
            return
        self._values.remove(wm_class)
        self._rebuild()
        self.changed.emit()

    def _rebuild(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        for wm in self._values:
            chip = Chip(wm, parent=self)
            chip.removed.connect(self.remove)
            self._layout.addWidget(chip)
        self.updateGeometry()
