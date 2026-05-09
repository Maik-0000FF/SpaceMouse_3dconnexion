"""Custom widgets: ToggleSwitch, AxesCard, AxisBar, LivePreviewBar."""

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QSize, QTimer,
                            Qt, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QSizePolicy, QSlider, QSpacerItem, QVBoxLayout, QWidget)

from .constants import (AXIS_ACTIONS, AXIS_ACTION_LABELS, AXIS_KEYS, AXIS_NAMES,
                        BTN_ACTIONS, BTN_ACTION_LABELS)


# ── ToggleSwitch (Apple-style pill) ───────────────────────────────────

class ToggleSwitch(QWidget):
    """Apple-style animated toggle switch with label."""
    stateChanged = Signal(int)

    def __init__(self, label_text="", checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._label_text = label_text
        self._knob_x = 1.0  # animation position: 0.0 = off, 1.0 = on

        # Track dimensions
        self._track_w = 44
        self._track_h = 24
        self._knob_margin = 2
        self._knob_size = self._track_h - 2 * self._knob_margin
        self._label_gap = 10

        # Animation
        self._anim = QPropertyAnimation(self, b"knob_position")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        if checked:
            self._knob_x = 1.0
        else:
            self._knob_x = 0.0

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self._track_h + 4)

    def _get_knob_position(self):
        return self._knob_x

    def _set_knob_position(self, val):
        self._knob_x = val
        self.update()

    knob_position = Property(float, _get_knob_position, _set_knob_position)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        if self._checked == checked:
            return
        self._checked = checked
        self._animate(checked)
        self.stateChanged.emit(1 if checked else 0)

    def _animate(self, to_on):
        self._anim.stop()
        self._anim.setStartValue(self._knob_x)
        self._anim.setEndValue(1.0 if to_on else 0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self._animate(self._checked)
            self.stateChanged.emit(1 if self._checked else 0)

    def sizeHint(self):
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self._label_text) if self._label_text else 0
        total_w = self._track_w + (self._label_gap + text_w if text_w else 0)
        return QSize(total_w + 4, max(self._track_h + 4, fm.height() + 4))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        y_offset = (self.height() - self._track_h) // 2

        # Track colors
        off_color = QColor(0x45, 0x47, 0x5a)
        on_color = QColor(0x52, 0x94, 0xe2)

        # Interpolate track color
        t = self._knob_x
        r = int(off_color.red() + t * (on_color.red() - off_color.red()))
        g = int(off_color.green() + t * (on_color.green() - off_color.green()))
        b = int(off_color.blue() + t * (on_color.blue() - off_color.blue()))
        track_color = QColor(r, g, b)

        # Draw track (pill shape)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(0, y_offset, self._track_w, self._track_h,
                          self._track_h / 2, self._track_h / 2)

        # Draw knob (white circle)
        knob_travel = self._track_w - self._knob_size - 2 * self._knob_margin
        knob_x = self._knob_margin + self._knob_x * knob_travel
        knob_y = y_offset + self._knob_margin

        # Subtle shadow
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawEllipse(int(knob_x), int(knob_y + 1), self._knob_size, self._knob_size)

        # White knob
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(int(knob_x), int(knob_y), self._knob_size, self._knob_size)

        # Draw label text
        if self._label_text:
            p.setPen(QColor(0xcd, 0xd6, 0xf4))
            text_x = self._track_w + self._label_gap
            text_y = (self.height() + self.fontMetrics().ascent() - self.fontMetrics().descent()) // 2
            p.drawText(text_x, text_y, self._label_text)

        p.end()


def make_toggle(label_text, checked=False):
    """Create an Apple-style toggle switch with label."""
    return ToggleSwitch(label_text, checked)

# ── Reusable Axes Card ────────────────────────────────────────────────

DISABLED_SLIDER_STYLE = """
QSlider::groove:horizontal { background: #313244; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #45475a; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }
QSlider::sub-page:horizontal { background: #45475a; border-radius: 3px; }
"""


# ── AxesCard ──────────────────────────────────────────────────────────

