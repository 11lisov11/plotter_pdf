from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class FilePage(QWidget):
    draw_requested = Signal(Path)
    preview_requested = Signal(Path)
    wear_test_requested = Signal()
    file_changed = Signal(str)
    # quality, force_text_to_path, exact_geometry_mode, safe_travel_lift, strict_one_to_one
    render_settings_changed = Signal(str, bool, bool, bool, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        card = QFrame(self)
        card.setObjectName("PageCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("3. Файл и запуск рисования", card)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("Загрузите PDF/SVG/FRW/CDW/DOC/DOCX и нажмите «Нарисовать».", card)
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(card)
        self.path_edit.setPlaceholderText("Выберите файл для рисования...")
        self.path_edit.textChanged.connect(self._on_path_changed)
        self.pick_btn = QPushButton("Выбрать файл...", card)
        self.pick_btn.clicked.connect(self.pick_file_dialog)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.pick_btn)
        layout.addLayout(row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.preview_btn = QPushButton("Предпросмотр", card)
        self.draw_btn = QPushButton("Нарисовать", card)
        self.draw_btn.setObjectName("PrimaryButton")
        self.wear_btn = QPushButton("Тест износа", card)
        self.preview_btn.clicked.connect(self._emit_preview)
        self.draw_btn.clicked.connect(self._emit_draw)
        self.wear_btn.clicked.connect(self.wear_test_requested.emit)
        action_row.addWidget(self.preview_btn)
        action_row.addWidget(self.draw_btn)
        action_row.addWidget(self.wear_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.advanced_toggle_btn = QPushButton("Расширенные параметры подготовки", card)
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

        quality_grid = QGridLayout()
        quality_grid.setHorizontalSpacing(8)
        quality_grid.setVerticalSpacing(8)

        q_lbl = QLabel("Качество траектории", self.advanced_box)
        q_lbl.setObjectName("FieldLabel")
        self.quality_combo = QComboBox(self.advanced_box)
        self.quality_combo.addItem("Быстро", "fast")
        self.quality_combo.addItem("Баланс", "normal")
        self.quality_combo.addItem("Точно", "high")
        self.quality_combo.currentIndexChanged.connect(self._emit_render_settings_changed)
        self.quality_combo.currentIndexChanged.connect(self._update_quality_hint)

        quality_grid.addWidget(q_lbl, 0, 0)
        quality_grid.addWidget(self.quality_combo, 1, 0)
        adv.addLayout(quality_grid)

        self.quality_hint = QLabel("", self.advanced_box)
        self.quality_hint.setObjectName("HintLabel")
        self.quality_hint.setWordWrap(True)
        adv.addWidget(self.quality_hint)

        self.force_text_to_path_check = QCheckBox("Усилить текст (конвертировать в кривые)", self.advanced_box)
        self.force_text_to_path_check.toggled.connect(self._emit_render_settings_changed)
        adv.addWidget(self.force_text_to_path_check)

        self.exact_geometry_check = QCheckBox("Точный режим чертежа (без синтетических дуг)", self.advanced_box)
        self.exact_geometry_check.toggled.connect(self._emit_render_settings_changed)
        adv.addWidget(self.exact_geometry_check)

        self.safe_travel_lift_check = QCheckBox(
            "Безопасный подъём пера между контурами (меньше артефактов)",
            self.advanced_box,
        )
        self.safe_travel_lift_check.toggled.connect(self._emit_render_settings_changed)
        adv.addWidget(self.safe_travel_lift_check)

        self.strict_one_to_one_check = QCheckBox(
            "Сохранять 1:1 масштаб (если не помещается - клиппинг)",
            self.advanced_box,
        )
        self.strict_one_to_one_check.toggled.connect(self._emit_render_settings_changed)
        adv.addWidget(self.strict_one_to_one_check)

        layout.addWidget(self.advanced_box)

        self.progress = QProgressBar(card)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.metrics = QLabel("Статистика: -", card)
        self.metrics.setObjectName("HintLabel")
        layout.addWidget(self.metrics)

        root.addWidget(card)
        root.addStretch(1)

        self._set_advanced_visible(False)
        self._update_quality_hint()
        self._update_action_buttons()

    def _set_advanced_visible(self, visible: bool) -> None:
        self.advanced_box.setVisible(bool(visible))

    def pick_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл для рисования",
            "",
            "Поддерживаемые (*.pdf *.svg *.frw *.cdw *.doc *.docx);;PDF (*.pdf);;SVG (*.svg);;FRW (*.frw);;CDW (*.cdw);;Word DOC (*.doc);;Word DOCX (*.docx)",
        )
        if path:
            self.path_edit.setText(path)

    def _emit_draw(self) -> None:
        text = self.path_edit.text().strip()
        if not text:
            return
        self.draw_requested.emit(Path(text))

    def _emit_preview(self) -> None:
        text = self.path_edit.text().strip()
        if not text:
            return
        self.preview_requested.emit(Path(text))

    def _on_path_changed(self, value: str) -> None:
        self.file_changed.emit(value)
        self._update_action_buttons()

    def _has_file(self) -> bool:
        return bool(self.path_edit.text().strip())

    def _update_action_buttons(self) -> None:
        has_file = self._has_file()
        self.preview_btn.setEnabled(has_file)
        self.draw_btn.setEnabled(self._connected and has_file)
        self.wear_btn.setEnabled(self._connected)

    def _emit_render_settings_changed(self) -> None:
        quality, force_text_to_path, exact_mode, safe_lift, strict_scale = self.current_render_settings()
        self.render_settings_changed.emit(quality, force_text_to_path, exact_mode, safe_lift, strict_scale)

    def _update_quality_hint(self) -> None:
        quality = str(self.quality_combo.currentData() or "normal")
        if quality == "fast":
            text = "Быстро: меньше команд и выше скорость, но ниже точность мелких деталей."
        elif quality == "high":
            text = "Точно: максимум деталей и аккуратные контуры, но дольше по времени."
        else:
            text = "Баланс: оптимальное соотношение скорости и качества для большинства файлов."
        self.quality_hint.setText(text)

    def current_render_settings(self) -> tuple[str, bool, bool, bool, bool]:
        quality = str(self.quality_combo.currentData() or "normal")
        force_text_to_path = bool(self.force_text_to_path_check.isChecked())
        exact_mode = bool(self.exact_geometry_check.isChecked())
        safe_lift = bool(self.safe_travel_lift_check.isChecked())
        strict_scale = bool(self.strict_one_to_one_check.isChecked())
        return quality, force_text_to_path, exact_mode, safe_lift, strict_scale

    def set_render_settings(
        self,
        quality: str,
        force_text_to_path: bool,
        exact_geometry_mode: bool,
        safe_travel_lift: bool = True,
        strict_one_to_one: bool = False,
    ) -> None:
        idx = self.quality_combo.findData((quality or "normal").strip().lower())
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        self.force_text_to_path_check.setChecked(bool(force_text_to_path))
        self.exact_geometry_check.setChecked(bool(exact_geometry_mode))
        self.safe_travel_lift_check.setChecked(bool(safe_travel_lift))
        self.strict_one_to_one_check.setChecked(bool(strict_one_to_one))

    def set_file_path(self, value: str) -> None:
        self.path_edit.setText(value or "")
        self._update_action_buttons()

    def set_connected_enabled(self, enabled: bool) -> None:
        self._connected = bool(enabled)
        self._update_action_buttons()

    def set_progress_indeterminate(self, active: bool, label: str = "") -> None:
        if active:
            self.progress.setRange(0, 0)
            self.progress.show()
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.hide()
        if label:
            self.metrics.setText(f"Статистика: {label}")

    def set_metrics_text(self, text: str) -> None:
        self.metrics.setText(f"Статистика: {text}")
