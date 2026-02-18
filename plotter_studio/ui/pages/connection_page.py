from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ConnectionPage(QWidget):
    refresh_requested = Signal()
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    port_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        card = QFrame(self)
        card.setObjectName("PageCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        title = QLabel("Подключение плоттера", card)
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        hint = QLabel(
            "Выберите COM-порт и подключитесь. После подключения станут доступны калибровка и рисование.",
            card,
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.port_combo = QComboBox(card)
        self.port_combo.currentTextChanged.connect(self.port_selected.emit)
        self.refresh_btn = QPushButton("Обновить", card)
        self.connect_btn = QPushButton("Подключить", card)
        self.connect_btn.setObjectName("PrimaryButton")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.connect_btn.clicked.connect(self._toggle_connect)
        row.addWidget(self.port_combo, 1)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.connect_btn)
        card_layout.addLayout(row)

        self.summary = QLabel("Состояние: Отключено", card)
        self.summary.setObjectName("HintLabel")
        card_layout.addWidget(self.summary)

        root.addWidget(card)
        root.addStretch(1)
        self._connected = False

    def _toggle_connect(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            self.connect_requested.emit(self.current_port())

    def set_ports(self, ports: list[str], selected: str) -> None:
        current = self.current_port()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if selected and selected in ports:
            self.port_combo.setCurrentText(selected)
        elif current and current in ports:
            self.port_combo.setCurrentText(current)
        elif ports:
            self.port_combo.setCurrentIndex(0)
        self.port_combo.blockSignals(False)

    def current_port(self) -> str:
        return (self.port_combo.currentText() or "").strip()

    def set_connection_state(self, connected: bool, text: str) -> None:
        self._connected = connected
        self.connect_btn.setText("Отключить" if connected else "Подключить")
        self.summary.setText(f"Состояние: {text}")
