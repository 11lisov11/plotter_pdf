from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class LogsPage(QWidget):
    open_drawer_requested = Signal()
    clear_logs_requested = Signal()
    copy_logs_requested = Signal()
    open_logs_folder_requested = Signal()

    def __init__(self, logs_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.logs_path = logs_path
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        card = QFrame(self)
        card.setObjectName("PageCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Логи и сервис", card)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Логи скрыты по умолчанию. Откройте панель логов, чтобы посмотреть детали операций и ошибок подключения.",
            card,
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.path_label = QLabel(f"Файл логов: {self.logs_path}", card)
        self.path_label.setObjectName("HintLabel")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        self.open_drawer_btn = QPushButton("Показать лог", card)
        self.copy_btn = QPushButton("Копировать лог", card)
        self.clear_btn = QPushButton("Очистить лог", card)
        self.open_folder_btn = QPushButton("Открыть папку логов", card)

        self.open_drawer_btn.clicked.connect(self.open_drawer_requested.emit)
        self.copy_btn.clicked.connect(self.copy_logs_requested.emit)
        self.clear_btn.clicked.connect(self.clear_logs_requested.emit)
        self.open_folder_btn.clicked.connect(self.open_logs_folder_requested.emit)

        layout.addWidget(self.open_drawer_btn)
        layout.addWidget(self.copy_btn)
        layout.addWidget(self.clear_btn)
        layout.addWidget(self.open_folder_btn)
        root.addWidget(card)
        root.addStretch(1)
