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
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("2. Калибровка и активная зона", card)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("Порядок: подключение -> калибровка 4 углов -> запуск файла.", card)
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        basic_grid = QGridLayout()
        basic_grid.setHorizontalSpacing(10)
        basic_grid.setVerticalSpacing(8)

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

        basic_grid.addWidget(fmt_lbl, 0, 0)
        basic_grid.addWidget(w_lbl, 0, 1)
        basic_grid.addWidget(h_lbl, 0, 2)
        basic_grid.addWidget(self.format_combo, 1, 0)
        basic_grid.addWidget(self.width_spin, 1, 1)
        basic_grid.addWidget(self.height_spin, 1, 2)
        layout.addLayout(basic_grid)

        self.advanced_toggle_btn = QPushButton("Расширенные параметры", card)
        self.advanced_toggle_btn.setObjectName("ToggleButton")
        self.advanced_toggle_btn.setCheckable(True)
        self.advanced_toggle_btn.setChecked(False)
        self.advanced_toggle_btn.toggled.connect(self._set_advanced_visible)
        layout.addWidget(self.advanced_toggle_btn)

        self.advanced_box = QFrame(card)
        self.advanced_box.setObjectName("PageSubCard")
        adv = QVBoxLayout(self.advanced_box)
        adv.setContentsMargins(12, 12, 12, 12)
        adv.setSpacing(10)

        anchor_grid = QGridLayout()
        anchor_grid.setHorizontalSpacing(10)
        anchor_grid.setVerticalSpacing(8)

        anchor_lbl = QLabel("Привязка", self.advanced_box)
        anchor_lbl.setObjectName("FieldLabel")
        self.anchor_combo = QComboBox(self.advanced_box)
        for key, title_name in ANCHOR_ITEMS:
            self.anchor_combo.addItem(title_name, key)
        self.anchor_combo.currentIndexChanged.connect(self._emit_sheet_change)

        off_x_lbl = QLabel("Смещение X (мм)", self.advanced_box)
        off_x_lbl.setObjectName("FieldLabel")
        self.offset_x_spin = QDoubleSpinBox(self.advanced_box)
        self.offset_x_spin.setRange(-500.0, 500.0)
        self.offset_x_spin.setDecimals(1)
        self.offset_x_spin.setSingleStep(0.5)
        self.offset_x_spin.valueChanged.connect(self._emit_sheet_change)

        off_y_lbl = QLabel("Смещение Y (мм)", self.advanced_box)
        off_y_lbl.setObjectName("FieldLabel")
        self.offset_y_spin = QDoubleSpinBox(self.advanced_box)
        self.offset_y_spin.setRange(-500.0, 500.0)
        self.offset_y_spin.setDecimals(1)
        self.offset_y_spin.setSingleStep(0.5)
        self.offset_y_spin.valueChanged.connect(self._emit_sheet_change)

        anchor_grid.addWidget(anchor_lbl, 0, 0)
        anchor_grid.addWidget(off_x_lbl, 0, 1)
        anchor_grid.addWidget(off_y_lbl, 0, 2)
        anchor_grid.addWidget(self.anchor_combo, 1, 0)
        anchor_grid.addWidget(self.offset_x_spin, 1, 1)
        anchor_grid.addWidget(self.offset_y_spin, 1, 2)
        adv.addLayout(anchor_grid)

        ll_frame = QFrame(self.advanced_box)
        ll_frame.setObjectName("PageSubCard")
        ll_layout = QVBoxLayout(ll_frame)
        ll_layout.setContentsMargins(10, 10, 10, 10)
        ll_layout.setSpacing(8)

        ll_title = QLabel("Быстро задать лист от 0,0", ll_frame)
        ll_title.setObjectName("FieldLabel")
        ll_layout.addWidget(ll_title)

        ll_hint = QLabel(
            "Поставьте 0,0 в левый нижний угол листа и введите размеры вправо/вверх.",
            ll_frame,
        )
        ll_hint.setObjectName("HintLabel")
        ll_hint.setWordWrap(True)
        ll_layout.addWidget(ll_hint)

        ll_grid = QGridLayout()
        ll_grid.setHorizontalSpacing(8)
        ll_grid.setVerticalSpacing(8)

        right_lbl = QLabel("Вправо X (мм)", ll_frame)
        right_lbl.setObjectName("FieldLabel")
        self.ll_right_spin = QDoubleSpinBox(ll_frame)
        self.ll_right_spin.setRange(10.0, 2000.0)
        self.ll_right_spin.setDecimals(1)
        self.ll_right_spin.setSingleStep(1.0)
        self.ll_right_spin.setValue(165.0)

        up_lbl = QLabel("Вверх Y (мм)", ll_frame)
        up_lbl.setObjectName("FieldLabel")
        self.ll_up_spin = QDoubleSpinBox(ll_frame)
        self.ll_up_spin.setRange(10.0, 2000.0)
        self.ll_up_spin.setDecimals(1)
        self.ll_up_spin.setSingleStep(1.0)
        self.ll_up_spin.setValue(205.0)

        self.ll_apply_btn = QPushButton("Применить как активную область", ll_frame)
        self.ll_apply_btn.clicked.connect(self._apply_from_lower_left)

        ll_grid.addWidget(right_lbl, 0, 0)
        ll_grid.addWidget(up_lbl, 0, 1)
        ll_grid.addWidget(self.ll_right_spin, 1, 0)
        ll_grid.addWidget(self.ll_up_spin, 1, 1)
        ll_grid.addWidget(self.ll_apply_btn, 1, 2)
        ll_layout.addLayout(ll_grid)
        adv.addWidget(ll_frame)

        a3_row = QHBoxLayout()
        a3_row.setSpacing(8)
        self.a3_two_pass_check = QCheckBox("A3 в 2 прохода по X", self.advanced_box)
        self.a3_two_pass_check.toggled.connect(self._update_dynamic_controls)
        self.a3_two_pass_check.toggled.connect(self._emit_sheet_change)
        self.a3_pass_combo = QComboBox(self.advanced_box)
        self.a3_pass_combo.addItem("Проход 1/2", 1)
        self.a3_pass_combo.addItem("Проход 2/2", 2)
        self.a3_pass_combo.currentIndexChanged.connect(self._emit_sheet_change)
        a3_row.addWidget(self.a3_two_pass_check)
        a3_row.addWidget(self.a3_pass_combo)
        a3_row.addStretch(1)
        adv.addLayout(a3_row)

        self.a3_hint = QLabel(
            "Для A3: проход 1, затем переставьте лист и выполните проход 2.",
            self.advanced_box,
        )
        self.a3_hint.setObjectName("HintLabel")
        self.a3_hint.setWordWrap(True)
        adv.addWidget(self.a3_hint)

        layout.addWidget(self.advanced_box)

        self.calibrate_check = QCheckBox("Выполнять калибровку перед рисованием", card)
        self.calibrate_check.toggled.connect(self.calibrate_before_draw_changed.emit)
        layout.addWidget(self.calibrate_check)

        self.wizard_hint = QLabel("Шаг 1: подключитесь. Шаг 2: нажмите «Калибровка 4 угла».", card)
        self.wizard_hint.setObjectName("HintLabel")
        layout.addWidget(self.wizard_hint)

        buttons = QVBoxLayout()
        buttons.setSpacing(8)
        self.calibrate_btn = QPushButton("Калибровка 4 угла", card)
        self.calibrate_btn.setObjectName("PrimaryButton")
        self.frame_btn = QPushButton("Рамка активной зоны", card)
        self.calibrate_btn.clicked.connect(self.calibration_requested.emit)
        self.frame_btn.clicked.connect(self.frame_requested.emit)
        buttons.addWidget(self.calibrate_btn)
        buttons.addWidget(self.frame_btn)
        layout.addLayout(buttons)

        root.addWidget(card)
        root.addStretch(1)
        self._set_advanced_visible(False)
        self._update_dynamic_controls()

    def _set_advanced_visible(self, visible: bool) -> None:
        self.advanced_box.setVisible(bool(visible))

    def _apply_from_lower_left(self) -> None:
        width = max(10.0, float(self.ll_right_spin.value()))
        height = max(10.0, float(self.ll_up_spin.value()))

        self.format_combo.blockSignals(True)
        idx = self.format_combo.findData("custom")
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        self.format_combo.blockSignals(False)

        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

        a_idx = self.anchor_combo.findData("lower_left")
        if a_idx >= 0:
            self.anchor_combo.setCurrentIndex(a_idx)

        self.offset_x_spin.setValue(0.0)
        self.offset_y_spin.setValue(0.0)
        self.wizard_hint.setText(
            f"Лист задан от 0,0: вправо {width:.1f} мм, вверх {height:.1f} мм. "
            "Если нужно сместить лист, откройте расширенные параметры."
        )

        self._update_dynamic_controls()
        self._emit_sheet_change()

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
        self.ll_right_spin.setValue(max(10.0, float(width_mm)))
        self.ll_up_spin.setValue(max(10.0, float(height_mm)))

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
