from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication

from plotter_studio.core import plotter_controller as controller_mod
from plotter_studio.core.plotter_controller import OperationMeta, PlotterController
from plotter_studio.core.settings import AppSettingsData


class _DummySignal:
    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args, **kwargs) -> None:
        for slot in list(self._slots):
            slot(*args, **kwargs)


class _FakeWorker:
    def __init__(self) -> None:
        self.operation_started = _DummySignal()
        self.operation_finished = _DummySignal()
        self.log_line = _DummySignal()
        self.busy_changed = _DummySignal()
        self.progress = _DummySignal()
        self.enqueued = []
        self.started = False
        self.shutdown_called = False

    def start(self) -> None:
        self.started = True

    def enqueue(self, operation) -> None:
        self.enqueued.append(operation)

    def shutdown(self) -> None:
        self.shutdown_called = True

    def wait(self, _timeout_ms: int) -> bool:
        return True

    def cancel_current(self) -> None:
        return None


class _FakeSettingsStore:
    def __init__(self) -> None:
        self.saved: list[AppSettingsData] = []

    def load(self) -> AppSettingsData:
        return AppSettingsData()

    def save(self, data: AppSettingsData) -> None:
        self.saved.append(data)


class _FakeBridge:
    def __init__(self, _project_root: Path) -> None:
        self.ports = ["COM6", "COM9"]
        self.tool_mode_calls: list[str] = []

    def default_baud(self) -> str:
        return "115200"

    def list_com_ports(self) -> list[str]:
        return list(self.ports)

    def set_tool_mode(self, mode: str) -> None:
        self.tool_mode_calls.append(mode)

    def pencil_banner_text(self) -> tuple[str, bool]:
        return ("Pencil OK", False)

    def detect_com_port(self, _preferred=None) -> str:
        return "COM6"

    def z_down_sign(self) -> float:
        return 1.0

    def emergency_stop(self, *_args, **_kwargs):
        return True, "ok"

    def manual_commands(self, *_args, **_kwargs):
        return True, "ok"


class PlotterControllerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self._settings_store_patch = mock.patch.object(controller_mod, "SettingsStore", _FakeSettingsStore)
        self._bridge_patch = mock.patch.object(controller_mod, "BackendBridge", _FakeBridge)
        self._worker_patch = mock.patch.object(controller_mod, "SerialWorker", _FakeWorker)
        self._settings_store_patch.start()
        self._bridge_patch.start()
        self._worker_patch.start()
        self.addCleanup(self._settings_store_patch.stop)
        self.addCleanup(self._bridge_patch.stop)
        self.addCleanup(self._worker_patch.stop)

        self.controller = PlotterController(Path.cwd())
        self.addCleanup(self.controller.shutdown)

    def test_refresh_ports_prefers_connected_port(self) -> None:
        selected_calls: list[tuple[list[str], str]] = []
        self.controller.ports_changed.connect(lambda ports, selected: selected_calls.append((list(ports), selected)))

        self.controller.connected = True
        self.controller.connected_port = "COM9"
        self.controller.bridge.ports = ["COM1", "COM9"]
        self.controller.refresh_ports()

        self.assertTrue(selected_calls)
        ports, selected = selected_calls[-1]
        self.assertEqual(selected, "COM9")
        self.assertIn("COM9", ports)

    def test_refresh_ports_falls_back_to_com6(self) -> None:
        selected_calls: list[tuple[list[str], str]] = []
        self.controller.ports_changed.connect(lambda ports, selected: selected_calls.append((list(ports), selected)))

        self.controller.connected = False
        self.controller.connected_port = ""
        self.controller.settings.com_port = ""
        self.controller.bridge.ports = ["COM2", "COM6", "COM8"]
        self.controller.refresh_ports()

        ports, selected = selected_calls[-1]
        self.assertEqual(selected, "COM6")
        self.assertEqual(self.controller.settings.com_port, "COM6")
        self.assertIn("COM6", ports)

    def test_refresh_ports_inserts_saved_port_when_no_detected_ports(self) -> None:
        selected_calls: list[tuple[list[str], str]] = []
        self.controller.ports_changed.connect(lambda ports, selected: selected_calls.append((list(ports), selected)))

        self.controller.settings.com_port = "COM77"
        self.controller.bridge.ports = []
        self.controller.refresh_ports()

        ports, selected = selected_calls[-1]
        self.assertEqual(selected, "COM77")
        self.assertEqual(ports, ["COM77"])

    def test_on_operation_finished_connect_success_updates_connection_state(self) -> None:
        toasts: list[tuple[str, str]] = []
        conn_state: list[tuple[bool, str, str]] = []
        self.controller.toast.connect(lambda level, text: toasts.append((level, text)))
        self.controller.connection_changed.connect(
            lambda connected, label, level: conn_state.append((connected, label, level))
        )

        op_id = "op-connect"
        self.controller._operations[op_id] = OperationMeta(op_type="connect", com_port="COM8")
        self.controller._on_operation_finished(op_id, True, "Connected")

        self.assertTrue(self.controller.connected)
        self.assertEqual(self.controller.connected_port, "COM8")
        self.assertNotIn(op_id, self.controller._operations)
        self.assertIn(("success", "Connected"), toasts)
        self.assertTrue(any(s[0] and "COM8" in s[1] for s in conn_state))

    def test_on_operation_finished_disconnect_resets_connection_state(self) -> None:
        self.controller.connected = True
        self.controller.connected_port = "COM6"

        op_id = "op-disconnect"
        self.controller._operations[op_id] = OperationMeta(op_type="disconnect")
        self.controller._on_operation_finished(op_id, True, "Disconnected")

        self.assertFalse(self.controller.connected)
        self.assertEqual(self.controller.connected_port, "")

    def test_on_operation_finished_preview_uses_payload_fallback(self) -> None:
        previews: list[str] = []
        updated: dict[str, object] = {}
        self.controller.preview_ready.connect(lambda path: previews.append(path))
        self.controller.update_ui_settings = lambda **kwargs: updated.update(kwargs)  # type: ignore[method-assign]

        op_id = "op-preview"
        payload = r"C:\tmp\fallback_preview.svg"
        self.controller._operations[op_id] = OperationMeta(op_type="preview", payload=payload)
        self.controller._on_operation_finished(op_id, True, "Done")

        self.assertEqual(previews[-1], payload)
        self.assertEqual(updated.get("last_preview_svg"), payload)

    def test_on_operation_finished_preview_uses_message_marker_first(self) -> None:
        previews: list[str] = []
        updated: dict[str, object] = {}
        self.controller.preview_ready.connect(lambda path: previews.append(path))
        self.controller.update_ui_settings = lambda **kwargs: updated.update(kwargs)  # type: ignore[method-assign]

        op_id = "op-preview-msg"
        payload = r"C:\tmp\payload.svg"
        marker = r"C:\tmp\from_message.svg"
        self.controller._operations[op_id] = OperationMeta(op_type="preview", payload=payload)
        self.controller._on_operation_finished(op_id, True, f"Preview ready: {marker} | PDF: x")

        self.assertEqual(previews[-1], marker)
        self.assertEqual(updated.get("last_preview_svg"), marker)

    def test_require_connection_false_emits_error_toast(self) -> None:
        toasts: list[tuple[str, str]] = []
        self.controller.toast.connect(lambda level, text: toasts.append((level, text)))
        self.controller.connected = False
        self.controller.connected_port = ""

        ok = self.controller._require_connection()
        self.assertFalse(ok)
        self.assertTrue(any(level == "error" for level, _ in toasts))

    def test_sheet_config_custom_and_a3_two_pass(self) -> None:
        self.controller.update_ui_settings(
            sheet_format="custom",
            custom_w_mm=210.0,
            custom_h_mm=99.0,
            sheet_anchor="upper_left",
            sheet_offset_x_mm=2.5,
            sheet_offset_y_mm=-3.0,
            a3_two_pass=True,
            a3_pass_index=2,
        )
        cfg = self.controller.sheet_config()
        self.assertEqual(cfg.sheet_format, "custom")
        self.assertAlmostEqual(float(cfg.width_mm or 0.0), 210.0, places=6)
        self.assertAlmostEqual(float(cfg.height_mm or 0.0), 99.0, places=6)
        self.assertEqual(cfg.anchor, "upper_left")
        self.assertEqual(cfg.pass_cols, 1)
        self.assertEqual(cfg.pass_col, 1)

        self.controller.update_ui_settings(sheet_format="a3", a3_two_pass=True, a3_pass_index=2)
        cfg_a3 = self.controller.sheet_config()
        self.assertEqual(cfg_a3.sheet_format, "a3")
        self.assertEqual(cfg_a3.pass_cols, 2)
        self.assertEqual(cfg_a3.pass_col, 2)

    def test_connect_port_without_value_emits_error(self) -> None:
        toasts: list[tuple[str, str]] = []
        self.controller.toast.connect(lambda level, text: toasts.append((level, text)))
        self.controller.settings.com_port = ""

        self.controller.connect_port("")
        self.assertTrue(any(level == "error" for level, _ in toasts))

    def test_connect_port_enqueues_operation(self) -> None:
        states: list[tuple[bool, str, str]] = []
        self.controller.connection_changed.connect(lambda a, b, c: states.append((a, b, c)))

        self.controller.connect_port("COM5")
        self.assertTrue(self.controller.worker.enqueued)
        op = self.controller.worker.enqueued[-1]
        self.assertIn("COM5", op.title)
        self.assertTrue(any(level == "connecting" for _a, _b, level in states))

    def test_draw_file_rejects_missing_or_unsupported_input(self) -> None:
        toasts: list[tuple[str, str]] = []
        self.controller.toast.connect(lambda level, text: toasts.append((level, text)))
        self.controller.connected = True
        self.controller.connected_port = "COM6"

        self.controller.draw_file(Path("C:/definitely/missing_file.pdf"))
        self.assertTrue(any(level == "error" for level, _text in toasts))

        with tempfile.TemporaryDirectory(prefix="plotter_ctrl_draw_") as td:
            bad = Path(td) / "input.txt"
            bad.write_text("x", encoding="utf-8")
            self.controller.draw_file(bad)
        self.assertGreaterEqual(sum(1 for level, _text in toasts if level == "error"), 2)

    def test_draw_file_docx_forces_handwriting_and_word_contours(self) -> None:
        self.controller.connected = True
        self.controller.connected_port = "COM6"
        self.controller.settings.render_mode = "drawing"
        self.controller.settings.handwriting_enabled = False
        self.controller.settings.image_contours_mode = "off"

        enqueued: list[tuple[str, str, object, dict[str, object]]] = []
        logs: list[str] = []
        self.controller.log_line.connect(logs.append)

        def _capture_enqueue(op_type: str, title: str, handler, **kwargs) -> None:
            enqueued.append((op_type, title, handler, kwargs))

        self.controller._enqueue = _capture_enqueue  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory(prefix="plotter_ctrl_docx_draw_") as td:
            docx = Path(td) / "input.docx"
            docx.write_text("docx stub", encoding="utf-8")
            self.controller.draw_file(docx)

        self.assertTrue(enqueued)
        op_type, _title, _handler, kwargs = enqueued[-1]
        self.assertEqual(op_type, "draw")
        self.assertIn("latest_draw_vector.svg", str(kwargs.get("payload", "")))
        self.assertTrue(any("handwriting mode forced for this job" in line for line in logs))
        self.assertTrue(any("image contours forced to word_only" in line for line in logs))

    def test_preview_file_docx_forces_handwriting_and_word_contours(self) -> None:
        self.controller.settings.render_mode = "drawing"
        self.controller.settings.handwriting_enabled = False
        self.controller.settings.image_contours_mode = "off"

        enqueued: list[tuple[str, str, object, dict[str, object]]] = []
        logs: list[str] = []
        self.controller.log_line.connect(logs.append)

        def _capture_enqueue(op_type: str, title: str, handler, **kwargs) -> None:
            enqueued.append((op_type, title, handler, kwargs))

        self.controller._enqueue = _capture_enqueue  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory(prefix="plotter_ctrl_docx_prev_") as td:
            docx = Path(td) / "input.docx"
            docx.write_text("docx stub", encoding="utf-8")
            self.controller.preview_file(docx)

        self.assertTrue(enqueued)
        op_type, _title, _handler, kwargs = enqueued[-1]
        self.assertEqual(op_type, "preview")
        self.assertIn("latest_preview_vector.svg", str(kwargs.get("payload", "")))
        self.assertTrue(any("handwriting mode forced for preview" in line for line in logs))
        self.assertTrue(any("image contours forced to word_only" in line for line in logs))

    def test_preview_file_rejects_missing_and_unsupported_input(self) -> None:
        toasts: list[tuple[str, str]] = []
        self.controller.toast.connect(lambda level, text: toasts.append((level, text)))

        self.controller.preview_file(Path("C:/definitely/missing_file.pdf"))
        self.assertTrue(any(level == "error" for level, _text in toasts))

        with tempfile.TemporaryDirectory(prefix="plotter_ctrl_prev_") as td:
            bad = Path(td) / "input.txt"
            bad.write_text("x", encoding="utf-8")
            self.controller.preview_file(bad)
        self.assertGreaterEqual(sum(1 for level, _text in toasts if level == "error"), 2)

    def test_sheet_swap_confirmation_wait_returns_true_after_response(self) -> None:
        calls: list[tuple[int, int, str]] = []

        def _on_request(completed_page: int, total_pages: int, source_name: str) -> None:
            calls.append((completed_page, total_pages, source_name))
            self.controller.respond_sheet_swap_confirmation(True)

        self.controller.sheet_swap_confirmation_requested.connect(_on_request)
        result = self.controller._wait_for_sheet_swap_confirmation(1, 3, "article.pdf")
        self.assertTrue(result)
        self.assertEqual(calls, [(1, 3, "article.pdf")])

    def test_sheet_swap_confirmation_wait_returns_false_after_response(self) -> None:
        calls: list[tuple[int, int, str]] = []

        def _on_request(completed_page: int, total_pages: int, source_name: str) -> None:
            calls.append((completed_page, total_pages, source_name))
            self.controller.respond_sheet_swap_confirmation(False)

        self.controller.sheet_swap_confirmation_requested.connect(_on_request)
        result = self.controller._wait_for_sheet_swap_confirmation(2, 5, "paper.pdf")
        self.assertFalse(result)
        self.assertEqual(calls, [(2, 5, "paper.pdf")])


if __name__ == "__main__":
    unittest.main()
