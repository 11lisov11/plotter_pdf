from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .protocol import BackendBridge, SheetConfig
from .serial_worker import OperationContext, SerialWorker, WorkerOperation
from .settings import AppSettingsData, SettingsStore, log_file_path


@dataclass
class OperationMeta:
    op_type: str
    com_port: Optional[str] = None
    payload: Optional[str] = None


class PlotterController(QObject):
    log_line = Signal(str)
    status_changed = Signal(str)
    toast = Signal(str, str)  # level, text
    connection_changed = Signal(bool, str, str)  # connected, label, level
    ports_changed = Signal(object, str)  # list[str], selected
    busy_changed = Signal(bool)
    progress_changed = Signal(int, str)  # value, label
    operation_done = Signal(str, bool, str)  # op_type, ok, message
    operation_started = Signal(str, str)  # op_type, title
    pencil_banner_changed = Signal(str, bool)  # text, alert
    preview_ready = Signal(str)  # path to preview artifact (pdf/svg)

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root
        self.settings_store = SettingsStore()
        self.settings: AppSettingsData = self.settings_store.load()
        self.bridge = BackendBridge(project_root)
        self.baud = self.bridge.default_baud()

        self.connected = False
        self.connected_port = ""
        self._operations: dict[str, OperationMeta] = {}
        self._settings_dirty = False
        self._log_buffer: list[str] = []

        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(250)
        self._settings_save_timer.timeout.connect(self._flush_settings)

        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(140)
        self._log_flush_timer.timeout.connect(self._flush_log_buffer)

        self.worker = SerialWorker()
        self.worker.operation_started.connect(self._on_operation_started)
        self.worker.operation_finished.connect(self._on_operation_finished)
        self.worker.log_line.connect(self._on_worker_log_line)
        self.worker.busy_changed.connect(self.busy_changed.emit)
        self.worker.progress.connect(self.progress_changed.emit)
        self.worker.start()

        self._set_connection_state(False, "Отключено", "neutral")
        self.refresh_ports()
        self.refresh_pencil_banner()

    def shutdown(self) -> None:
        self._flush_log_buffer()
        self._flush_settings()
        self.worker.shutdown()
        self.worker.wait(1500)

    def _schedule_settings_save(self) -> None:
        self._settings_dirty = True
        self._settings_save_timer.start()

    def _flush_settings(self) -> None:
        if not self._settings_dirty:
            return
        try:
            self.settings_store.save(self.settings)
        except Exception:
            pass
        finally:
            self._settings_dirty = False

    def _on_worker_log_line(self, text: str) -> None:
        line = text.rstrip("\n")
        if not line:
            return
        self.log_line.emit(line)
        self._append_log_file_line(line)

    def _append_log_file_line(self, line: str) -> None:
        self._log_buffer.append(line)
        self._log_flush_timer.start()

    def _flush_log_buffer(self) -> None:
        if not self._log_buffer:
            return
        path = log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        chunk = "\n".join(self._log_buffer) + "\n"
        self._log_buffer.clear()
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(chunk)
        except Exception:
            pass

    def _on_operation_started(self, op_id: str, title: str) -> None:
        meta = self._operations.get(op_id, OperationMeta(op_type="operation"))
        self.operation_started.emit(meta.op_type, title)
        self.status_changed.emit(title)
        self.progress_changed.emit(-1, title)

    def _on_operation_finished(self, op_id: str, ok: bool, message: str) -> None:
        meta = self._operations.pop(op_id, OperationMeta(op_type="operation"))
        level = "success" if ok else "error"
        self.status_changed.emit(message if message else ("Готово" if ok else "Ошибка"))
        self.progress_changed.emit(0, "")
        self.operation_done.emit(meta.op_type, ok, message)

        if meta.op_type == "connect":
            if ok:
                port = meta.com_port or self.settings.com_port
                self.connected = True
                self.connected_port = port
                self._set_connection_state(True, f"Подключено {port}", "ok")
            else:
                self.connected = False
                self.connected_port = ""
                self._set_connection_state(False, "Ошибка подключения", "error")
        elif meta.op_type == "disconnect":
            self.connected = False
            self.connected_port = ""
            self._set_connection_state(False, "Отключено", "neutral")
        elif meta.op_type in {"preview", "draw"} and ok:
            preview_path = self._extract_preview_path(message)
            if not preview_path:
                preview_path = (meta.payload or "").strip()
            if preview_path:
                self.update_ui_settings(last_preview_svg=preview_path)
                self.preview_ready.emit(preview_path)

        if message:
            self.toast.emit(level, message)
        self.refresh_pencil_banner()

    def _set_connection_state(self, connected: bool, label: str, level: str) -> None:
        self.connection_changed.emit(connected, label, level)

    def _release_idle_motors_in_operation(self, ctx: OperationContext, port: str) -> tuple[bool, str]:
        ok, tail = self.bridge.manual_commands(
            port,
            self.baud,
            ["$X", "M5", "$1=0", "?", "$SLP"],
            soft_reset_first=False,
            read_tail=True,
        )
        if tail:
            for line in tail.splitlines():
                ctx.emit_log(line)
        if ok and self._is_grbl_tail(tail):
            return True, "Моторы отпущены"
        return False, tail or "нет подтверждения отпуска моторов"

    def _enqueue(
        self,
        op_type: str,
        title: str,
        handler: Callable[[OperationContext], tuple[bool, str]],
        *,
        com_port: Optional[str] = None,
        payload: Optional[str] = None,
    ) -> None:
        op_id = uuid.uuid4().hex
        self._operations[op_id] = OperationMeta(op_type=op_type, com_port=com_port, payload=payload)
        self.worker.enqueue(WorkerOperation(op_id=op_id, title=title, handler=handler))

    def _resolve_target_port(self) -> str:
        return (self.connected_port or self.settings.com_port or "").strip()

    def _release_port_candidates(self) -> list[str]:
        selected = self._resolve_target_port()
        out: list[str] = []
        for p in [selected]:
            p_clean = (p or "").strip()
            if p_clean and p_clean not in out:
                out.append(p_clean)
        return out

    @staticmethod
    def _is_grbl_tail(tail: str) -> bool:
        if not tail:
            return False
        markers = ("ok", "error:", "ALARM:", "<", "[MSG:")
        for line in tail.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(m in s for m in markers):
                return True
        return False

    @staticmethod
    def _extract_preview_path(message: str) -> str:
        text = (message or "").strip()
        if not text:
            return ""
        # Stable primary marker from backend bridge.
        m = re.search(r"Preview ready:\s*([^|]+)", text, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        # Legacy marker from older builds.
        m = re.search(r"РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РіРѕС‚РѕРІ:\s*([^|]+)", text)
        if m:
            return (m.group(1) or "").strip()
        # Prefer PDF preview when available.
        m = re.search(r"Preview PDF:\s*([^|]+)", text, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        m = re.search(r"\bPDF:\s*([^|]+)", text, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        # New stable marker.
        m = re.search(r"Preview ready:\s*([^|]+)", text, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        # Legacy marker from older builds.
        m = re.search(r"Предпросмотр готов:\s*([^|]+)", text)
        if m:
            return (m.group(1) or "").strip()
        # Secondary marker if only raw preview path is attached.
        m = re.search(r"Preview SVG:\s*([^|]+)", text, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        return ""

    def refresh_ports(self) -> None:
        try:
            ports = self.bridge.list_com_ports()
            saved = (self.settings.com_port or "").strip()
            suggested = "COM11"

            selected = ""
            if self.connected and self.connected_port in ports:
                selected = self.connected_port
            elif saved and saved in ports:
                selected = saved
            elif "COM11" in ports:
                selected = "COM11"
            elif ports:
                selected = ports[0]
            elif saved:
                selected = saved
            elif suggested:
                selected = suggested

            if selected and selected not in ports:
                ports.insert(0, selected)

            if selected and self.settings.com_port != selected:
                self.settings.com_port = selected
                self._schedule_settings_save()

            self.ports_changed.emit(ports, selected)
        except Exception as exc:
            self.toast.emit("error", f"Не удалось получить список COM-портов: {exc}")

    def set_selected_port(self, com_port: str) -> None:
        self.settings.com_port = (com_port or "").strip()
        self._schedule_settings_save()

    def set_tool_mode(self, tool_mode: str) -> None:
        self.settings.tool_mode = "pencil" if tool_mode == "pencil" else "pen"
        self._schedule_settings_save()
        self.bridge.set_tool_mode(self.settings.tool_mode)
        self.refresh_pencil_banner()

    def update_ui_settings(
        self,
        *,
        theme_mode: Optional[str] = None,
        sheet_format: Optional[str] = None,
        custom_w_mm: Optional[float] = None,
        custom_h_mm: Optional[float] = None,
        calibrate_before_draw: Optional[bool] = None,
        z_step_mm: Optional[float] = None,
        z_feed: Optional[float] = None,
        last_file: Optional[str] = None,
        log_drawer_open: Optional[bool] = None,
        quality_profile: Optional[str] = None,
        render_mode: Optional[str] = None,
        force_text_to_path: Optional[bool] = None,
        handwriting_enabled: Optional[bool] = None,
        handwriting_font: Optional[str] = None,
        handwriting_formula_font: Optional[str] = None,
        image_contours_mode: Optional[str] = None,
        source_page_index: Optional[int] = None,
        source_all_pages: Optional[bool] = None,
        exact_geometry_mode: Optional[bool] = None,
        safe_travel_lift: Optional[bool] = None,
        strict_one_to_one: Optional[bool] = None,
        sheet_anchor: Optional[str] = None,
        sheet_offset_x_mm: Optional[float] = None,
        sheet_offset_y_mm: Optional[float] = None,
        a3_two_pass: Optional[bool] = None,
        a3_pass_index: Optional[int] = None,
        last_preview_svg: Optional[str] = None,
    ) -> None:
        if theme_mode is not None:
            self.settings.theme_mode = theme_mode
        if sheet_format is not None:
            self.settings.sheet_format = sheet_format
        if custom_w_mm is not None:
            self.settings.custom_width_mm = max(10.0, float(custom_w_mm))
        if custom_h_mm is not None:
            self.settings.custom_height_mm = max(10.0, float(custom_h_mm))
        if calibrate_before_draw is not None:
            self.settings.calibrate_before_draw = bool(calibrate_before_draw)
        if z_step_mm is not None:
            self.settings.z_step_mm = max(0.1, float(z_step_mm))
        if z_feed is not None:
            self.settings.z_feed = max(20.0, float(z_feed))
        if last_file is not None:
            self.settings.last_file = last_file
        if log_drawer_open is not None:
            self.settings.log_drawer_open = bool(log_drawer_open)
        if quality_profile is not None:
            qp = (quality_profile or "normal").strip().lower()
            if qp not in {"fast", "normal", "high"}:
                qp = "normal"
            self.settings.quality_profile = qp
        if render_mode is not None:
            mode = (render_mode or "drawing").strip().lower()
            if mode not in {"drawing", "handwriting"}:
                mode = "drawing"
            self.settings.render_mode = mode
        if force_text_to_path is not None:
            self.settings.force_text_to_path = bool(force_text_to_path)
        if handwriting_enabled is not None:
            self.settings.handwriting_enabled = bool(handwriting_enabled)
        if handwriting_font is not None:
            font = (handwriting_font or "").strip() or "Marck Script"
            self.settings.handwriting_font = font
        if handwriting_formula_font is not None:
            ffont = (handwriting_formula_font or "").strip() or "Times New Roman"
            self.settings.handwriting_formula_font = ffont
        if image_contours_mode is not None:
            mode = (image_contours_mode or "always").strip().lower()
            if mode not in {"off", "word_only", "always"}:
                mode = "always"
            self.settings.image_contours_mode = mode
        if source_page_index is not None:
            self.settings.source_page_index = max(1, int(source_page_index))
        if source_all_pages is not None:
            self.settings.source_all_pages = bool(source_all_pages)
        if exact_geometry_mode is not None:
            self.settings.exact_geometry_mode = bool(exact_geometry_mode)
        if safe_travel_lift is not None:
            self.settings.safe_travel_lift = bool(safe_travel_lift)
        if strict_one_to_one is not None:
            self.settings.strict_one_to_one = bool(strict_one_to_one)
        if sheet_anchor is not None:
            anc = (sheet_anchor or "lower_left").strip().lower()
            if anc not in {"center", "lower_left", "upper_left", "lower_right", "upper_right"}:
                anc = "lower_left"
            self.settings.sheet_anchor = anc
        if sheet_offset_x_mm is not None:
            self.settings.sheet_offset_x_mm = float(sheet_offset_x_mm)
        if sheet_offset_y_mm is not None:
            self.settings.sheet_offset_y_mm = float(sheet_offset_y_mm)
        if a3_two_pass is not None:
            self.settings.a3_two_pass = bool(a3_two_pass)
        if a3_pass_index is not None:
            self.settings.a3_pass_index = 1 if int(a3_pass_index) <= 1 else 2
        if last_preview_svg is not None:
            self.settings.last_preview_svg = str(last_preview_svg)
        self._schedule_settings_save()

    def sheet_config(self) -> SheetConfig:
        fmt = (self.settings.sheet_format or "a4").strip().lower()
        if fmt not in {"work", "a4", "a3", "notebook", "custom"}:
            fmt = "a4"
        pass_cols = 1
        pass_rows = 1
        pass_col = 1
        pass_row = 1
        if fmt == "a3" and bool(self.settings.a3_two_pass):
            pass_cols = 2
            pass_col = 1 if int(self.settings.a3_pass_index) <= 1 else 2
        if fmt == "custom":
            return SheetConfig(
                sheet_format=fmt,
                width_mm=self.settings.custom_width_mm,
                height_mm=self.settings.custom_height_mm,
                anchor=self.settings.sheet_anchor,
                offset_x_mm=self.settings.sheet_offset_x_mm,
                offset_y_mm=self.settings.sheet_offset_y_mm,
                pass_cols=pass_cols,
                pass_rows=pass_rows,
                pass_col=pass_col,
                pass_row=pass_row,
            )
        return SheetConfig(
            sheet_format=fmt,
            anchor=self.settings.sheet_anchor,
            offset_x_mm=self.settings.sheet_offset_x_mm,
            offset_y_mm=self.settings.sheet_offset_y_mm,
            pass_cols=pass_cols,
            pass_rows=pass_rows,
            pass_col=pass_col,
            pass_row=pass_row,
        )

    def _require_connection(self) -> bool:
        if self.connected and self.connected_port:
            return True
        self.toast.emit("error", "Подключитесь к плоттеру перед выполнением команды.")
        return False

    def connect_port(self, com_port: str) -> None:
        port = (com_port or self.settings.com_port or "").strip()
        if not port:
            self.toast.emit("error", "Выберите COM-порт.")
            return
        self.set_selected_port(port)

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_log(f"Проверка подключения к {port}...")
            ok, text = self.bridge.probe_connection(port, self.baud, ctx.emit_log)
            if not ok:
                return False, f"Не удалось подключиться к {port}: {text}"
            return True, f"Подключено к {port}"

        self._set_connection_state(False, "Подключение...", "connecting")
        self._enqueue("connect", f"Подключение {port}...", handler, com_port=port)

    def disconnect(self) -> None:
        if not self.connected:
            self._set_connection_state(False, "Отключено", "neutral")
            return
        port = self.connected_port

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_log("Отключение: отпуск моторов и завершение сессии...")
            self.bridge.manual_commands(
                port,
                self.baud,
                ["$X", "M5", "$1=0", "$SLP", "?"],
                soft_reset_first=False,
                read_tail=True,
            )
            return True, "Отключено"

        self._enqueue("disconnect", "Отключение...", handler, com_port=port)

    def cancel_active_operation(self) -> None:
        self.worker.cancel_current()
        if self.connected and self.connected_port:
            port = self.connected_port

            def stop_now() -> None:
                ok, text = self.bridge.emergency_stop(port, self.baud, self.log_line.emit)
                if ok:
                    self.toast.emit("error", "Операция остановлена. Команда аварийного стопа отправлена.")
                elif text:
                    self.toast.emit("error", f"Не удалось отправить аварийный стоп: {text}")

            threading.Thread(target=stop_now, daemon=True).start()
        else:
            self.toast.emit("error", "Операция отменена.")

    def run_calibration(self) -> None:
        if not self._require_connection():
            return
        port = self.connected_port
        sheet = self.sheet_config()

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_progress(10, "Подготовка калибровки...")
            ok, msg = self.bridge.run_calibration(ctx, port, self.baud, sheet, ctx.emit_log)
            rel_ok, rel_msg = self._release_idle_motors_in_operation(ctx, port)
            if ok and rel_ok:
                return True, f"{msg} | {rel_msg}"
            if not ok:
                return False, msg
            return True, msg

        self._enqueue("calibration", "Калибровка 4 углов...", handler, com_port=port)

    def run_frame(self) -> None:
        if not self._require_connection():
            return
        port = self.connected_port
        sheet = self.sheet_config()

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_progress(10, "Подготовка рамки...")
            ok, msg = self.bridge.run_frame(ctx, port, self.baud, sheet, ctx.emit_log)
            rel_ok, rel_msg = self._release_idle_motors_in_operation(ctx, port)
            if ok and rel_ok:
                return True, f"{msg} | {rel_msg}"
            if not ok:
                return False, msg
            return True, msg

        self._enqueue("frame", "Рисование рамки активной зоны...", handler, com_port=port)

    def draw_file(self, file_path: Path) -> None:
        if not self._require_connection():
            return
        if not file_path.exists():
            self.toast.emit("error", f"Файл не найден: {file_path}")
            return
        if file_path.suffix.lower() not in {".pdf", ".svg", ".frw", ".cdw", ".doc", ".docx"}:
            self.toast.emit("error", "Поддерживаются файлы: PDF, SVG, FRW, CDW, DOC, DOCX.")
            return
        port = self.connected_port
        sheet = self.sheet_config()
        tool = self.settings.tool_mode
        cal = self.settings.calibrate_before_draw
        render_mode = self.settings.render_mode
        quality_profile = self.settings.quality_profile
        force_text_to_path = self.settings.force_text_to_path
        handwriting_enabled = self.settings.handwriting_enabled
        handwriting_font = self.settings.handwriting_font
        handwriting_formula_font = self.settings.handwriting_formula_font
        image_contours_mode = self.settings.image_contours_mode
        source_page_index = max(1, int(self.settings.source_page_index or 1))
        source_all_pages = bool(self.settings.source_all_pages)
        if file_path.suffix.lower() in {".doc", ".docx"}:
            if render_mode != "handwriting" or not handwriting_enabled:
                render_mode = "handwriting"
                handwriting_enabled = True
                self.log_line.emit("Word input: handwriting mode forced for this job.")
            if image_contours_mode == "off":
                image_contours_mode = "word_only"
                self.log_line.emit("Word input: image contours forced to word_only.")
        exact_geometry_mode = self.settings.exact_geometry_mode
        safe_travel_lift = self.settings.safe_travel_lift
        strict_one_to_one = self.settings.strict_one_to_one or (
            sheet.sheet_format == "a3" and sheet.pass_cols > 1
        )
        self.update_ui_settings(last_file=str(file_path))
        previews_dir = self.project_root / "_tmp"
        previews_dir.mkdir(parents=True, exist_ok=True)
        expected_draw_preview = str(previews_dir / "latest_draw_vector.svg")

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_progress(10, "Подготовка траектории...")
            ok, msg = self.bridge.run_draw(
                ctx=ctx,
                input_path=file_path,
                com_port=port,
                baud=self.baud,
                sheet=sheet,
                tool_mode=tool,
                calibrate_before_draw=cal,
                render_mode=render_mode,
                quality_profile=quality_profile,
                force_text_to_path=force_text_to_path,
                handwriting_enabled=handwriting_enabled,
                handwriting_font=handwriting_font,
                handwriting_formula_font=handwriting_formula_font,
                image_contours_mode=image_contours_mode,
                source_page_index=source_page_index,
                source_all_pages=source_all_pages,
                exact_geometry_mode=exact_geometry_mode,
                safe_travel_lift=safe_travel_lift,
                strict_one_to_one=strict_one_to_one,
                log=ctx.emit_log,
            )
            rel_ok, rel_msg = self._release_idle_motors_in_operation(ctx, port)
            if ok and rel_ok:
                return True, f"{msg} | {rel_msg}"
            if not ok:
                return False, msg
            return True, msg

        self._enqueue(
            "draw",
            "Отправка задания на рисование...",
            handler,
            com_port=port,
            payload=expected_draw_preview,
        )

    def preview_file(self, file_path: Path) -> None:
        if not file_path.exists():
            self.toast.emit("error", f"Файл не найден: {file_path}")
            return
        if file_path.suffix.lower() not in {".pdf", ".svg", ".frw", ".cdw", ".doc", ".docx"}:
            self.toast.emit("error", "Поддерживаются файлы: PDF, SVG, FRW, CDW, DOC, DOCX.")
            return

        sheet = self.sheet_config()
        tool = self.settings.tool_mode
        render_mode = self.settings.render_mode
        quality_profile = self.settings.quality_profile
        force_text_to_path = self.settings.force_text_to_path
        handwriting_enabled = self.settings.handwriting_enabled
        handwriting_font = self.settings.handwriting_font
        handwriting_formula_font = self.settings.handwriting_formula_font
        image_contours_mode = self.settings.image_contours_mode
        source_page_index = max(1, int(self.settings.source_page_index or 1))
        source_all_pages = bool(self.settings.source_all_pages)
        if file_path.suffix.lower() in {".doc", ".docx"}:
            if render_mode != "handwriting" or not handwriting_enabled:
                render_mode = "handwriting"
                handwriting_enabled = True
                self.log_line.emit("Word input: handwriting mode forced for preview.")
            if image_contours_mode == "off":
                image_contours_mode = "word_only"
                self.log_line.emit("Word input: image contours forced to word_only.")
        exact_geometry_mode = self.settings.exact_geometry_mode
        safe_travel_lift = self.settings.safe_travel_lift
        strict_one_to_one = self.settings.strict_one_to_one or (
            sheet.sheet_format == "a3" and sheet.pass_cols > 1
        )
        self.update_ui_settings(last_file=str(file_path))

        previews_dir = self.project_root / "_tmp"
        previews_dir.mkdir(parents=True, exist_ok=True)
        expected_preview = str(previews_dir / "latest_preview_vector.svg")

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_progress(10, "Подготовка предпросмотра...")
            ok, msg = self.bridge.run_preview(
                ctx=ctx,
                input_path=file_path,
                sheet=sheet,
                tool_mode=tool,
                render_mode=render_mode,
                quality_profile=quality_profile,
                force_text_to_path=force_text_to_path,
                handwriting_enabled=handwriting_enabled,
                handwriting_font=handwriting_font,
                handwriting_formula_font=handwriting_formula_font,
                image_contours_mode=image_contours_mode,
                source_page_index=source_page_index,
                source_all_pages=source_all_pages,
                exact_geometry_mode=exact_geometry_mode,
                safe_travel_lift=safe_travel_lift,
                strict_one_to_one=strict_one_to_one,
                log=ctx.emit_log,
            )
            if ok:
                svg_path = self._extract_preview_path(msg)
                if svg_path:
                    self.update_ui_settings(last_preview_svg=svg_path)
            return ok, msg

        payload = self.settings.last_preview_svg or expected_preview
        self._enqueue("preview", "Подготовка предпросмотра...", handler, payload=payload)

    def run_wear_test(self) -> None:
        if not self._require_connection():
            return
        port = self.connected_port
        sheet = self.sheet_config()

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ctx.emit_progress(10, "Подготовка теста износа...")
            ok, msg = self.bridge.run_wear_test(ctx, port, self.baud, sheet, ctx.emit_log)
            rel_ok, rel_msg = self._release_idle_motors_in_operation(ctx, port)
            if ok and rel_ok:
                return True, f"{msg} | {rel_msg}"
            if not ok:
                return False, msg
            return True, msg

        self._enqueue("wear_test", "Тест износа карандаша...", handler, com_port=port)

    def pen_step(self, *, down: bool, step_mm: float, feed: float) -> None:
        if not self._require_connection():
            return
        port = self.connected_port
        step = max(0.1, float(step_mm))
        feed_v = max(20.0, float(feed))
        sign = self.bridge.z_down_sign()
        delta = sign * step if down else -sign * step
        title = "Опускание пера..." if down else "Подъём пера..."

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ok, tail = self.bridge.manual_commands(
                port,
                self.baud,
                ["$X", "$1=255", "G21", "G91", f"G1 Z{delta:.3f} F{feed_v:.1f}", "G90", "?"],
                soft_reset_first=True,
                read_tail=True,
            )
            if tail:
                for line in tail.splitlines():
                    ctx.emit_log(line)
            if ok:
                action = "опущено" if down else "поднято"
                return True, f"Перо {action} на {step:.2f} мм"
            return False, f"Команда не выполнена: {tail}"

        self._enqueue("manual", title, handler, com_port=port)

    def release_motors(self) -> None:
        selected_ports = self._release_port_candidates()
        if not selected_ports:
            self.toast.emit("error", "Выберите COM-порт.")
            return

        def handler(ctx: OperationContext) -> tuple[bool, str]:
            ports = list(selected_ports)
            try:
                suggested = (self.bridge.detect_com_port(None) or "").strip()
                if suggested and suggested not in ports:
                    ports.append(suggested)
            except Exception:
                pass

            last_err = ""
            for port in ports:
                ctx.emit_log(f"Пробую отпуск моторов через {port}...")
                ok, tail = self.bridge.manual_commands(
                    port,
                    self.baud,
                    ["$X", "G90", "G1 Z0 F800", "G4 P0.05", "M5", "$1=0", "?", "$SLP"],
                    soft_reset_first=True,
                    read_tail=True,
                )
                if tail:
                    for line in tail.splitlines():
                        ctx.emit_log(line)
                if ok and self._is_grbl_tail(tail):
                    return True, f"Моторы отпущены ({port})"
                if ok and not self._is_grbl_tail(tail):
                    last_err = f"{port}: нет подтверждения GRBL"
                else:
                    last_err = tail or "нет ответа"
            return False, f"Не удалось отпустить моторы: {last_err}"

        self._enqueue("manual", "Отпуск моторов...", handler, com_port=selected_ports[0])

    def mark_pencil_sharpened(self) -> None:
        def handler(ctx: OperationContext) -> tuple[bool, str]:
            return self.bridge.reset_pencil_after_sharpen(ctx.emit_log)

        self._enqueue("pencil_sharpened", "Сброс состояния карандаша...", handler, com_port=self.connected_port or None)

    def refresh_pencil_banner(self) -> None:
        text, alert = self.bridge.pencil_banner_text()
        self.pencil_banner_changed.emit(text, alert)
