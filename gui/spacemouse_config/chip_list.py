"""Visual chip list widget for managing string sets in the GUI.

Replaces comma-separated QLineEdits in the MATCH APPS card. Each entry
renders as a read-only pill ("chip") with the app's friendly name; wraps
via a custom FlowLayout (Qt ships none).
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
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


# ── Chip (single pill, read-only) ─────────────────────────────────────


class Chip(QFrame):
    """Read-only pill: friendly app name as label.

    A chip represents one logical application, which may be backed by
    several WM-class strings (e.g. Firefox: ``firefox`` + ``Navigator``,
    VSCode: ``Code`` + ``code-oss``). The tooltip lists all backing
    classes for transparency.
    """

    _STYLE = """
    Chip {
        background: #45475a;
        border-radius: 12px;
    }
    Chip QLabel {
        color: #cdd6f4;
        background: transparent;
    }
    """

    def __init__(self, display, wm_classes, parent=None):
        super().__init__(parent)
        self._wm_classes = list(wm_classes)
        self.setStyleSheet(self._STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(0)

        label = QLabel(display)
        label.setToolTip(
            f"WM class: {wm_classes[0]}"
            if len(wm_classes) == 1
            else "WM classes: " + ", ".join(wm_classes)
        )
        layout.addWidget(label)


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

        # Group WM classes by display name — apps with multiple catalog
        # WM-class variants (Firefox + Navigator, Code + code-oss, …)
        # render as a single chip so the list shows one entry per app.
        groups = {}
        order = []
        for wm in self._values:
            display = display_name_for(wm)
            if display in groups:
                groups[display].append(wm)
            else:
                groups[display] = [wm]
                order.append(display)

        for display in order:
            chip = Chip(display, groups[display], parent=self)
            self._layout.addWidget(chip)
        self.updateGeometry()