class AxesCard(QWidget):
    """Reusable 6-axis table with configurable columns per page.

    Columns (all optional, configured via constructor booleans):
      - action: QComboBox (Desktop: axis action dropdown)
      - enable: ToggleSwitch (FreeCAD: per-axis enable)
      - invert: ToggleSwitch (all pages: per-axis invert)
      - deadzone: QSlider 0-100 (Desktop: active, FreeCAD/Blender: greyed out)
    Extra toggles: appended below the axis grid.
    """
    changed = Signal()

    def __init__(self, axis_labels, *,
                 show_action=False, action_items=None,
                 show_enable=False,
                 show_invert=True,
                 show_deadzone=True, deadzone_enabled=True,
                 deadzone_max=300,
                 extra_toggles=None,
                 parent=None):
        super().__init__(parent)
        self._building = True
        self._axis_labels = axis_labels
        self._show_action = show_action
        self._show_enable = show_enable
        self._show_invert = show_invert
        self._show_deadzone = show_deadzone
        self._deadzone_enabled = deadzone_enabled
        self._deadzone_max = deadzone_max

        self.action_combos = []
        self.enable_toggles = []
        self.invert_toggles = []
        self.deadzone_sliders = []
        self.deadzone_labels = []
        self.extra_toggle_widgets = []

        card, cl = make_card("AXES")

        # Header row
        header = QHBoxLayout()
        header.setSpacing(6)
        axis_lbl = QLabel("Axis")
        axis_lbl.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
        axis_lbl.setFixedWidth(130)
        header.addWidget(axis_lbl)
        if show_action:
            h = QLabel("Action")
            h.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
            h.setMinimumWidth(160)
            header.addWidget(h, 1)
        if show_enable:
            h = QLabel("Enable")
            h.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
            h.setFixedWidth(60)
            header.addWidget(h)
        if show_invert:
            h = QLabel("Invert")
            h.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
            h.setFixedWidth(60)
            header.addWidget(h)
        if show_deadzone:
            h = QLabel("Deadzone")
            h.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
            h.setMinimumWidth(100)
            header.addWidget(h, 1)
        cl.addLayout(header)

        # Axis rows
        for i, label in enumerate(axis_labels):
            row = QHBoxLayout()
            row.setSpacing(6)

            name_lbl = QLabel(label)
            name_lbl.setFixedWidth(130)
            row.addWidget(name_lbl)

            if show_action:
                combo = QComboBox()
                combo.addItems(action_items or [])
                combo.currentIndexChanged.connect(self._emit_changed)
                combo.setMinimumWidth(160)
                row.addWidget(combo, 1)
                self.action_combos.append(combo)

            if show_enable:
                en = ToggleSwitch("", False)
                en.stateChanged.connect(self._emit_changed)
                en.setFixedWidth(60)
                row.addWidget(en)
                self.enable_toggles.append(en)

            if show_invert:
                inv = ToggleSwitch("", False)
                inv.stateChanged.connect(self._emit_changed)
                inv.setFixedWidth(60)
                row.addWidget(inv)
                self.invert_toggles.append(inv)

            if show_deadzone:
                dz_container = QWidget()
                dz_hl = QHBoxLayout(dz_container)
                dz_hl.setContentsMargins(0, 0, 0, 0)
                dz_hl.setSpacing(4)
                dz_slider = QSlider(Qt.Orientation.Horizontal)
                dz_slider.setRange(0, deadzone_max)
                dz_slider.setValue(0)
                dz_slider.setMinimumWidth(80)
                dz_lbl = QLabel("0")
                dz_lbl.setStyleSheet("color: #5294e2; font-weight: bold; min-width: 28px;")
                dz_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                dz_slider.valueChanged.connect(lambda v, l=dz_lbl: l.setText(str(v)))
                dz_slider.valueChanged.connect(self._emit_changed)
                if not deadzone_enabled:
                    dz_slider.setEnabled(False)
                    dz_slider.setStyleSheet(DISABLED_SLIDER_STYLE)
                    dz_lbl.setStyleSheet("color: #45475a; font-weight: bold; min-width: 28px;")
                dz_hl.addWidget(dz_slider, 1)
                dz_hl.addWidget(dz_lbl)
                row.addWidget(dz_container, 1)
                self.deadzone_sliders.append(dz_slider)
                self.deadzone_labels.append(dz_lbl)

            cl.addLayout(row)

        # Extra toggles row
        if extra_toggles:
            spacer = QWidget()
            spacer.setFixedHeight(4)
            cl.addWidget(spacer)
            # Lay them out in rows of 2
            for row_start in range(0, len(extra_toggles), 2):
                row_hl = QHBoxLayout()
                row_hl.setSpacing(16)
                for j in range(row_start, min(row_start + 2, len(extra_toggles))):
                    label, checked = extra_toggles[j][:2]
                    toggle = make_toggle(label, checked)
                    toggle.stateChanged.connect(self._emit_changed)
                    row_hl.addWidget(toggle)
                    self.extra_toggle_widgets.append(toggle)
                row_hl.addStretch()
                cl.addLayout(row_hl)

        self._card = card
        self._card_layout = cl
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
        self._building = False

    def _emit_changed(self):
        if not self._building:
            self.changed.emit()


# ── AxisBar + LivePreviewBar ──────────────────────────────────────────

