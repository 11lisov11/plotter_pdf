from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


SHEET_ITEMS = [
    ("work", "Рабочая зона"),
    ("a4", "A4"),
    ("a3", "A3"),
    ("notebook", "Тетрадь"),
    ("custom", "Произвольный"),
]

ANCHOR_ITEMS = [
    ("lower_left", "Нижний левый"),
    ("center", "По центру"),
    ("upper_left", "Верхний левый"),
    ("lower_right", "Нижний правый"),
    ("upper_right", "Верхний правый"),
]


class CalibrationPage(QWidget):
    calibration_requested = Signal()
    frame_requested = Signal()
    sheet_changed = Signal(str, float, float, str, float, float, bool, int)
    calibrate_before_draw_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        card = QFrame(self)
        card.setObjectName("PageCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Калибровка и активная зона", card)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Калибровка выполняется пошагово: рисуются 4 угла, после проверки можно запускать рисование.",
            card,
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        fmt_lbl = QLabel("Формат", card)
        fmt_lbl.setObjectName("FieldLabel")
        self.format_combo = QComboBox(card)
        for key, title_name in SHEET_ITEMS:
            self.format_combo.addItem(title_name, key)
        self.format_combo.currentIndexChanged.connect(self._emit_sheet_change)
        self.format_combo.currentIndexChanged.connect(self._update_dynamic_controls)

        w_lbl = QLabel("W (мм)", card)
        w_lbl.setObjectName("FieldLabel")
        self.width_spin = QDoubleSpinBox(card)
        self.width_spin.setRange(10.0, 2000.0)
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(1.0)
        self.width_spin.valueChanged.connect(self._emit_sheet_change)

        h_lbl = QLabel("H (мм)", card)
        h_lbl.setObjectName("FieldLabel")
        self.height_spin = QDoubleSpinBox(card)
        self.height_spin.setRange(10.0, 2000.0)
        self.height_spin.setDecimals(1)
        self.height_spin.setSingleStep(1.0)
        self.height_spin.valueChanged.connect(self._emit_sheet_change)

        anchor_lbl = QLabel("Привязка", card)
        anchor_lbl.setObjectName("FieldLabel")
        self.anchor_combo = QComboBox(card)
        for key, title_name in ANCHOR_ITEMS:
            self.anchor_combo.addItem(title_name, key)
        self.anchor_combo.currentIndexChanged.connect(self._emit_sheet_change)

        off_x_lbl = QLabel("Смещение X (мм)", card)
        off_x_lbl.setObjectName("FieldLabel")
        self.offset_x_spin = QDoubleSpinBox(card)
        self.offset_x_spin.setRange(-500.0, 500.0)
        self.offset_x_spin.setDecimals(1)
        self.offset_x_spin.setSingleStep(0.5)
        self.offset_x_spin.valueChanged.connect(self._emit_sheet_change)

        off_y_lbl = QLabel("Смещение Y (мм)", card)
        off_y_lbl.setObjectName("FieldLabel")
        self.offset_y_spin = QDoubleSpinBox(card)
        self.offset_y_spin.setRange(-500.0, 500.0)
        self.offset_y_spin.setDecimals(1)
        self.offset_y_spin.setSingleStep(0.5)
        self.offset_y_spin.valueChanged.connect(self._emit_sheet_change)

        grid.addWidget(fmt_lbl, 0, 0)
        grid.addWidget(self.format_combo, 1, 0)
        grid.addWidget(w_lbl, 0, 1)
        grid.addWidget(self.width_spin, 1, 1)
        grid.addWidget(h_lbl, 0, 2)
        grid.addWidget(self.height_spin, 1, 2)
        grid.addWidget(anchor_lbl, 2, 0)
        grid.addWidget(self.anchor_combo, 3, 0)
        grid.addWidget(off_x_lbl, 2, 1)
        grid.addWidget(self.offset_x_spin, 3, 1)
        grid.addWidget(off_y_lbl, 2, 2)
        grid.addWidget(self.offset_y_spin, 3, 2)
        layout.addLayout(grid)

        a3_row = QHBoxLayout()
        self.a3_two_pass_check = QCheckBox("A3 в 2 прохода по X", card)
        self.a3_two_pass_check.toggled.connect(self._update_dynamic_controls)
        self.a3_two_pass_check.toggled.connect(self._emit_sheet_change)
        self.a3_pass_combo = QComboBox(card)
        self.a3_pass_combo.addItem("Проход 1/2", 1)
        self.a3_pass_combo.addItem("Проход 2/2", 2)
        self.a3_pass_combo.currentIndexChanged.connect(self._emit_sheet_change)
        a3_row.addWidget(self.a3_two_pass_check)
        a3_row.addWidget(self.a3_pass_combo)
        a3_row.addStretch(1)
        layout.addLayout(a3_row)

        self.a3_hint = QLabel(
            "Для A3: сначала выполните проход 1, затем переставьте лист и включите проход 2.",
            card,
        )
        self.a3_hint.setObjectName("HintLabel")
        self.a3_hint.setWordWrap(True)
        layout.addWidget(self.a3_hint)

        self.calibrate_check = QCheckBox("Выполнять калибровку перед рисованием", card)
        self.calibrate_check.toggled.connect(self.calibrate_before_draw_changed.emit)
        layout.addWidget(self.calibrate_check)

        self.wizard_hint = QLabel("Шаг 1: подключитесь. Шаг 2: нажмите «Калибровка 4 угла».", card)
        self.wizard_hint.setObjectName("HintLabel")
        layout.addWidget(self.wizard_hint)

        row = QVBoxLayout()
        self.calibrate_btn = QPushButton("Калибровка 4 угла", card)
        self.calibrate_btn.setObjectName("PrimaryButton")
        self.frame_btn = QPushButton("Рамка активной зоны", card)
        self.calibrate_btn.clicked.connect(self.calibration_requested.emit)
        self.frame_btn.clicked.connect(self.frame_requested.emit)
        row.addWidget(self.calibrate_btn)
        row.addWidget(self.frame_btn)
        layout.addLayout(row)

        root.addWidget(card)
        root.addStretch(1)
        self._update_dynamic_controls()

    def _update_dynamic_controls(self) -> None:
        custom = self.current_sheet_format() == "custom"
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)

        a3 = self.current_sheet_format() == "a3"
        self.a3_two_pass_check.setEnabled(a3)
        self.a3_pass_combo.setEnabled(a3 and self.a3_two_pass_check.isChecked())
        self.a3_hint.setVisible(a3 and self.a3_two_pass_check.isChecked())
        if not a3:
            self.a3_two_pass_check.setChecked(False)
            self.a3_pass_combo.setCurrentIndex(0)

    def _emit_sheet_change(self) -> None:
        fmt = self.current_sheet_format()
        w = float(self.width_spin.value())
        h = float(self.height_spin.value())
        anchor = self.current_anchor()
        off_x = float(self.offset_x_spin.value())
        off_y = float(self.offset_y_spin.value())
        two_pass = bool(self.a3_two_pass_check.isChecked() and fmt == "a3")
        pass_idx = int(self.a3_pass_combo.currentData() or 1)
        self.sheet_changed.emit(fmt, w, h, anchor, off_x, off_y, two_pass, pass_idx)

    def current_sheet_format(self) -> str:
        return str(self.format_combo.currentData() or "a4")

    def current_anchor(self) -> str:
        return str(self.anchor_combo.currentData() or "lower_left")

    def set_sheet_values(
        self,
        fmt: str,
        width_mm: float,
        height_mm: float,
        anchor: str,
        offset_x_mm: float,
        offset_y_mm: float,
        a3_two_pass: bool,
        a3_pass_index: int,
    ) -> None:
        idx = self.format_combo.findData(fmt)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        self.width_spin.setValue(float(width_mm))
        self.height_spin.setValue(float(height_mm))

        a_idx = self.anchor_combo.findData(anchor)
        if a_idx >= 0:
            self.anchor_combo.setCurrentIndex(a_idx)
        self.offset_x_spin.setValue(float(offset_x_mm))
        self.offset_y_spin.setValue(float(offset_y_mm))

        self.a3_two_pass_check.setChecked(bool(a3_two_pass))
        self.a3_pass_combo.setCurrentIndex(0 if int(a3_pass_index) <= 1 else 1)
        self._update_dynamic_controls()

    def set_calibrate_before_draw(self, enabled: bool) -> None:
        self.calibrate_check.setChecked(bool(enabled))

    def set_connected_enabled(self, enabled: bool) -> None:
        self.calibrate_btn.setEnabled(enabled)
        self.frame_btn.setEnabled(enabled)
