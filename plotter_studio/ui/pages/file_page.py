from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtSvgWidgets import QSvgWidget
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class FilePage(QWidget):
    draw_requested = Signal(Path)
    preview_requested = Signal(Path)
    wear_test_requested = Signal()
    file_changed = Signal(str)
    # render_mode, quality, force_text_to_path, exact_geometry_mode, safe_travel_lift, strict_one_to_one,
    # handwriting_enabled, handwriting_font, handwriting_formula_font, image_contours_mode, source_page_index
    render_settings_changed = Signal(str, str, bool, bool, bool, bool, bool, str, str, str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._last_preview_path = ""
        self._default_handwriting_fonts = [
            "Marck Script",
            "Bad Script",
            "Caveat",
            "Neucha",
            "Segoe Script",
            "Comic Sans MS",
        ]
        self._default_formula_fonts = [
            "Times New Roman",
            "Cambria Math",
            "STIX Two Math",
            "Arial",
        ]

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

        hint = QLabel(
            "Загрузите PDF/SVG/FRW/CDW/DOC/DOCX. Выберите режим: «Чертеж» для технички "
            "или «Рукописный» для конспекта. Для PDF с уже кривым текстом смена шрифта недоступна.",
            card,
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_lbl = QLabel("Режим подготовки", card)
        mode_lbl.setObjectName("FieldLabel")
        self.render_mode_combo = QComboBox(card)
        self.render_mode_combo.addItem("Чертеж (как раньше)", "drawing")
        self.render_mode_combo.addItem("Рукописный текст", "handwriting")
        self.render_mode_combo.currentIndexChanged.connect(self._on_render_mode_changed)
        self.render_mode_combo.currentIndexChanged.connect(self._emit_render_settings_changed)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self.render_mode_combo, 1)
        layout.addLayout(mode_row)

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

        page_row = QHBoxLayout()
        page_row.setSpacing(8)
        page_lbl = QLabel("Страница", card)
        page_lbl.setObjectName("FieldLabel")
        self.page_spin = QSpinBox(card)
        self.page_spin.setRange(1, 9999)
        self.page_spin.setValue(1)
        self.page_spin.setSingleStep(1)
        self.page_spin.setToolTip("Номер страницы для Word/PDF (постраничная отправка).")
        self.page_spin.valueChanged.connect(self._emit_render_settings_changed)
        self.page_hint = QLabel("Постраничный режим: Word/PDF", card)
        self.page_hint.setObjectName("HintLabel")
        page_row.addWidget(page_lbl)
        page_row.addWidget(self.page_spin)
        page_row.addWidget(self.page_hint, 1)
        layout.addLayout(page_row)

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

        self.handwriting_check = QCheckBox("Рукописный режим текста", self.advanced_box)
        self.handwriting_check.toggled.connect(self._emit_render_settings_changed)
        self.handwriting_check.toggled.connect(self._sync_handwriting_state)
        adv.addWidget(self.handwriting_check)

        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        font_lbl = QLabel("Шрифт", self.advanced_box)
        font_lbl.setObjectName("FieldLabel")
        self.handwriting_font_combo = QComboBox(self.advanced_box)
        self.handwriting_font_combo.setEditable(True)
        self.handwriting_font_combo.currentTextChanged.connect(self._emit_render_settings_changed)
        self.handwriting_font_pick_btn = QPushButton("Файл...", self.advanced_box)
        self.handwriting_font_pick_btn.clicked.connect(self._pick_handwriting_font_file)
        self.handwriting_font_refresh_btn = QPushButton("Обновить", self.advanced_box)
        self.handwriting_font_refresh_btn.clicked.connect(self._refresh_handwriting_fonts)
        font_row.addWidget(font_lbl)
        font_row.addWidget(self.handwriting_font_combo, 1)
        font_row.addWidget(self.handwriting_font_pick_btn)
        font_row.addWidget(self.handwriting_font_refresh_btn)
        adv.addLayout(font_row)

        formula_font_row = QHBoxLayout()
        formula_font_row.setSpacing(8)
        formula_font_lbl = QLabel("Шрифт формул", self.advanced_box)
        formula_font_lbl.setObjectName("FieldLabel")
        self.handwriting_formula_font_combo = QComboBox(self.advanced_box)
        self.handwriting_formula_font_combo.setEditable(True)
        self.handwriting_formula_font_combo.addItems(self._default_formula_fonts)
        self.handwriting_formula_font_combo.setCurrentText("Times New Roman")
        self.handwriting_formula_font_combo.currentTextChanged.connect(self._emit_render_settings_changed)
        formula_font_row.addWidget(formula_font_lbl)
        formula_font_row.addWidget(self.handwriting_formula_font_combo, 1)
        adv.addLayout(formula_font_row)

        contour_row = QHBoxLayout()
        contour_row.setSpacing(8)
        contour_lbl = QLabel("Картинки", self.advanced_box)
        contour_lbl.setObjectName("FieldLabel")
        self.image_contours_mode_combo = QComboBox(self.advanced_box)
        self.image_contours_mode_combo.addItem("Контуры: всегда", "always")
        self.image_contours_mode_combo.addItem("Контуры: только Word", "word_only")
        self.image_contours_mode_combo.addItem("Контуры: выкл", "off")
        self.image_contours_mode_combo.currentIndexChanged.connect(self._emit_render_settings_changed)
        contour_row.addWidget(contour_lbl)
        contour_row.addWidget(self.image_contours_mode_combo, 1)
        adv.addLayout(contour_row)

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

        self.preview_card = QFrame(card)
        self.preview_card.setObjectName("PageSubCard")
        preview_layout = QVBoxLayout(self.preview_card)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(6)
        preview_title = QLabel("Предпросмотр вектора", self.preview_card)
        preview_title.setObjectName("FieldLabel")
        preview_layout.addWidget(preview_title)
        self.preview_path_label = QLabel("Нет предпросмотра", self.preview_card)
        self.preview_path_label.setObjectName("HintLabel")
        self.preview_path_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_path_label)
        self.preview_svg = QSvgWidget(self.preview_card)
        self.preview_svg.setMinimumHeight(240)
        self.preview_svg.setMaximumHeight(360)
        preview_layout.addWidget(self.preview_svg)
        layout.addWidget(self.preview_card)

        root.addWidget(card)
        root.addStretch(1)

        self._set_advanced_visible(False)
        self._populate_handwriting_font_choices()
        self._update_quality_hint()
        self._apply_render_mode_preset()
        self._sync_input_specific_controls()
        self._set_preview_placeholder()
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
        self._sync_input_specific_controls()
        self._update_action_buttons()

    def _has_file(self) -> bool:
        return bool(self.path_edit.text().strip())

    def _update_action_buttons(self) -> None:
        has_file = self._has_file()
        self.preview_btn.setEnabled(has_file)
        self.draw_btn.setEnabled(self._connected and has_file)
        self.wear_btn.setEnabled(self._connected)

    def _emit_render_settings_changed(self) -> None:
        (
            render_mode,
            quality,
            force_text_to_path,
            exact_mode,
            safe_lift,
            strict_scale,
            handwriting_enabled,
            handwriting_font,
            handwriting_formula_font,
            image_contours_mode,
            source_page_index,
        ) = self.current_render_settings()
        self.render_settings_changed.emit(
            render_mode,
            quality,
            force_text_to_path,
            exact_mode,
            safe_lift,
            strict_scale,
            handwriting_enabled,
            handwriting_font,
            handwriting_formula_font,
            image_contours_mode,
            source_page_index,
        )

    def current_render_mode(self) -> str:
        mode = str(self.render_mode_combo.currentData() or "drawing").strip().lower()
        return mode if mode in {"drawing", "handwriting"} else "drawing"

    def _on_render_mode_changed(self) -> None:
        self._apply_render_mode_preset()

    def _apply_render_mode_preset(self) -> None:
        if not hasattr(self, "handwriting_check") or not hasattr(self, "exact_geometry_check"):
            return
        mode = self.current_render_mode()
        if mode == "drawing":
            if self.handwriting_check.isChecked():
                self.handwriting_check.setChecked(False)
            if not self.exact_geometry_check.isChecked():
                self.exact_geometry_check.setChecked(True)
            self.handwriting_check.setEnabled(False)
            self.exact_geometry_check.setEnabled(False)
        else:
            if not self.handwriting_check.isChecked():
                self.handwriting_check.setChecked(True)
            if self.exact_geometry_check.isChecked():
                self.exact_geometry_check.setChecked(False)
            self.handwriting_check.setEnabled(False)
            self.exact_geometry_check.setEnabled(False)
        self._sync_handwriting_state()

    def _sync_handwriting_state(self, _checked: bool | None = None) -> None:
        enabled = bool(self.handwriting_check.isChecked()) and self.current_render_mode() == "handwriting"
        self.handwriting_font_combo.setEnabled(enabled)
        self.handwriting_font_pick_btn.setEnabled(enabled)
        self.handwriting_font_refresh_btn.setEnabled(enabled)
        self.handwriting_formula_font_combo.setEnabled(enabled)

    def _sync_input_specific_controls(self) -> None:
        text = (self.path_edit.text() or "").strip()
        ext = Path(text).suffix.lower() if text else ""
        page_related = ext in {".pdf", ".doc", ".docx"}
        self.page_spin.setEnabled(page_related)
        if not page_related:
            self.page_hint.setText("Для SVG/FRW/CDW используется 1 страница")
        else:
            self.page_hint.setText("Постраничный режим: Word/PDF")

    @staticmethod
    def _project_root() -> Path:
        # plotter_studio/ui/pages/file_page.py -> project root
        return Path(__file__).resolve().parents[3]

    def _discover_local_handwriting_fonts(self) -> list[str]:
        root = self._project_root()
        candidates: list[Path] = []
        for pattern in ("*.ttf", "*.otf", "*.ttc"):
            candidates.extend(root.glob(pattern))
            candidates.extend((root / "data" / "fonts").glob(pattern))

        out: list[str] = []
        seen: set[str] = set()
        for p in sorted(candidates, key=lambda v: v.name.lower()):
            if not p.is_file():
                continue
            name = p.name
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
        return out

    def _populate_handwriting_font_choices(self) -> None:
        current = (self.handwriting_font_combo.currentText() or "").strip() or "Marck Script"
        merged: list[str] = []
        seen: set[str] = set()
        for name in [*self._default_handwriting_fonts, *self._discover_local_handwriting_fonts()]:
            item = (name or "").strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

        self.handwriting_font_combo.blockSignals(True)
        self.handwriting_font_combo.clear()
        self.handwriting_font_combo.addItems(merged)
        self.handwriting_font_combo.setCurrentText(current)
        self.handwriting_font_combo.blockSignals(False)

    def _refresh_handwriting_fonts(self) -> None:
        self._populate_handwriting_font_choices()
        self._emit_render_settings_changed()

    def _pick_handwriting_font_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите рукописный шрифт",
            str(self._project_root()),
            "Font files (*.ttf *.otf *.ttc);;All files (*.*)",
        )
        if not path:
            return
        value = str(Path(path))
        if self.handwriting_font_combo.findText(value) < 0:
            self.handwriting_font_combo.addItem(value)
        self.handwriting_font_combo.setCurrentText(value)
        self._emit_render_settings_changed()

    def _update_quality_hint(self) -> None:
        quality = str(self.quality_combo.currentData() or "normal")
        if quality == "fast":
            text = "Быстро: меньше команд и выше скорость, но ниже точность мелких деталей."
        elif quality == "high":
            text = "Точно: максимум деталей и аккуратные контуры, но дольше по времени."
        else:
            text = "Баланс: оптимальное соотношение скорости и качества для большинства файлов."
        self.quality_hint.setText(text)

    def current_render_settings(self) -> tuple[str, str, bool, bool, bool, bool, bool, str, str, str, int]:
        render_mode = self.current_render_mode()
        quality = str(self.quality_combo.currentData() or "normal")
        force_text_to_path = bool(self.force_text_to_path_check.isChecked())
        exact_mode = bool(self.exact_geometry_check.isChecked())
        safe_lift = bool(self.safe_travel_lift_check.isChecked())
        strict_scale = bool(self.strict_one_to_one_check.isChecked())
        handwriting_enabled = bool(self.handwriting_check.isChecked())
        handwriting_font = (self.handwriting_font_combo.currentText() or "").strip() or "Marck Script"
        handwriting_formula_font = (
            (self.handwriting_formula_font_combo.currentText() or "").strip() or "Times New Roman"
        )
        image_contours_mode = str(self.image_contours_mode_combo.currentData() or "always")
        source_page_index = max(1, int(self.page_spin.value()))
        return (
            render_mode,
            quality,
            force_text_to_path,
            exact_mode,
            safe_lift,
            strict_scale,
            handwriting_enabled,
            handwriting_font,
            handwriting_formula_font,
            image_contours_mode,
            source_page_index,
        )

    def set_render_settings(
        self,
        render_mode: str,
        quality: str,
        force_text_to_path: bool,
        exact_geometry_mode: bool,
        safe_travel_lift: bool = True,
        strict_one_to_one: bool = False,
        handwriting_enabled: bool = False,
        handwriting_font: str = "Marck Script",
        handwriting_formula_font: str = "Times New Roman",
        image_contours_mode: str = "always",
        source_page_index: int = 1,
    ) -> None:
        mode_idx = self.render_mode_combo.findData((render_mode or "drawing").strip().lower())
        if mode_idx >= 0:
            self.render_mode_combo.setCurrentIndex(mode_idx)
        idx = self.quality_combo.findData((quality or "normal").strip().lower())
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        self.force_text_to_path_check.setChecked(bool(force_text_to_path))
        self.exact_geometry_check.setChecked(bool(exact_geometry_mode))
        self.safe_travel_lift_check.setChecked(bool(safe_travel_lift))
        self.strict_one_to_one_check.setChecked(bool(strict_one_to_one))
        self.handwriting_check.setChecked(bool(handwriting_enabled))
        self.handwriting_font_combo.setCurrentText((handwriting_font or "").strip() or "Marck Script")
        self.handwriting_formula_font_combo.setCurrentText(
            (handwriting_formula_font or "").strip() or "Times New Roman"
        )
        self.page_spin.setValue(max(1, int(source_page_index or 1)))
        im_idx = self.image_contours_mode_combo.findData((image_contours_mode or "always").strip().lower())
        if im_idx >= 0:
            self.image_contours_mode_combo.setCurrentIndex(im_idx)
        self._apply_render_mode_preset()

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

    def _set_preview_placeholder(self, text: str = "Нет предпросмотра") -> None:
        self.preview_path_label.setText(text)
        placeholder = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="220" viewBox="0 0 420 220">'
            '<rect x="0" y="0" width="420" height="220" fill="#f4f5f7"/>'
            '<text x="16" y="34" font-size="18" fill="#64748b">Предпросмотр появится здесь</text>'
            "</svg>"
        )
        self.preview_svg.load(bytearray(placeholder, encoding="utf-8"))

    def set_preview_path(self, path: str) -> None:
        self._last_preview_path = str(path or "").strip()
        if not self._last_preview_path:
            self._set_preview_placeholder()
            return
        p = Path(self._last_preview_path)
        if not p.exists():
            self._set_preview_placeholder(f"Предпросмотр не найден: {p}")
            return
        target = p
        if target.suffix.lower() == ".pdf":
            candidate_svg = target.with_suffix(".svg")
            if candidate_svg.exists():
                target = candidate_svg
        if target.suffix.lower() != ".svg":
            self._set_preview_placeholder(f"Предпросмотр: {p.name}")
            return
        try:
            self.preview_svg.load(str(target))
            self.preview_path_label.setText(f"Файл: {target}")
        except Exception:
            self._set_preview_placeholder(f"Не удалось загрузить предпросмотр: {target}")
