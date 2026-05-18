"""Small helpers shared across modules — daemon socket, LED, common widget builders."""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
)

# Re-export daemon-socket helpers so existing callers keep their import path.
# The actual implementations live in daemon_socket.py (Qt-free for testing).
from .daemon_socket import send_daemon_cmd, wait_for_daemon_socket  # noqa: F401

# ── LED control via direct USB HID ────────────────────────────────────


def set_spacemouse_led(on):
    """Control SpaceMouse LED directly via USB HID (bypasses libspnav/spacenavd).

    spnav_cfg_set_led doesn't work with spacenavd protocol 0.
    Direct HID feature report (ID 0x04) works regardless of spacenavd version.
    """
    try:
        for entry in Path("/sys/class/hidraw").iterdir():
            uevent = entry / "device" / "uevent"
            if uevent.exists() and "0000046D:0000C626" in uevent.read_text():
                dev = Path("/dev") / entry.name
                fd = os.open(str(dev), os.O_WRONLY | os.O_NONBLOCK)
                os.write(fd, bytes([0x04, 0x01 if on else 0x00]))
                os.close(fd)
                return True
    except OSError:
        pass
    return False


# ── Wheel-blocking variants ───────────────────────────────────────────


class NoScrollSlider(QSlider):
    """QSlider that ignores mouse-wheel events. Used inside scroll areas
    so the wheel scrolls the page instead of nudging the slider value."""

    def wheelEvent(self, event):
        event.ignore()


class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse-wheel events. Same rationale as
    NoScrollSlider — scrolling the page must not flip the selection."""

    def wheelEvent(self, event):
        event.ignore()


# ── UI helpers ────────────────────────────────────────────────────────


def make_card(title=None):
    """Create a styled card frame with optional section title."""
    card = QFrame()
    card.setProperty("class", "card")
    card.setObjectName("card")
    card.setStyleSheet(
        "QFrame#card { background-color: #2a2a3e; border-radius: 8px; padding: 12px; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold;")
        layout.addWidget(lbl)
    return card, layout


def make_slider(minimum, maximum, value, decimals=0, suffix=""):
    """Create a horizontal slider with value label inside a rounded container.

    The container sits inside the card and uses the main window bg so the
    slider area reads as a recess into the card. Returns (widget, slider, label).
    """
    container = QFrame()
    container.setObjectName("slider-box")
    container.setStyleSheet(
        "QFrame#slider-box { background-color: #1e1e2e; border-radius: 6px; }"
    )
    hl = QHBoxLayout(container)
    hl.setContentsMargins(12, 4, 12, 4)
    hl.setSpacing(8)

    slider = NoScrollSlider(Qt.Orientation.Horizontal)
    scale = 10**decimals
    slider.setRange(int(minimum * scale), int(maximum * scale))
    slider.setValue(int(value * scale))
    slider.setMinimumWidth(200)

    val_label = QLabel()
    val_label.setStyleSheet("color: #5294e2; font-weight: bold; min-width: 45px;")
    val_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def update_label(v):
        if decimals > 0:
            val_label.setText(f"{v / scale:.{decimals}f}{suffix}")
        else:
            val_label.setText(f"{v}{suffix}")

    slider.valueChanged.connect(update_label)
    update_label(slider.value())

    hl.addWidget(slider, 1)
    hl.addWidget(val_label)
    return container, slider, val_label


# ── Tray icon pixmap ──────────────────────────────────────────────────


def create_tray_icon_pixmap(text="SM"):
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(82, 148, 226))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 12, 12)
    painter.setPen(QColor(255, 255, 255))
    font = QFont("Sans", 18, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap
