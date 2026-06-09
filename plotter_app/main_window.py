from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.plotter_backend import discovery as discovery_mod
from src.plotter_backend.jobs import JobResult, JobSettings

from .settings import load_gui_settings, save_gui_settings
from .viewmodels import JobViewModel, SelfCheckViewModel


class _Worker(QThread):
    finished_result = Signal(object)

    def __init__(self, action, parent=None) -> None:
        super().__init__(parent)
        self._action = action

    def run(self) -> None:
        self.finished_result.emit(self._action())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Plotter PDF")
        self.resize(980, 720)
        self.settings_data = load_gui_settings()
        self.vm = JobViewModel(self._settings_from_ui_data())
        self.self_check_vm = SelfCheckViewModel()
        self._worker: _Worker | None = None
        self._build_ui()
        self._sync_draw_gate()

    def _settings_from_ui_data(self) -> JobSettings:
        data = self.settings_data
        return JobSettings(
            input_path=data.get("input_path") or None,
            output_dir=data.get("output_dir") or "_plotter_jobs",
            com=data.get("com") or None,
            baud=str(data.get("baud") or "115200"),
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
        )

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        form = QFormLayout()
        self.input_edit = QLineEdit(str(self.vm.settings.input_path or ""))
        self.output_edit = QLineEdit(str(self.vm.settings.output_dir))
        self.com_combo = QComboBox()
        self.com_combo.setEditable(True)
        self._refresh_com_ports(self.vm.settings.com or "", sync=False)
        self.baud_edit = QLineEdit(str(self.vm.settings.baud))
        self.sheet_combo = QComboBox()
        self.sheet_combo.addItems(["work", "a4", "a3", "notebook", "custom"])
        self.sheet_combo.setCurrentText(self.vm.settings.sheet_format)
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["pen", "pencil"])
        self.tool_combo.setCurrentText(self.vm.settings.tool)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["fast", "normal", "high"])
        self.quality_combo.setCurrentText(self.vm.settings.quality)
        self.pass_cols = QSpinBox()
        self.pass_cols.setRange(1, 10)
        self.pass_cols.setValue(self.vm.settings.pass_cols)
        self.pass_rows = QSpinBox()
        self.pass_rows.setRange(1, 10)
        self.pass_rows.setValue(self.vm.settings.pass_rows)
        self.pass_col = QSpinBox()
        self.pass_col.setRange(1, 10)
        self.pass_col.setValue(self.vm.settings.pass_col)
        self.pass_row = QSpinBox()
        self.pass_row.setRange(1, 10)
        self.pass_row.setValue(self.vm.settings.pass_row)
        self.handwriting = QCheckBox("Handwriting text")
        self.handwriting.setChecked(self.vm.settings.handwriting)
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_edit)
        pick_input = QPushButton("Browse")
        pick_input.clicked.connect(self._pick_input)
        input_row.addWidget(pick_input)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit)
        pick_output = QPushButton("Browse")
        pick_output.clicked.connect(self._pick_output)
        output_row.addWidget(pick_output)
        com_row = QHBoxLayout()
        com_row.addWidget(self.com_combo)
        refresh_com = QPushButton("Refresh")
        refresh_com.clicked.connect(lambda: self._refresh_com_ports(self.com_combo.currentText().strip()))
        com_row.addWidget(refresh_com)
        form.addRow("Input PDF/SVG/DOC/CDW:", input_row)
        form.addRow("Output dir:", output_row)
        form.addRow("COM port:", com_row)
        form.addRow("Baud:", self.baud_edit)
        form.addRow("Sheet:", self.sheet_combo)
        form.addRow("Tool:", self.tool_combo)
        form.addRow("Quality:", self.quality_combo)
        form.addRow("Pass cols/rows:", self._pair(self.pass_cols, self.pass_rows))
        form.addRow("Pass col/row:", self._pair(self.pass_col, self.pass_row))
        form.addRow("Text:", self.handwriting)
        layout.addLayout(form)
        self.status_label = QLabel("Preflight: not run")
        layout.addWidget(self.status_label)
        buttons = QHBoxLayout()
        self.self_check_btn = QPushButton("Self-check")
        self.preview_btn = QPushButton("Preview")
        self.generate_btn = QPushButton("Generate G-code")
        self.draw_btn = QPushButton("Draw")
        self.release_btn = QPushButton("Safe park / release")
        self.stop_btn = QPushButton("Emergency stop")
        buttons.addWidget(self.self_check_btn)
        buttons.addWidget(self.preview_btn)
        buttons.addWidget(self.generate_btn)
        buttons.addWidget(self.draw_btn)
        buttons.addWidget(self.release_btn)
        buttons.addWidget(self.stop_btn)
        layout.addLayout(buttons)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        self.self_check_btn.clicked.connect(self._run_self_check)
        self.preview_btn.clicked.connect(lambda: self._run_job(self.vm.run_preview))
        self.generate_btn.clicked.connect(lambda: self._run_job(self.vm.generate_gcode))
        self.draw_btn.clicked.connect(self._confirm_and_draw)
        self.release_btn.clicked.connect(lambda: self._append_log("Use CLI safe-release script for now: scripts\\release_motors.bat"))
        self.stop_btn.clicked.connect(lambda: QMessageBox.warning(self, "Emergency stop", "Use controller reset / power stop for hard emergency."))
        for widget in [
            self.input_edit,
            self.output_edit,
            self.com_combo,
            self.baud_edit,
            self.sheet_combo,
            self.tool_combo,
            self.quality_combo,
            self.pass_cols,
            self.pass_rows,
            self.pass_col,
            self.pass_row,
            self.handwriting,
        ]:
            signal = getattr(widget, "textChanged", None) or getattr(widget, "currentTextChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "stateChanged", None)
            if signal is not None:
                signal.connect(self._sync_from_ui)
        self.setCentralWidget(central)

    def _pair(self, left: QWidget, right: QWidget) -> QWidget:
        box = QWidget(self)
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(left)
        row.addWidget(QLabel("/"))
        row.addWidget(right)
        row.addStretch(1)
        return box

    def _pick_input(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Select input", "", "Drawings (*.pdf *.svg *.doc *.docx *.frw *.cdw);;All files (*.*)")
        if path:
            self.input_edit.setText(path)

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output directory", self.output_edit.text() or str(Path.cwd()))
        if path:
            self.output_edit.setText(path)

    def _refresh_com_ports(self, preferred: str = "", *, sync: bool = True) -> None:
        current = str(preferred or "").strip()
        ports = discovery_mod.list_serial_ports()
        selected = discovery_mod.suggest_plotter_port(current or None, ports=ports) or current
        self.com_combo.blockSignals(True)
        self.com_combo.clear()
        self.com_combo.addItem("", "")
        for port in ports:
            self.com_combo.addItem(port.label, port.device)
        if selected:
            selected_index = -1
            for index in range(self.com_combo.count()):
                if str(self.com_combo.itemData(index) or "").upper() == selected.upper():
                    selected_index = index
                    break
            if selected_index >= 0:
                self.com_combo.setCurrentIndex(selected_index)
            else:
                self.com_combo.setEditText(selected)
        self.com_combo.blockSignals(False)
        if sync:
            self._sync_from_ui()

    def _sync_from_ui(self, *_args) -> None:
        self.vm.settings.input_path = self.input_edit.text().strip() or None
        self.vm.settings.output_dir = self.output_edit.text().strip() or "_plotter_jobs"
        com_value = str(self.com_combo.currentData() or "").strip()
        if not com_value:
            raw_com = self.com_combo.currentText().strip()
            com_value = raw_com.split(" ", 1)[0].strip()
        self.vm.settings.com = com_value or None
        self.vm.settings.baud = self.baud_edit.text().strip() or "115200"
        self.vm.settings.sheet_format = self.sheet_combo.currentText()
        self.vm.settings.tool = self.tool_combo.currentText()
        self.vm.settings.quality = self.quality_combo.currentText()
        self.vm.settings.pass_cols = self.pass_cols.value()
        self.vm.settings.pass_rows = self.pass_rows.value()
        self.vm.settings.pass_col = self.pass_col.value()
        self.vm.settings.pass_row = self.pass_row.value()
        self.vm.settings.handwriting = self.handwriting.isChecked()
        save_gui_settings(asdict(self.vm.settings))
        self._sync_draw_gate()

    def _sync_draw_gate(self) -> None:
        self.draw_btn.setEnabled(self.vm.can_draw() if hasattr(self, "draw_btn") else False)
        if hasattr(self, "preview_btn"):
            self.preview_btn.setEnabled(self.vm.can_preview())
            self.generate_btn.setEnabled(self.vm.can_generate())

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def _run_self_check(self) -> None:
        exit_code, text = self.self_check_vm.run()
        self._append_log(text)
        self.status_label.setText(f"Self-check exit code: {exit_code}")

    def _run_job(self, action) -> None:
        self._sync_from_ui()
        if not self.vm.has_input():
            QMessageBox.warning(self, "Missing input", "Choose an input drawing first.")
            return
        self._set_busy(True)
        self._worker = _Worker(action, self)
        self._worker.finished_result.connect(self._job_finished)
        self._worker.start()

    def _confirm_and_draw(self) -> None:
        self._sync_from_ui()
        text = (
            "G-code will be sent to the COM port.\n\n"
            "Make sure the pen is lifted, the sheet is fixed, and the work area is clear."
        )
        if QMessageBox.question(self, "Confirm plotter draw", text) != QMessageBox.StandardButton.Yes:
            return
        self.vm.set_hardware_confirmed(True)
        self._run_job(self.vm.draw)

    def _set_busy(self, busy: bool) -> None:
        self.vm.operation_running = busy
        self.setCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        self._sync_draw_gate()

    def _job_finished(self, result: JobResult) -> None:
        self._set_busy(False)
        self._append_log(result.message)
        if result.ok:
            self.status_label.setText(f"Ready: {result.gcode_path or result.nc_path or ''}")
        else:
            self.status_label.setText("Failed")
            QMessageBox.warning(self, "Job failed", result.message)
