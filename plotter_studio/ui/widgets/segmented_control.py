from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class SegmentedControl(QWidget):
    value_changed = Signal(str)

    def __init__(self, options: Iterable[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        for key, title in options:
            btn = QPushButton(title, self)
            btn.setCheckable(True)
            btn.setObjectName("SegmentButton")
            self._group.addButton(btn)
            self._buttons[key] = btn
            self._layout.addWidget(btn)
            btn.clicked.connect(lambda checked=False, k=key: self._on_button_clicked(k))
        self._apply_segment_style()

    def _apply_segment_style(self) -> None:
        self.setStyleSheet(
            """
            QPushButton#SegmentButton {
                border-radius: 10px;
                padding: 7px 12px;
                border: 1px solid palette(mid);
                background: palette(base);
            }
            QPushButton#SegmentButton:checked {
                border: 1px solid palette(highlight);
                background: palette(highlight);
                color: white;
                font-weight: 600;
            }
            """
        )

    def _on_button_clicked(self, key: str) -> None:
        self.value_changed.emit(key)

    def set_value(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is None:
            return
        btn.setChecked(True)

    def value(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return next(iter(self._buttons.keys()), "")

