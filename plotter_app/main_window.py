from __future__ import annotations

from pathlib import Path

from .settings import load_settings, save_settings
from .viewmodels.job_viewmodel import JobViewModel
from .viewmodels.self_check_viewmodel import SelfCheckViewModel

try:
    from PySide6.QtCore import QObject, QThread, Signal
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
        QMainWindow, QMessageBox, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
    )
except ImportError:  # pragma: no cover
    QObject = object  # type: ignore
    QMainWindow = object  # type: ignore


class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, func):
        super().__init__()
        self.func = func

    def run(self):
        try:
            self.finished.emit(self.func())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.vm = JobViewModel(load_settings())
        self.setWindowTitle("Plotter PDF")
        self.resize(920, 720)
        self._threads: list[QThread] = []
        self._build_ui()
        self._sync_from_settings()
        self._update_gate()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        form = QFormLayout()
        self.input_edit = QLineEdit()
        input_btn = QPushButton("Browse...")
        input_btn.clicked.connect(self._choose_input)
        row = QHBoxLayout(); row.addWidget(self.input_edit); row.addWidget(input_btn)
        form.addRow("Input PDF/SVG/DOC/DOCX/FRW/CDW", row)
        self.output_edit = QLineEdit()
        out_btn = QPushButton("Browse..."); out_btn.clicked.connect(self._choose_output)
        out_row = QHBoxLayout(); out_row.addWidget(self.output_edit); out_row.addWidget(out_btn)
        form.addRow("Output dir", out_row)
        self.com_combo = QComboBox(); self.com_combo.setEditable(True)
        refresh_btn = QPushButton("Refresh COM"); refresh_btn.clicked.connect(self._refresh_ports)
        com_row = QHBoxLayout(); com_row.addWidget(self.com_combo); com_row.addWidget(refresh_btn)
        form.addRow("COM port", com_row)
        self.baud_edit = QLineEdit("115200"); form.addRow("Baud", self.baud_edit)
        self.sheet_combo = QComboBox(); self.sheet_combo.addItems(["work", "a4", "a3", "notebook", "custom"]); form.addRow("Sheet format", self.sheet_combo)
        self.width_edit = QLineEdit(); self.height_edit = QLineEdit(); wh = QHBoxLayout(); wh.addWidget(self.width_edit); wh.addWidget(self.height_edit); form.addRow("Custom W/H mm", wh)
        self.anchor_edit = QLineEdit("center"); form.addRow("Sheet anchor", self.anchor_edit)
        self.offset_x = QLineEdit("0"); self.offset_y = QLineEdit("0"); off = QHBoxLayout(); off.addWidget(self.offset_x); off.addWidget(self.offset_y); form.addRow("Offsets X/Y mm", off)
        self.pass_cols = QSpinBox(); self.pass_cols.setRange(1, 20); self.pass_rows = QSpinBox(); self.pass_rows.setRange(1, 20); self.pass_col = QSpinBox(); self.pass_col.setRange(1, 20); self.pass_row = QSpinBox(); self.pass_row.setRange(1, 20)
        pg = QHBoxLayout(); [pg.addWidget(w) for w in (QLabel("cols"), self.pass_cols, QLabel("rows"), self.pass_rows, QLabel("col"), self.pass_col, QLabel("row"), self.pass_row)]; form.addRow("Pass grid", pg)
        self.tool_combo = QComboBox(); self.tool_combo.addItems(["pen", "pencil"]); form.addRow("Tool", self.tool_combo)
        self.handwriting = QCheckBox("Handwriting"); form.addRow("Handwriting", self.handwriting)
        self.quality_combo = QComboBox(); self.quality_combo.addItems(["fast", "normal", "high"]); form.addRow("Quality", self.quality_combo)
        self.draw_order = QComboBox(); self.draw_order.addItems(["auto", "nearest", "source", "line_lr"]); form.addRow("Draw order", self.draw_order)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.self_check_btn = QPushButton("Self-check"); self.self_check_btn.clicked.connect(self._self_check)
        self.preview_btn = QPushButton("Preview"); self.preview_btn.clicked.connect(self._preview)
        self.generate_btn = QPushButton("Generate G-code"); self.generate_btn.clicked.connect(self._generate)
        self.draw_btn = QPushButton("Draw"); self.draw_btn.clicked.connect(self._draw)
        for text in ["Calibrate corners", "Draw frame", "Safe park / release motors", "Emergency stop", "Open output folder"]:
            btn = QPushButton(text); btn.clicked.connect(lambda _=False, t=text: self._log(f"{t}: use CLI/hardware workflow after self-check.")); buttons.addWidget(btn)
        for btn in (self.self_check_btn, self.preview_btn, self.generate_btn, self.draw_btn): buttons.addWidget(btn)
        layout.addLayout(buttons)
        self.status = QLabel("Preflight: not run")
        layout.addWidget(self.status)
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True); layout.addWidget(self.log_box)
        self.setCentralWidget(root)

    def _sync_from_settings(self):
        s = self.vm.settings
        self.input_edit.setText(str(s.input_path or "")); self.output_edit.setText(str(s.output_dir or "")); self.com_combo.setEditText(s.com or ""); self.baud_edit.setText(str(s.baud))
        self.sheet_combo.setCurrentText(s.sheet_format); self.width_edit.setText("" if s.sheet_width_mm is None else str(s.sheet_width_mm)); self.height_edit.setText("" if s.sheet_height_mm is None else str(s.sheet_height_mm))
        self.anchor_edit.setText(s.sheet_anchor); self.offset_x.setText(str(s.sheet_offset_x_mm)); self.offset_y.setText(str(s.sheet_offset_y_mm))
        self.pass_cols.setValue(s.pass_cols); self.pass_rows.setValue(s.pass_rows); self.pass_col.setValue(s.pass_col); self.pass_row.setValue(s.pass_row); self.tool_combo.setCurrentText(s.tool); self.handwriting.setChecked(s.handwriting); self.quality_combo.setCurrentText(s.quality); self.draw_order.setCurrentText(s.draw_order)

    def _collect(self):
        def f(text):
            return float(text) if str(text).strip() else None
        self.vm.update_settings(input_path=self.input_edit.text().strip() or None, output_dir=self.output_edit.text().strip() or None, com=self.com_combo.currentText().strip(), baud=self.baud_edit.text().strip() or "115200", sheet_format=self.sheet_combo.currentText(), sheet_width_mm=f(self.width_edit.text()), sheet_height_mm=f(self.height_edit.text()), sheet_anchor=self.anchor_edit.text().strip() or "center", sheet_offset_x_mm=float(self.offset_x.text() or 0), sheet_offset_y_mm=float(self.offset_y.text() or 0), pass_cols=self.pass_cols.value(), pass_rows=self.pass_rows.value(), pass_col=self.pass_col.value(), pass_row=self.pass_row.value(), tool=self.tool_combo.currentText(), handwriting=self.handwriting.isChecked(), quality=self.quality_combo.currentText(), draw_order=self.draw_order.currentText())
        save_settings(self.vm.settings)

    def _choose_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select input", "", "Plotter inputs (*.pdf *.svg *.doc *.docx *.frw *.cdw);;All files (*)")
        if path: self.input_edit.setText(path); self._update_gate()

    def _choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "Select output")
        if path: self.output_edit.setText(path)

    def _refresh_ports(self):
        self.com_combo.clear(); self.com_combo.addItems(self.vm.refresh_com_ports())

    def _log(self, msg):
        self.log_box.append(str(msg))

    def _run_threaded(self, func):
        self._collect(); self.vm.busy = True; self._update_gate()
        thread = QThread(self); worker = _Worker(func); worker.moveToThread(thread); thread.started.connect(worker.run)
        worker.finished.connect(lambda result: self._done(thread, result)); worker.failed.connect(lambda err: self._done(thread, err)); thread.start(); self._threads.append(thread)

    def _done(self, thread, result):
        self.vm.busy = False
        if hasattr(result, "message"):
            self._log(result.message); self.status.setText(f"Preflight: {'ok' if result.ok else 'failed'}; G-code: {result.gcode_path}; bounds: {result.bounds}; lines: {result.line_count}; draw/travel: {result.draw_moves}/{result.travel_moves}; warnings: {result.warnings}; errors: {result.errors}")
        else:
            self._log(result)
        thread.quit(); thread.wait(1000); self._update_gate()

    def _self_check(self):
        self._log(SelfCheckViewModel().run())

    def _preview(self): self._run_threaded(lambda: self.vm.run_preview())
    def _generate(self): self._run_threaded(lambda: self.vm.run_generate())

    def _draw(self):
        self._collect()
        msg = "Будет отправлен G-code на COM-порт. Убедитесь, что перо поднято, лист закреплён, рабочая область свободна."
        if QMessageBox.warning(self, "Confirm hardware draw", msg, QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok: return
        self.vm.hardware_confirmed = True; self._run_threaded(lambda: self.vm.run_draw())

    def _update_gate(self):
        self._collect()
        self.preview_btn.setEnabled(self.vm.can_preview()); self.generate_btn.setEnabled(self.vm.can_generate()); self.draw_btn.setEnabled(self.vm.can_draw())
