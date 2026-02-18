from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ManualPage(QWidget):
    pen_down_requested = Signal(float, float)  # step, feed
    pen_up_requested = Signal(float, float)
    release_motors_requested = Signal()
    sharpen_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        card = QFrame(self)
        card.setObjectName("PageCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("4. Ручное управление и сервис", card)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("Точное управление осью Z и сервисные команды.", card)
        hint.setObjectName("HintLabel")
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        z_lbl = QLabel("Шаг Z (мм)", card)
        z_lbl.setObjectName("FieldLabel")
        self.z_step = QDoubleSpinBox(card)
        self.z_step.setRange(0.1, 200.0)
        self.z_step.setDecimals(2)
        self.z_step.setSingleStep(0.1)
        self.z_step.setMinimumHeight(42)

        feed_lbl = QLabel("Подача Z", card)
        feed_lbl.setObjectName("FieldLabel")
        self.z_feed = QDoubleSpinBox(card)
        self.z_feed.setRange(20.0, 10000.0)
        self.z_feed.setDecimals(1)
        self.z_feed.setSingleStep(10.0)
        self.z_feed.setMinimumHeight(42)

        grid.addWidget(z_lbl, 0, 0)
        grid.addWidget(self.z_step, 1, 0)
        grid.addWidget(feed_lbl, 0, 1)
        grid.addWidget(self.z_feed, 1, 1)
        layout.addLayout(grid)

        self.down_btn = QPushButton("Опустить перо", card)
        self.down_btn.setObjectName("PrimaryButton")
        self.up_btn = QPushButton("Поднять перо", card)
        self.release_btn = QPushButton("Отпустить моторы", card)
        self.release_btn.setObjectName("DangerButton")
        self.sharpen_btn = QPushButton("Заточил карандаш", card)
        self.sharpen_btn.setObjectName("SuccessButton")
        self.sharpen_banner = QLabel("ЗАТОЧИ КАРАНДАШ", card)
        self.sharpen_banner.setObjectName("HintLabel")
        for btn in (self.down_btn, self.up_btn, self.release_btn, self.sharpen_btn):
            btn.setMinimumHeight(44)

        self.down_btn.clicked.connect(lambda: self.pen_down_requested.emit(self.z_step.value(), self.z_feed.value()))
        self.up_btn.clicked.connect(lambda: self.pen_up_requested.emit(self.z_step.value(), self.z_feed.value()))
        self.release_btn.clicked.connect(self.release_motors_requested.emit)
        self.sharpen_btn.clicked.connect(self.sharpen_requested.emit)

        pen_row = QHBoxLayout()
        pen_row.setSpacing(8)
        pen_row.addWidget(self.down_btn)
        pen_row.addWidget(self.up_btn)
        layout.addLayout(pen_row)
        layout.addWidget(self.release_btn)
        layout.addWidget(self.sharpen_btn)
        layout.addWidget(self.sharpen_banner)

        root.addWidget(card)
        root.addStretch(1)

    def set_values(self, step_mm: float, feed: float) -> None:
        self.z_step.setValue(float(step_mm))
        self.z_feed.setValue(float(feed))

    def values(self) -> tuple[float, float]:
        return float(self.z_step.value()), float(self.z_feed.value())

    def set_connected_enabled(self, enabled: bool) -> None:
        self.down_btn.setEnabled(enabled)
        self.up_btn.setEnabled(enabled)
        # Отпуск моторов доступен всегда, если выбран COM.
        self.release_btn.setEnabled(True)

    def set_pencil_banner(self, text: str, alert: bool) -> None:
        color = "#ef4444" if alert else "#10b981"
        self.sharpen_banner.setText(text)
        self.sharpen_banner.setStyleSheet(f"color: {color}; font-weight: 600; background-color: transparent;")
