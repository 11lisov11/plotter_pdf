from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from plotter_studio.core import plotter_controller as controller_mod
from plotter_studio.core.plotter_controller import PlotterController
from plotter_studio.core.settings import AppSettingsData
from plotter_studio.ui.main_window import MainWindow


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
        self.cancel_called = False

    def start(self) -> None:
        self.started = True

    def enqueue(self, operation) -> None:
        self.enqueued.append(operation)

    def shutdown(self) -> None:
        self.shutdown_called = True

    def wait(self, _timeout_ms: int) -> bool:
        return True

    def cancel_current(self) -> None:
        self.cancel_called = True


class _FakeSettingsStore:
    def __init__(self) -> None:
        self.saved: list[AppSettingsData] = []

    def load(self) -> AppSettingsData:
        return AppSettingsData()

    def save(self, data: AppSettingsData) -> None:
        self.saved.append(data)


class _FakeBridge:
    def __init__(self, _project_root: Path) -> None:
        self.ports = ["COM6"]

    def default_baud(self) -> str:
        return "115200"

    def list_com_ports(self) -> list[str]:
        return list(self.ports)

    def set_tool_mode(self, _mode: str) -> None:
        return None

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

    def probe_connection(self, *_args, **_kwargs):
        return True, "ok"


class MainWindowHeadlessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

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
        self.window = MainWindow(self.controller)
        self.window._animate_log_drawer = lambda target: self.window.log_drawer.setMaximumHeight(max(0, int(target)))  # type: ignore[method-assign]

    def tearDown(self) -> None:
        try:
            self.window.close()
        except Exception:
            pass
        QApplication.processEvents()

    def test_connection_lock_states_toggle_controls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_ui_conn_") as td:
            src = Path(td) / "sample.pdf"
            src.write_bytes(b"%PDF-1.4\n")
            self.window.file_page.set_file_path(str(src))
            QApplication.processEvents()

            self.assertFalse(self.window.calibration_page.calibrate_btn.isEnabled())
            self.assertFalse(self.window.file_page.draw_btn.isEnabled())
            self.assertFalse(self.window.manual_page.down_btn.isEnabled())

            self.controller.connected = True
            self.controller.connected_port = "COM6"
            self.controller.connection_changed.emit(True, "Connected COM6", "ok")
            QApplication.processEvents()

            self.assertTrue(self.window.calibration_page.calibrate_btn.isEnabled())
            self.assertTrue(self.window.file_page.draw_btn.isEnabled())
            self.assertTrue(self.window.manual_page.down_btn.isEnabled())

            self.controller.connected = False
            self.controller.connected_port = ""
            self.controller.connection_changed.emit(False, "Disconnected", "neutral")
            QApplication.processEvents()

            self.assertFalse(self.window.calibration_page.calibrate_btn.isEnabled())
            self.assertFalse(self.window.file_page.draw_btn.isEnabled())
            self.assertFalse(self.window.manual_page.down_btn.isEnabled())

    def test_preview_and_draw_buttons_enqueue_operations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_ui_dispatch_") as td:
            src = Path(td) / "sample.pdf"
            src.write_bytes(b"%PDF-1.4\n")

            self.controller.connected = True
            self.controller.connected_port = "COM6"
            self.controller.connection_changed.emit(True, "Connected COM6", "ok")
            self.window.file_page.set_file_path(str(src))
            QApplication.processEvents()

            initial = len(self.controller.worker.enqueued)
            self.window.file_page.preview_btn.click()
            self.window.file_page.draw_btn.click()
            QApplication.processEvents()

            self.assertEqual(len(self.controller.worker.enqueued), initial + 2)
            op_types = [meta.op_type for meta in self.controller._operations.values()]
            self.assertIn("preview", op_types)
            self.assertIn("draw", op_types)

    def test_stop_button_calls_cancel_and_emergency_stop(self) -> None:
        calls: list[tuple[str, str]] = []

        def _emergency_stop(port: str, baud: str, _logger):
            calls.append((port, baud))
            return True, "ok"

        self.controller.connected = True
        self.controller.connected_port = "COM6"
        self.controller.bridge.emergency_stop = _emergency_stop  # type: ignore[method-assign]

        self.window._on_busy_changed(True)
        self.window.stop_btn.click()
        for _ in range(40):
            QApplication.processEvents()
            if calls:
                break
            time.sleep(0.01)

        self.assertTrue(self.controller.worker.cancel_called)
        self.assertTrue(calls)
        self.assertEqual(calls[-1][0], "COM6")

    def test_hidden_log_drawer_counts_unread_and_resets_on_open(self) -> None:
        self.window._set_log_drawer_visible(False)
        self.window._append_log("line-one")
        QApplication.processEvents()
        self.assertIn("(1)", self.window.log_toggle_btn.text())

        self.window._set_log_drawer_visible(True)
        QApplication.processEvents()
        self.assertNotIn("(1)", self.window.log_toggle_btn.text())
        self.assertTrue(self.controller.settings.log_drawer_open)


if __name__ == "__main__":
    unittest.main()
