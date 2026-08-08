from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import fitz
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.plotter_backend import discovery as discovery_mod
from src.plotter_backend.jobs import JobResult, JobSettings
from src.plotter_backend.machine import profiles as machine_profiles_mod

from .settings import load_gui_settings, save_gui_settings
from .viewmodels import JobViewModel, SelfCheckViewModel


class _Worker(QThread):
    finished_result = Signal(object)

    def __init__(self, action, parent=None) -> None:
        super().__init__(parent)
        self._action = action

    def run(self) -> None:
        self.finished_result.emit(self._action())


class PdfPreviewView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self._has_page = False

    def show_pdf(self, path: Path, page_index: int = 0) -> None:
        with fitz.open(path) as doc:
            if not doc.page_count:
                raise ValueError("В PDF нет страниц.")
            page = doc[min(max(0, page_index), doc.page_count - 1)]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        self.scene().clear()
        self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.scene().itemsBoundingRect())
        self._has_page = True
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        if not self._has_page:
            return super().wheelEvent(event)
        self.scale(1.18 if event.angleDelta().y() > 0 else 1.0 / 1.18, 1.18 if event.angleDelta().y() > 0 else 1.0 / 1.18)


_MACHINE_PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "machine_profiles.json"


def _machine_profile_choices() -> list[tuple[str, str]]:
    profiles = machine_profiles_mod.load_machine_profiles(_MACHINE_PROFILE_PATH)
    order = ["a4_desktop", "a2_corexy"] + [name for name in sorted(profiles) if name not in {"a4_desktop", "a2_corexy"}]
    return [(name, str(profiles[name].get("label") or name)) for name in order if name in profiles]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Plotter PDF — раскладка и управление плоттером")
        self.resize(1380, 900)
        self.settings_data = load_gui_settings()
        self.vm = JobViewModel(self._settings_from_ui_data())
        self.self_check_vm = SelfCheckViewModel()
        self._worker: _Worker | None = None
        self._current_preview_pdf: Path | None = None
        self._build_ui()
        self._sync_draw_gate()

    def _settings_from_ui_data(self) -> JobSettings:
        data = self.settings_data
        return JobSettings(
            input_path=data.get("input_path") or None,
            input_paths=[str(value) for value in data.get("input_paths") or []],
            input_pages=[int(value) for value in data.get("input_pages") or []],
            input_rotations=[int(value) for value in data.get("input_rotations") or []],
            output_dir=data.get("output_dir") or "_plotter_jobs",
            com=data.get("com") or None,
            baud=str(data.get("baud") or "115200"),
            machine_profile=str(data.get("machine_profile") or "a4_desktop"),
            calibration_layout=str(data.get("calibration_layout") or "sheet"),
            sheet_format=str(data.get("sheet_format") or "a4"),
            sheet_width_mm=data.get("sheet_width_mm"),
            sheet_height_mm=data.get("sheet_height_mm"),
            sheet_anchor=str(data.get("sheet_anchor") or "center"),
            sheet_offset_x_mm=float(data.get("sheet_offset_x_mm") or 0.0),
            sheet_offset_y_mm=float(data.get("sheet_offset_y_mm") or 0.0),
            pass_cols=int(data.get("pass_cols") or 1),
            pass_rows=int(data.get("pass_rows") or 1),
            pass_col=int(data.get("pass_col") or 1),
            pass_row=int(data.get("pass_row") or 1),
            tool=str(data.get("tool") or "pen"),
            handwriting=bool(data.get("handwriting")),
            quality=str(data.get("quality") or "normal"),
            draw_order=str(data.get("draw_order") or "auto"),
            open_preview=bool(data.get("open_preview")),
            layout_mode=str(data.get("layout_mode") or "auto"),
            layout_page=int(data.get("layout_page") or 1),
            layout_margin_mm=float(data.get("layout_margin_mm") or 0.0),
            layout_gap_mm=float(data.get("layout_gap_mm") or 0.0),
            output_rotation_deg=int(data.get("output_rotation_deg") or 0),
            mirror_x=bool(data.get("mirror_x")),
            mirror_y=bool(data.get("mirror_y")),
        )

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        controls_scroll = QScrollArea(splitter)
        controls_scroll.setWidgetResizable(True)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self._build_files_group())
        controls_layout.addWidget(self._build_layout_group())
        controls_layout.addWidget(self._build_machine_group())
        controls_layout.addWidget(self._build_actions_group())
        controls_layout.addStretch(1)
        controls_scroll.setWidget(controls)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.status_label = QLabel("Выберите PDF и соберите раскладку.")
        self.status_label.setWordWrap(True)
        right_layout.addWidget(self.status_label)
        self.tabs = QTabWidget()
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        preview_toolbar = QHBoxLayout()
        self.preview_caption = QLabel("Предпросмотр ещё не сформирован")
        self.open_pdf_btn = QPushButton("Открыть PDF отдельно")
        self.open_pdf_btn.setEnabled(False)
        self.open_pdf_btn.clicked.connect(self._open_current_preview)
        preview_toolbar.addWidget(self.preview_caption)
        preview_toolbar.addStretch(1)
        preview_toolbar.addWidget(self.open_pdf_btn)
        preview_layout.addLayout(preview_toolbar)
        self.preview_view = PdfPreviewView()
        preview_layout.addWidget(self.preview_view, 1)
        self.tabs.addTab(preview_tab, "Лист и итоговый G-code")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, "Журнал")
        right_layout.addWidget(self.tabs, 1)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(right)
        splitter.setSizes([470, 910])
        self.setCentralWidget(splitter)

    def _build_files_group(self) -> QGroupBox:
        group = QGroupBox("1. Файлы и порядок страниц")
        layout = QVBoxLayout(group)
        self.file_list = QListWidget()
        self.file_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.file_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.file_list.model().rowsMoved.connect(lambda *_args: self._layout_changed())
        layout.addWidget(self.file_list)
        grid = QGridLayout()
        actions = (
            ("Добавить PDF", self._pick_inputs, 0, 0),
            ("Удалить", self._remove_selected, 0, 1),
            ("Выше", lambda: self._move_selected(-1), 1, 0),
            ("Ниже", lambda: self._move_selected(1), 1, 1),
            ("↶ 90°", lambda: self._rotate_selected(-90), 2, 0),
            ("↷ 90°", lambda: self._rotate_selected(90), 2, 1),
            ("Все на 180°", self._rotate_all_180, 3, 0),
            ("Сбросить повороты", self._reset_rotations, 3, 1),
        )
        for text, callback, row, col in actions:
            button = QPushButton(text)
            button.clicked.connect(callback)
            grid.addWidget(button, row, col)
        layout.addLayout(grid)
        self._restore_items()
        return group

    def _build_layout_group(self) -> QGroupBox:
        group = QGroupBox("2. Формат и раскладка")
        form = QFormLayout(group)
        self.sheet_combo = QComboBox()
        self.sheet_combo.addItem("A4 — один лист", "a4")
        self.sheet_combo.addItem("A3 — до двух страниц", "a3")
        self.sheet_combo.addItem("A2 — до четырёх страниц", "a2")
        self.sheet_combo.setCurrentIndex(max(0, self.sheet_combo.findData(self.vm.settings.sheet_format)))
        self.layout_combo = QComboBox()
        for label, value in (
            ("Автоматически, максимальное вписание", "auto"),
            ("Горизонтально", "horizontal"),
            ("Вертикально", "vertical"),
            ("Сетка 2×2", "grid"),
            ("Одна страница", "single"),
        ):
            self.layout_combo.addItem(label, value)
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(self.vm.settings.layout_mode)))
        self.layout_page = QSpinBox()
        self.layout_page.setRange(1, 99)
        self.layout_page.setValue(max(1, self.vm.settings.layout_page))
        self.margin_spin = self._double_spin(self.vm.settings.layout_margin_mm)
        self.gap_spin = self._double_spin(self.vm.settings.layout_gap_mm)
        form.addRow("Итоговый формат:", self.sheet_combo)
        form.addRow("Размещение:", self.layout_combo)
        form.addRow("Выходной лист:", self.layout_page)
        form.addRow("Внешнее поле:", self.margin_spin)
        form.addRow("Зазор между файлами:", self.gap_spin)
        self.layout_preview_btn = QPushButton("Собрать и показать PDF раскладки")
        self.layout_preview_btn.clicked.connect(self._run_layout_preview)
        form.addRow(self.layout_preview_btn)
        for widget in (self.sheet_combo, self.layout_combo, self.layout_page, self.margin_spin, self.gap_spin):
            signal = getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None)
            signal.connect(self._layout_changed)
        return group

    def _build_machine_group(self) -> QGroupBox:
        group = QGroupBox("3. Станок, проход и ориентация")
        form = QFormLayout(group)
        self.machine_combo = QComboBox()
        for name, label in _machine_profile_choices():
            self.machine_combo.addItem(label, name)
        self.machine_combo.setCurrentIndex(max(0, self.machine_combo.findData(self.vm.settings.machine_profile)))
        self.com_combo = QComboBox()
        self.com_combo.setEditable(True)
        self._refresh_com_ports(self.vm.settings.com or "", sync=False)
        com_widget = QWidget()
        com_row = QHBoxLayout(com_widget)
        com_row.setContentsMargins(0, 0, 0, 0)
        com_row.addWidget(self.com_combo)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(lambda: self._refresh_com_ports(self.com_combo.currentText()))
        com_row.addWidget(refresh)
        self.baud_edit = QLineEdit(self.vm.settings.baud)
        self.calibration_combo = QComboBox()
        self.calibration_combo.addItems(["sheet", "a2", "a2_2xa3", "a2_4xa4"])
        self.calibration_combo.setCurrentText(self.vm.settings.calibration_layout)
        self.pass_cols = self._spin(self.vm.settings.pass_cols)
        self.pass_rows = self._spin(self.vm.settings.pass_rows)
        self.pass_col = self._spin(self.vm.settings.pass_col)
        self.pass_row = self._spin(self.vm.settings.pass_row)
        self.output_rotation = QComboBox()
        for value in (0, 90, 180, 270):
            self.output_rotation.addItem(f"{value}°", value)
        self.output_rotation.setCurrentIndex(max(0, self.output_rotation.findData(self.vm.settings.output_rotation_deg)))
        self.mirror_x = QCheckBox("Отразить по X")
        self.mirror_y = QCheckBox("Отразить по Y")
        self.mirror_x.setChecked(self.vm.settings.mirror_x)
        self.mirror_y.setChecked(self.vm.settings.mirror_y)
        mirror_widget = QWidget()
        mirror_row = QHBoxLayout(mirror_widget)
        mirror_row.setContentsMargins(0, 0, 0, 0)
        mirror_row.addWidget(self.mirror_x)
        mirror_row.addWidget(self.mirror_y)
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["pen", "pencil"])
        self.tool_combo.setCurrentText(self.vm.settings.tool)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["fast", "normal", "high"])
        self.quality_combo.setCurrentText(self.vm.settings.quality)
        self.handwriting = QCheckBox("Рукописный текст")
        self.handwriting.setChecked(self.vm.settings.handwriting)
        form.addRow("Плоттер:", self.machine_combo)
        form.addRow("COM-порт:", com_widget)
        form.addRow("Скорость порта:", self.baud_edit)
        form.addRow("Калибровка:", self.calibration_combo)
        form.addRow("Сетка проходов cols/rows:", self._pair(self.pass_cols, self.pass_rows))
        form.addRow("Текущий проход col/row:", self._pair(self.pass_col, self.pass_row))
        form.addRow("Поворот всего задания:", self.output_rotation)
        form.addRow("Отражение на станке:", mirror_widget)
        form.addRow("Инструмент:", self.tool_combo)
        form.addRow("Качество:", self.quality_combo)
        form.addRow("Текст:", self.handwriting)
        self.machine_combo.currentIndexChanged.connect(self._machine_or_sheet_changed)
        self.sheet_combo.currentIndexChanged.connect(self._machine_or_sheet_changed)
        for widget in (
            self.com_combo,
            self.baud_edit,
            self.calibration_combo,
            self.pass_cols,
            self.pass_rows,
            self.pass_col,
            self.pass_row,
            self.output_rotation,
            self.mirror_x,
            self.mirror_y,
            self.tool_combo,
            self.quality_combo,
            self.handwriting,
        ):
            signal = getattr(widget, "textChanged", None) or getattr(widget, "currentIndexChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "stateChanged", None)
            signal.connect(self._sync_from_ui)
        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("4. Проверка и рисование")
        layout = QVBoxLayout(group)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(str(self.vm.settings.output_dir))
        output_row.addWidget(self.output_edit)
        choose = QPushButton("Папка")
        choose.clicked.connect(self._pick_output)
        output_row.addWidget(choose)
        layout.addLayout(output_row)
        grid = QGridLayout()
        self.self_check_btn = QPushButton("Самопроверка")
        self.preview_btn = QPushButton("Проверить итоговый G-code в PDF")
        self.generate_btn = QPushButton("Сформировать G-code")
        self.draw_btn = QPushButton("Рисовать выбранный проход")
        self.release_btn = QPushButton("Отпустить двигатели")
        self.stop_btn = QPushButton("Аварийный стоп")
        for button, row, col in (
            (self.self_check_btn, 0, 0),
            (self.preview_btn, 0, 1),
            (self.generate_btn, 1, 0),
            (self.draw_btn, 1, 1),
            (self.release_btn, 2, 0),
            (self.stop_btn, 2, 1),
        ):
            grid.addWidget(button, row, col)
        layout.addLayout(grid)
        self.self_check_btn.clicked.connect(self._run_self_check)
        self.preview_btn.clicked.connect(lambda: self._run_job(self.vm.run_preview))
        self.generate_btn.clicked.connect(lambda: self._run_job(self.vm.generate_gcode))
        self.draw_btn.clicked.connect(self._confirm_and_draw)
        self.release_btn.clicked.connect(lambda: self._append_log("Двигатели отпускаются штатной командой после завершения задания."))
        self.stop_btn.clicked.connect(lambda: QMessageBox.warning(self, "Аварийный стоп", "Нажмите аппаратный аварийный стоп или отключите питание станка."))
        return group

    @staticmethod
    def _spin(value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(1, 10)
        widget.setValue(value)
        return widget

    @staticmethod
    def _double_spin(value: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(0.0, 30.0)
        widget.setDecimals(1)
        widget.setSuffix(" мм")
        widget.setValue(value)
        return widget

    @staticmethod
    def _pair(left: QWidget, right: QWidget) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(left)
        layout.addWidget(QLabel("/"))
        layout.addWidget(right)
        return box

    def _restore_items(self) -> None:
        for path, page, rotation in self.vm.settings.normalized_layout_items():
            if path.is_file() and path.suffix.lower() == ".pdf":
                self._add_list_item(path, page, rotation)

    def _add_list_item(self, path: Path, page_index: int, rotation: int) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, {"path": str(path), "page": int(page_index), "rotation": int(rotation) % 360})
        self.file_list.addItem(item)
        self._refresh_item_text(item)

    @staticmethod
    def _refresh_item_text(item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        item.setText(f"{Path(data['path']).name}  •  стр. {int(data['page']) + 1}  •  {int(data['rotation']) % 360}°")
        item.setToolTip(str(data["path"]))

    def _items(self) -> list[tuple[Path, int, int]]:
        output = []
        for index in range(self.file_list.count()):
            data = self.file_list.item(index).data(Qt.ItemDataRole.UserRole)
            path = Path(data["path"])
            if path.is_file() and path.suffix.lower() == ".pdf":
                output.append((path, int(data["page"]), int(data["rotation"])))
        return output

    def _pick_inputs(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите PDF", "", "PDF (*.pdf)")
        for raw_path in paths:
            path = Path(raw_path)
            try:
                with fitz.open(path) as doc:
                    for page_index in range(doc.page_count):
                        self._add_list_item(path, page_index, 0)
            except Exception as exc:
                QMessageBox.warning(self, "Не удалось открыть PDF", f"{path}\n\n{exc}")
        if paths:
            self._layout_changed()

    def _remove_selected(self) -> None:
        row = self.file_list.currentRow()
        if row >= 0:
            self.file_list.takeItem(row)
            self._layout_changed()

    def _move_selected(self, delta: int) -> None:
        row = self.file_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.file_list.count():
            return
        item = self.file_list.takeItem(row)
        self.file_list.insertItem(target, item)
        self.file_list.setCurrentRow(target)
        self._layout_changed()

    def _rotate_selected(self, delta: int) -> None:
        item = self.file_list.currentItem()
        if item is None:
            return
        data = dict(item.data(Qt.ItemDataRole.UserRole))
        data["rotation"] = (int(data["rotation"]) + delta) % 360
        item.setData(Qt.ItemDataRole.UserRole, data)
        self._refresh_item_text(item)
        self._layout_changed()

    def _rotate_all_180(self) -> None:
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            data = dict(item.data(Qt.ItemDataRole.UserRole))
            data["rotation"] = (int(data["rotation"]) + 180) % 360
            item.setData(Qt.ItemDataRole.UserRole, data)
            self._refresh_item_text(item)
        self._layout_changed()

    def _reset_rotations(self) -> None:
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            data = dict(item.data(Qt.ItemDataRole.UserRole))
            data["rotation"] = 0
            item.setData(Qt.ItemDataRole.UserRole, data)
            self._refresh_item_text(item)
        self._layout_changed()

    def _selected_machine_profile(self) -> str:
        return str(self.machine_combo.currentData() or "a4_desktop")

    def _machine_or_sheet_changed(self, *_args) -> None:
        profile = self._selected_machine_profile()
        fmt = str(self.sheet_combo.currentData() or "a4")
        if profile == "a4_desktop":
            cols, rows = {"a4": (1, 1), "a3": (2, 1), "a2": (2, 2)}[fmt]
            calibration = "sheet"
        else:
            cols, rows = 1, 1
            calibration = {"a4": "a2_4xa4", "a3": "a2_2xa3", "a2": "a2"}[fmt]
        for widget, value in ((self.pass_cols, cols), (self.pass_rows, rows), (self.pass_col, 1), (self.pass_row, 1)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.calibration_combo.setCurrentText(calibration)
        self._layout_changed()

    def _layout_changed(self, *_args) -> None:
        self.vm.preflight_ok = False
        self._sync_from_ui()
        self.status_label.setText("Раскладка изменена. Обновите PDF предпросмотра перед рисованием.")

    def _sync_from_ui(self, *_args) -> None:
        if not hasattr(self, "file_list"):
            return
        items = [(path, page, rotation) for path, page, rotation in self._items()]
        current_items = self.vm.settings.normalized_layout_items()
        if items != current_items:
            self.vm.set_layout_items(items)
        if hasattr(self, "output_edit"):
            self.vm.settings.output_dir = self.output_edit.text().strip() or "_plotter_jobs"
        if hasattr(self, "com_combo"):
            self.vm.settings.com = str(self.com_combo.currentData() or self.com_combo.currentText()).split(" ", 1)[0].strip() or None
            self.vm.settings.baud = self.baud_edit.text().strip() or "115200"
            self.vm.settings.machine_profile = self._selected_machine_profile()
            self.vm.settings.calibration_layout = self.calibration_combo.currentText()
            self.vm.settings.pass_cols = self.pass_cols.value()
            self.vm.settings.pass_rows = self.pass_rows.value()
            self.vm.settings.pass_col = self.pass_col.value()
            self.vm.settings.pass_row = self.pass_row.value()
            self.vm.settings.output_rotation_deg = int(self.output_rotation.currentData() or 0)
            self.vm.settings.mirror_x = self.mirror_x.isChecked()
            self.vm.settings.mirror_y = self.mirror_y.isChecked()
            self.vm.settings.tool = self.tool_combo.currentText()
            self.vm.settings.quality = self.quality_combo.currentText()
            self.vm.settings.handwriting = self.handwriting.isChecked()
        self.vm.settings.sheet_format = str(self.sheet_combo.currentData() or "a4")
        self.vm.settings.layout_mode = str(self.layout_combo.currentData() or "auto")
        self.vm.settings.layout_page = self.layout_page.value()
        self.vm.settings.layout_margin_mm = self.margin_spin.value()
        self.vm.settings.layout_gap_mm = self.gap_spin.value()
        save_gui_settings(asdict(self.vm.settings))
        self._sync_draw_gate()

    def _run_layout_preview(self) -> None:
        self._sync_from_ui()
        if not self.vm.has_input():
            QMessageBox.warning(self, "Нет файлов", "Добавьте хотя бы один существующий PDF.")
            return
        self._handle_result(self.vm.build_layout_preview(), prefer_layout=True)

    def _run_job(self, action) -> None:
        self._sync_from_ui()
        if not self.vm.has_input():
            QMessageBox.warning(self, "Нет файлов", "Добавьте хотя бы один существующий PDF.")
            return
        self._set_busy(True)
        self._worker = _Worker(action, self)
        self._worker.finished_result.connect(self._job_finished)
        self._worker.start()

    def _job_finished(self, result: JobResult) -> None:
        self._set_busy(False)
        self._handle_result(result)

    def _handle_result(self, result: JobResult, *, prefer_layout: bool = False) -> None:
        self._append_log(result.message)
        for warning in result.warnings:
            self._append_log(f"Предупреждение: {warning}")
        if not result.ok:
            self.status_label.setText("Ошибка подготовки задания")
            QMessageBox.warning(self, "Ошибка", result.message)
            return
        if result.layout_page_count:
            self.layout_page.setMaximum(result.layout_page_count)
        preview_path = result.layout_preview_pdf_path if prefer_layout else result.preview_pdf_path or result.layout_preview_pdf_path
        if preview_path and preview_path.exists():
            self._show_preview(preview_path, self.layout_page.value() - 1)
        self.status_label.setText(result.message)

    def _show_preview(self, path: Path, page_index: int = 0) -> None:
        self.preview_view.show_pdf(path, page_index)
        self._current_preview_pdf = path
        self.preview_caption.setText(path.name)
        self.open_pdf_btn.setEnabled(True)
        self.tabs.setCurrentIndex(0)

    def _open_current_preview(self) -> None:
        if self._current_preview_pdf and self._current_preview_pdf.exists() and os.name == "nt":
            os.startfile(str(self._current_preview_pdf))  # type: ignore[attr-defined]

    def _confirm_and_draw(self) -> None:
        self._sync_from_ui()
        message = (
            f"Будет отправлен проход {self.pass_col.value()}/{self.pass_cols.value()} × "
            f"{self.pass_row.value()}/{self.pass_rows.value()} на {self._selected_machine_profile()}.\n\n"
            "Перо поднято, лист закреплён, калибровка выполнена?"
        )
        if QMessageBox.question(self, "Подтвердите рисование", message) != QMessageBox.StandardButton.Yes:
            return
        self.vm.set_hardware_confirmed(True)
        self._run_job(self.vm.draw)

    def _run_self_check(self) -> None:
        exit_code, text = self.self_check_vm.run()
        self._append_log(text)
        self.status_label.setText(f"Самопроверка завершена, код {exit_code}")
        self.tabs.setCurrentIndex(1)

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка результатов", self.output_edit.text() or str(Path.cwd()))
        if path:
            self.output_edit.setText(path)
            self._sync_from_ui()

    def _refresh_com_ports(self, preferred: str = "", *, sync: bool = True) -> None:
        ports = discovery_mod.list_serial_ports()
        selected = discovery_mod.suggest_plotter_port(preferred or None, ports=ports) or preferred
        self.com_combo.blockSignals(True)
        self.com_combo.clear()
        self.com_combo.addItem("Автоопределение", "")
        for port in ports:
            self.com_combo.addItem(port.label, port.device)
        index = self.com_combo.findData(selected)
        self.com_combo.setCurrentIndex(index if index >= 0 else 0)
        if selected and index < 0:
            self.com_combo.setEditText(selected)
        self.com_combo.blockSignals(False)
        if sync:
            self._sync_from_ui()

    def _set_busy(self, busy: bool) -> None:
        self.vm.operation_running = busy
        self.setCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        self._sync_draw_gate()

    def _sync_draw_gate(self) -> None:
        if hasattr(self, "preview_btn"):
            self.preview_btn.setEnabled(self.vm.can_preview())
            self.generate_btn.setEnabled(self.vm.can_generate())
            self.draw_btn.setEnabled(self.vm.can_draw())
            self.layout_preview_btn.setEnabled(self.vm.can_preview())

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(str(text))
