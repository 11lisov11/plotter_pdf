from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class SegmentedControl(QWidget):
    value_changed = Signal(str)

    def __init__(self, options: Iterable[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentedControl")

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        for key, title in options:
            btn = QPushButton(title, self)
            btn.setCheckable(True)
            btn.setObjectName("SegmentButton")
            self._group.addButton(btn)
            self._buttons[key] = btn
            layout.addWidget(btn)
            btn.clicked.connect(lambda checked=False, k=key: self._on_button_clicked(k))

    def _on_button_clicked(self, key: str) -> None:
        self.value_changed.emit(key)

    def set_value(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.setChecked(True)

    def value(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return next(iter(self._buttons.keys()), "")