class AxisBar(QWidget):
    """Custom axis bar with deadzone visualization.

    Shows the current axis value as a bar from center, with the deadzone
    region highlighted. Values inside the deadzone are dimmed, outside are
    bright blue.
    """

    def __init__(self):
        super().__init__()
        self._value = 0
        self._deadzone = 0
        self.setFixedHeight(12)
        self.setMinimumWidth(40)

    def setValue(self, val):
        self._value = max(-350, min(350, val))
        self.update()

    def setDeadzone(self, dz):
        self._deadzone = max(0, min(350, dz))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        center = w / 2.0

        # Background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0x31, 0x32, 0x44))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        # Deadzone region (centered, visible red-tinted area)
        if self._deadzone > 0:
            dz_half = (self._deadzone / 350.0) * (w / 2.0)
            p.setBrush(QColor(0xf3, 0x8b, 0xa8, 50))
            p.drawRoundedRect(int(center - dz_half), 0, int(dz_half * 2), h, 3, 3)
            # Deadzone edge lines
            pen = QPen(QColor(0xf3, 0x8b, 0xa8, 120))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.drawLine(int(center - dz_half), 0, int(center - dz_half), h)
            p.drawLine(int(center + dz_half), 0, int(center + dz_half), h)
            p.setPen(Qt.PenStyle.NoPen)

        # Value bar (from center)
        if self._value != 0:
            inside_dz = abs(self._value) <= self._deadzone
            if inside_dz:
                color = QColor(0xf3, 0x8b, 0xa8, 100)  # muted red inside deadzone
            else:
                color = QColor(0x52, 0x94, 0xe2)        # bright blue outside
            p.setBrush(color)
            val_x = center + (self._value / 350.0) * (w / 2.0)
            if val_x > center:
                p.drawRoundedRect(int(center), 0, int(val_x - center), h, 2, 2)
            else:
                p.drawRoundedRect(int(val_x), 0, int(center - val_x), h, 2, 2)

        p.end()


# ── Live Preview Bar ──────────────────────────────────────────────────

class LivePreviewBar(QWidget):
    """Compact horizontal live preview bar with deadzone visualization."""

    def __init__(self):
        super().__init__()
        self.setObjectName("live-bar")
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(6)

        lbl = QLabel("Live:")
        lbl.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl)

        self.bars = []
        short_names = ["TX", "TY", "TZ", "RX", "RY", "RZ"]
        for name in short_names:
            nl = QLabel(name)
            nl.setStyleSheet("color: #6c7086; font-size: 10px; min-width: 18px;")
            layout.addWidget(nl)
            bar = AxisBar()
            layout.addWidget(bar, 1)
            self.bars.append(bar)

        layout.addSpacing(8)

        lbl = QLabel("Buttons:")
        lbl.setStyleSheet("color: #a6adc8; font-weight: bold; font-size: 11px;")
        layout.addWidget(lbl)

        self.btn_labels = []
        for i in range(2):
            bl = QLabel("\u25cb")
            bl.setStyleSheet("font-size: 14px; color: #45475a;")
            layout.addWidget(bl)
            self.btn_labels.append(bl)

        layout.addSpacing(12)

        self.profile_label = QLabel("Profile: default")
        self.profile_label.setStyleSheet("color: #5294e2; font-weight: bold; font-size: 11px;")
        layout.addWidget(self.profile_label)

        self.status_dot = QLabel("\u25cf")
        self.status_dot.setStyleSheet("font-size: 12px; color: #45475a;")
        self.status_dot.setToolTip("Daemon: checking...")
        layout.addWidget(self.status_dot)

    def update_axes(self, values):
        for i, val in enumerate(values):
            if i < len(self.bars):
                self.bars[i].setValue(val)

    def set_deadzones(self, values):
        """Update deadzone visualization on all 6 axis bars."""
        for i, dz in enumerate(values):
            if i < len(self.bars):
                self.bars[i].setDeadzone(dz)

    def update_button(self, bnum, pressed):
        if 0 <= bnum < len(self.btn_labels):
            if pressed:
                self.btn_labels[bnum].setText("\u25cf")
                self.btn_labels[bnum].setStyleSheet("font-size: 14px; color: #a6e3a1;")
            else:
                self.btn_labels[bnum].setText("\u25cb")
                self.btn_labels[bnum].setStyleSheet("font-size: 14px; color: #45475a;")

    def set_profile(self, name):
        self.profile_label.setText(f"Profile: {name}")

    def set_daemon_status(self, connected):
        if connected:
            self.status_dot.setStyleSheet("font-size: 12px; color: #a6e3a1;")
            self.status_dot.setToolTip("Daemon: connected")
        else:
            self.status_dot.setStyleSheet("font-size: 12px; color: #f38ba8;")
            self.status_dot.setToolTip("Daemon: not connected")
