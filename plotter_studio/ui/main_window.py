from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.plotter_controller import PlotterController
from ..core.settings import log_file_path
from .pages import CalibrationPage, ConnectionPage, FilePage, ManualPage
from .theme import build_stylesheet, resolve_palette
from .widgets import SegmentedControl, StatusPill, ToastWidget


class MainWindow(QMainWindow):
    def __init__(self, controller: PlotterController) -> None:
        super().__init__()
        self.controller = controller
        self.settings = controller.settings
        self._connected = False
        self._busy = False
        self._unread_logs = 0
        self._hide_log_after_anim = False

        self.setWindowTitle("Plotter Studio")
        self.resize(1420, 920)
        self.setMinimumSize(1260, 800)

        self._build_ui()
        self._bind_signals()
        self._apply_initial_state()
        self._apply_theme(self.settings.theme_mode)

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(16, 14, 16, 14)
        main.setSpacing(12)

        self.top_bar = QFrame(root)
        self.top_bar.setObjectName("TopBar")
        top = QHBoxLayout(self.top_bar)
        top.setContentsMargins(18, 12, 18, 12)
        top.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.title_label = QLabel("Plotter Studio", self.top_bar)
        self.title_label.setObjectName("TitleLabel")
        self.subtitle_label = QLabel("Подключение, калибровка, запуск и ручное управление в одном окне", self.top_bar)
        self.subtitle_label.setObjectName("SubtitleLabel")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        top.addLayout(title_col)
        top.addStretch(1)

        self.connection_pill = StatusPill("Отключено", "neutral", self.top_bar)
        top.addWidget(self.connection_pill)

        self.tool_segment = SegmentedControl([("pencil", "Карандаш"), ("pen", "Ручка")], self.top_bar)
        top.addWidget(self.tool_segment)

        self.theme_combo = QComboBox(self.top_bar)
        self.theme_combo.addItem("Авто", "auto")
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Тёмная", "dark")
        self.theme_combo.setMinimumWidth(124)
        top.addWidget(self.theme_combo)

        self.stop_btn = QPushButton("Стоп", self.top_bar)
        self.stop_btn.setObjectName("DangerButton")
        top.addWidget(self.stop_btn)

        self.log_toggle_btn = QPushButton("Логи", self.top_bar)
        self.log_toggle_btn.setObjectName("GhostButton")
        top.addWidget(self.log_toggle_btn)

        main.addWidget(self.top_bar)

        self.scroll = QScrollArea(root)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.content_root = QWidget(self.scroll)
        self.content_root.setObjectName("ContentRoot")
        self.content_root.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        content = QHBoxLayout(self.content_root)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        content.setSizeConstraint(QLayout.SetMinimumSize)

        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        left_col.setSpacing(12)
        right_col.setSpacing(12)

        self.connection_page = ConnectionPage(self.content_root)
        self.calibration_page = CalibrationPage(self.content_root)
        self.file_page = FilePage(self.content_root)
        self.manual_page = ManualPage(self.content_root)

        for page in (self.connection_page, self.calibration_page, self.file_page, self.manual_page):
            page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        left_col.addWidget(self.connection_page)
        left_col.addWidget(self.calibration_page)

        right_col.addWidget(self.file_page)
        right_col.addWidget(self.manual_page)

        content.addLayout(left_col, 6)
        content.addLayout(right_col, 5)
        content.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.content_root)
        main.addWidget(self.scroll, 1)

        self.log_drawer = QFrame(root)
        self.log_drawer.setObjectName("LogDrawer")
        drawer = QVBoxLayout(self.log_drawer)
        drawer.setContentsMargins(14, 12, 14, 12)
        drawer.setSpacing(10)

        drawer_top = QHBoxLayout()
        self.log_search = QLineEdit(self.log_drawer)
        self.log_search.setPlaceholderText("Поиск по логу...")
        self.log_find_btn = QPushButton("Найти", self.log_drawer)
        self.log_copy_btn = QPushButton("Копировать", self.log_drawer)
        self.log_clear_btn = QPushButton("Очистить", self.log_drawer)
        self.log_open_folder_btn = QPushButton("Папка логов", self.log_drawer)
        drawer_top.addWidget(self.log_search, 1)
        drawer_top.addWidget(self.log_find_btn)
        drawer_top.addWidget(self.log_copy_btn)
        drawer_top.addWidget(self.log_clear_btn)
        drawer_top.addWidget(self.log_open_folder_btn)
        drawer.addLayout(drawer_top)

        self.log_view = QPlainTextEdit(self.log_drawer)
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setMinimumHeight(180)
        drawer.addWidget(self.log_view, 1)

        self.log_drawer.setMaximumHeight(0)
        self.log_drawer.setVisible(False)
        self._log_anim = QPropertyAnimation(self.log_drawer, b"maximumHeight", self)
        self._log_anim.setDuration(180)
        self._log_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._log_anim.finished.connect(self._on_log_animation_finished)
        main.addWidget(self.log_drawer)

        self.status_bar_card = QFrame(root)
        self.status_bar_card.setObjectName("StatusCard")
        sb = QHBoxLayout(self.status_bar_card)
        sb.setContentsMargins(12, 8, 12, 8)
        sb.setSpacing(10)

        self.status_text = QLabel("Готово", self.status_bar_card)
        self.status_text.setObjectName("HintLabel")

        self.progress_bar = QProgressBar(self.status_bar_card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(260)

        sb.addWidget(self.status_text, 1)
        sb.addWidget(self.progress_bar)
        main.addWidget(self.status_bar_card)

        self.toast = ToastWidget(self)
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.file_page.pick_file_dialog)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._draw_from_current_file)
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self, activated=self._preview_current_file)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._toggle_log_drawer)
        QShortcut(QKeySequence("Escape"), self, activated=self.controller.cancel_active_operation)

    def _bind_signals(self) -> None:
        self.tool_segment.value_changed.connect(self._on_tool_changed)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.stop_btn.clicked.connect(self.controller.cancel_active_operation)
        self.log_toggle_btn.clicked.connect(self._toggle_log_drawer)

        self.connection_page.refresh_requested.connect(self.controller.refresh_ports)
        self.connection_page.connect_requested.connect(self.controller.connect_port)
        self.connection_page.disconnect_requested.connect(self.controller.disconnect)
        self.connection_page.port_selected.connect(self._on_port_changed)

        self.calibration_page.sheet_changed.connect(self._on_sheet_changed)
        self.calibration_page.calibration_requested.connect(self.controller.run_calibration)
        self.calibration_page.frame_requested.connect(self.controller.run_frame)
        self.calibration_page.calibrate_before_draw_changed.connect(
            lambda v: self.controller.update_ui_settings(calibrate_before_draw=v)
        )

        self.file_page.file_changed.connect(lambda s: self.controller.update_ui_settings(last_file=s))
        self.file_page.preview_requested.connect(self.controller.preview_file)
        self.file_page.draw_requested.connect(self.controller.draw_file)
        self.file_page.wear_test_requested.connect(self.controller.run_wear_test)
        self.file_page.render_settings_changed.connect(
            lambda render_mode, quality, force_text_to_path, exact_mode, safe_lift, strict_scale, handwriting_enabled, handwriting_font, handwriting_formula_font, image_contours_mode, source_page_index: self.controller.update_ui_settings(
                render_mode=render_mode,
                quality_profile=quality,
                force_text_to_path=force_text_to_path,
                exact_geometry_mode=exact_mode,
                safe_travel_lift=safe_lift,
                strict_one_to_one=strict_scale,
                handwriting_enabled=handwriting_enabled,
                handwriting_font=handwriting_font,
                handwriting_formula_font=handwriting_formula_font,
                image_contours_mode=image_contours_mode,
                source_page_index=source_page_index,
            )
        )

        self.manual_page.pen_down_requested.connect(
            lambda step, feed: self.controller.pen_step(down=True, step_mm=step, feed=feed)
        )
        self.manual_page.pen_up_requested.connect(
            lambda step, feed: self.controller.pen_step(down=False, step_mm=step, feed=feed)
        )
        self.manual_page.release_motors_requested.connect(self._confirm_release_motors)
        self.manual_page.sharpen_requested.connect(self.controller.mark_pencil_sharpened)

        self.log_find_btn.clicked.connect(self._find_log_text)
        self.log_copy_btn.clicked.connect(self._copy_logs)
        self.log_clear_btn.clicked.connect(self._clear_logs)
        self.log_open_folder_btn.clicked.connect(self._open_logs_folder)

        self.controller.log_line.connect(self._append_log)
        self.controller.status_changed.connect(self._set_status)
        self.controller.toast.connect(self._show_toast)
        self.controller.connection_changed.connect(self._on_connection_changed)
        self.controller.ports_changed.connect(self._set_ports)
        self.controller.busy_changed.connect(self._on_busy_changed)
        self.controller.progress_changed.connect(self._on_progress_changed)
        self.controller.operation_started.connect(self._on_operation_started)
        self.controller.operation_done.connect(self._on_operation_done)
        self.controller.pencil_banner_changed.connect(self.manual_page.set_pencil_banner)
        self.controller.preview_ready.connect(self._on_preview_ready)

    def _apply_initial_state(self) -> None:
        self.tool_segment.set_value(self.settings.tool_mode)
        idx = self.theme_combo.findData(self.settings.theme_mode)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

        self.calibration_page.set_sheet_values(
            self.settings.sheet_format,
            self.settings.custom_width_mm,
            self.settings.custom_height_mm,
            self.settings.sheet_anchor,
            self.settings.sheet_offset_x_mm,
            self.settings.sheet_offset_y_mm,
            self.settings.a3_two_pass,
            self.settings.a3_pass_index,
        )
        self.calibration_page.set_calibrate_before_draw(self.settings.calibrate_before_draw)

        self.file_page.set_file_path(self.settings.last_file)
        self.file_page.set_render_settings(
            self.settings.render_mode,
            self.settings.quality_profile,
            self.settings.force_text_to_path,
            self.settings.exact_geometry_mode,
            self.settings.safe_travel_lift,
            self.settings.strict_one_to_one,
            self.settings.handwriting_enabled,
            self.settings.handwriting_font,
            self.settings.handwriting_formula_font,
            self.settings.image_contours_mode,
            self.settings.source_page_index,
        )
        self.file_page.set_preview_path(self.settings.last_preview_svg)

        self.manual_page.set_values(self.settings.z_step_mm, self.settings.z_feed)
        self._set_log_drawer_visible(bool(self.settings.log_drawer_open))
        self.controller.set_tool_mode(self.settings.tool_mode)
        self._on_connection_changed(False, "Отключено", "neutral")
        self.controller.refresh_ports()

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        palette = resolve_palette(mode, app)
        self.setStyleSheet(build_stylesheet(palette))
        self.controller.update_ui_settings(theme_mode=mode)

    def _set_ports(self, ports_obj, selected: str) -> None:
        ports = list(ports_obj)
        self.connection_page.set_ports(ports, selected)

    def _on_port_changed(self, com_port: str) -> None:
        self.controller.set_selected_port((com_port or "").strip())

    def _on_tool_changed(self, value: str) -> None:
        self.controller.set_tool_mode(value)

    def _on_theme_changed(self) -> None:
        mode = str(self.theme_combo.currentData() or "auto")
        self._apply_theme(mode)

    def _on_sheet_changed(
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
        self.controller.update_ui_settings(
            sheet_format=fmt,
            custom_w_mm=width_mm,
            custom_h_mm=height_mm,
            sheet_anchor=anchor,
            sheet_offset_x_mm=offset_x_mm,
            sheet_offset_y_mm=offset_y_mm,
            a3_two_pass=a3_two_pass,
            a3_pass_index=a3_pass_index,
        )

    def _on_connection_changed(self, connected: bool, text: str, level: str) -> None:
        self._connected = connected
        self.connection_pill.set_state(text, level)
        self.connection_page.set_connection_state(connected, text)
        self._apply_connection_locks(connected)

    def _apply_connection_locks(self, connected: bool) -> None:
        self.calibration_page.set_connected_enabled(connected)
        self.file_page.set_connected_enabled(connected)
        self.manual_page.set_connected_enabled(connected)

    def _on_busy_changed(self, busy: bool) -> None:
        self._busy = busy
        self.connection_page.connect_btn.setEnabled(not busy)
        self.connection_page.refresh_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def _on_progress_changed(self, value: int, label: str) -> None:
        if value < 0:
            self.progress_bar.setRange(0, 0)
        else:
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(max(0, min(100, value)))
        if label:
            self.status_text.setText(label)

    def _on_operation_started(self, op_type: str, title: str) -> None:
        if op_type in {"draw", "wear_test", "preview"}:
            self.file_page.set_progress_indeterminate(True, title)

    def _on_operation_done(self, op_type: str, ok: bool, message: str) -> None:
        if op_type in {"draw", "preview"}:
            self.file_page.set_metrics_text(message if message else ("Готово" if ok else "Ошибка"))
        if op_type in {"draw", "wear_test", "preview"}:
            self.file_page.set_progress_indeterminate(False)

    def _set_status(self, text: str) -> None:
        self.status_text.setText(text)

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        if not self.log_drawer.isVisible():
            self._unread_logs += 1
            self._update_log_toggle_text()

    def _update_log_toggle_text(self) -> None:
        unread = f" ({self._unread_logs})" if self._unread_logs > 0 else ""
        self.log_toggle_btn.setText(f"Логи{unread}")

    def _toggle_log_drawer(self) -> None:
        self._set_log_drawer_visible(not self.log_drawer.isVisible())

    def _set_log_drawer_visible(self, visible: bool) -> None:
        if visible:
            self._hide_log_after_anim = False
            self.log_drawer.setVisible(True)
            target = max(180, min(420, self.log_drawer.sizeHint().height()))
            self._animate_log_drawer(target)
            self._unread_logs = 0
        else:
            self._hide_log_after_anim = True
            self._animate_log_drawer(0)
        self._update_log_toggle_text()
        self.controller.update_ui_settings(log_drawer_open=visible)

    def _animate_log_drawer(self, target_height: int) -> None:
        self._log_anim.stop()
        start = self.log_drawer.maximumHeight()
        self._log_anim.setStartValue(start)
        self._log_anim.setEndValue(max(0, int(target_height)))
        self._log_anim.start()

    def _on_log_animation_finished(self) -> None:
        if self._hide_log_after_anim and self.log_drawer.maximumHeight() == 0:
            self.log_drawer.setVisible(False)

    def _find_log_text(self) -> None:
        needle = self.log_search.text().strip()
        if not needle:
            return
        if not self.log_view.find(needle):
            cursor = self.log_view.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.log_view.setTextCursor(cursor)
            self.log_view.find(needle)

    def _copy_logs(self) -> None:
        text = self.log_view.toPlainText().strip()
        if not text:
            self._show_toast("info", "Лог пуст.")
            return
        self.log_view.selectAll()
        self.log_view.copy()
        cursor = self.log_view.textCursor()
        cursor.clearSelection()
        self.log_view.setTextCursor(cursor)
        self._show_toast("info", "Лог скопирован в буфер обмена.")

    def _clear_logs(self) -> None:
        self.log_view.clear()
        self._show_toast("info", "Лог очищен.")

    def _open_logs_folder(self) -> None:
        path = log_file_path().parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _confirm_release_motors(self) -> None:
        result = QMessageBox.question(
            self,
            "Подтверждение",
            "Отпустить моторы? После этого оси можно сдвинуть руками.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.controller.release_motors()

    def _draw_from_current_file(self) -> None:
        text = self.file_page.path_edit.text().strip()
        if text:
            self.controller.draw_file(Path(text))

    def _preview_current_file(self) -> None:
        text = self.file_page.path_edit.text().strip()
        if text:
            self.controller.preview_file(Path(text))

    @Slot(str)
    def _on_preview_ready(self, path: str) -> None:
        self.file_page.set_preview_path(path)

    @Slot(str)
    def _open_preview_file(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    @Slot(str, str)
    def _show_toast(self, level: str, text: str) -> None:
        self.toast.show_message(level, text)

    def closeEvent(self, event: QCloseEvent) -> None:
        (
            render_mode,
            quality_profile,
            force_text_to_path,
            exact_geometry_mode,
            safe_travel_lift,
            strict_one_to_one,
            handwriting_enabled,
            handwriting_font,
            handwriting_formula_font,
            image_contours_mode,
            source_page_index,
        ) = self.file_page.current_render_settings()
        self.controller.update_ui_settings(
            log_drawer_open=self.log_drawer.isVisible(),
            z_step_mm=self.manual_page.values()[0],
            z_feed=self.manual_page.values()[1],
            sheet_format=self.calibration_page.current_sheet_format(),
            custom_w_mm=self.calibration_page.width_spin.value(),
            custom_h_mm=self.calibration_page.height_spin.value(),
            sheet_anchor=self.calibration_page.current_anchor(),
            sheet_offset_x_mm=self.calibration_page.offset_x_spin.value(),
            sheet_offset_y_mm=self.calibration_page.offset_y_spin.value(),
            a3_two_pass=self.calibration_page.a3_two_pass_check.isChecked(),
            a3_pass_index=int(self.calibration_page.a3_pass_combo.currentData() or 1),
            calibrate_before_draw=self.calibration_page.calibrate_check.isChecked(),
            last_file=self.file_page.path_edit.text().strip(),
            render_mode=render_mode,
            quality_profile=quality_profile,
            force_text_to_path=force_text_to_path,
            exact_geometry_mode=exact_geometry_mode,
            safe_travel_lift=safe_travel_lift,
            strict_one_to_one=strict_one_to_one,
            handwriting_enabled=handwriting_enabled,
            handwriting_font=handwriting_font,
            handwriting_formula_font=handwriting_formula_font,
            image_contours_mode=image_contours_mode,
            source_page_index=source_page_index,
        )
        self.controller.shutdown()
        super().closeEvent(event)
