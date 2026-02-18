from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


STATUS_COLORS = {
    "neutral": "#94a3b8",
    "connecting": "#f59e0b",
    "ok": "#10b981",
    "error": "#ef4444",
}


class StatusPill(QWidget):
    def __init__(self, text: str = "Отключено", level: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusPill")

        self._dot = QLabel(self)
        self._dot.setFixedSize(10, 10)
        self._dot.setAlignment(Qt.AlignCenter)

        self._label = QLabel(text, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addWidget(self._dot)
        layout.addWidget(self._label)

        self.set_level(level)

    def set_level(self, level: str) -> None:
        color = STATUS_COLORS.get(level, STATUS_COLORS["neutral"])
        self._dot.setStyleSheet(f"background:{color}; border-radius:5px;")

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def set_state(self, text: str, level: str) -> None:
        self.set_text(text)
        self.set_level(level)
