from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plotter_studio.core.serial_worker import OperationContext, SerialWorker, WorkerOperation


class _SignalStub:
    def __init__(self) -> None:
        self.values: list[str] = []

    def emit(self, value: str) -> None:
        self.values.append(value)


class _WorkerStub:
    def __init__(self) -> None:
        self.cancel_event = mock.Mock()
        self.cancel_event.is_set.return_value = False
        self.log_line = _SignalStub()
        self.progress = mock.Mock()

    def set_active_process(self, _proc) -> None:
        return None


class SerialWorkerDiagnosticsTests(unittest.TestCase):
    def test_operation_context_emit_log_prefixes_operation_id(self) -> None:
        worker = _WorkerStub()
        ctx = OperationContext(worker, "op-123")
        ctx.emit_log("hello")
        self.assertEqual(worker.log_line.values, ["[op-123] hello"])

    def test_write_operation_diagnostic_creates_json_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plotter_diag_") as td:
            root = Path(td)
            op = WorkerOperation(op_id="op-diag-1", title="Preview", handler=lambda _ctx: (True, "ok"))
            with mock.patch("plotter_studio.core.serial_worker.Path.cwd", return_value=root):
                SerialWorker._write_operation_diagnostic(
                    op=op,
                    ok=False,
                    message="failed",
                    error_trace="traceback",
                )

            report = root / "_tmp" / "diagnostics" / "op-diag-1.json"
            self.assertTrue(report.exists(), "Diagnostic report file was not created")
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("op_id"), "op-diag-1")
            self.assertEqual(payload.get("title"), "Preview")
            self.assertFalse(bool(payload.get("ok")))
            self.assertEqual(payload.get("message"), "failed")
            self.assertEqual(payload.get("error_trace"), "traceback")
            self.assertTrue(str(payload.get("timestamp_utc", "")).strip())

    def test_cancel_current_without_process_sets_cancel_flag(self) -> None:
        worker = SerialWorker()
        worker.cancel_event.clear()
        worker.cancel_current()
        self.assertTrue(worker.cancel_event.is_set())

    def test_cancel_current_terminates_running_process(self) -> None:
        class _Proc:
            def __init__(self) -> None:
                self.terminated = False
                self.killed = False
                self.wait_called = False

            def poll(self):
                return None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: float = 0.0) -> int:
                self.wait_called = True
                return 0

            def kill(self) -> None:
                self.killed = True

        worker = SerialWorker()
        proc = _Proc()
        worker.set_active_process(proc)
        worker.cancel_current()
        self.assertTrue(proc.terminated)
        self.assertTrue(proc.wait_called)
        self.assertFalse(proc.killed)

    def test_cancel_current_kills_process_when_wait_fails(self) -> None:
        class _Proc:
            def __init__(self) -> None:
                self.terminated = False
                self.killed = False
                self.wait_called = False

            def poll(self):
                return None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: float = 0.0) -> int:
                self.wait_called = True
                raise TimeoutError("wait timeout")

            def kill(self) -> None:
                self.killed = True

        worker = SerialWorker()
        proc = _Proc()
        worker.set_active_process(proc)
        worker.cancel_current()
        self.assertTrue(proc.terminated)
        self.assertTrue(proc.wait_called)
        self.assertTrue(proc.killed)

    def test_enqueue_and_shutdown_push_items_into_queue(self) -> None:
        worker = SerialWorker()
        op = WorkerOperation(op_id="op-1", title="Op", handler=lambda _ctx: (True, "ok"))
        worker.enqueue(op)
        self.assertIs(worker._queue.get_nowait(), op)  # type: ignore[attr-defined]
        worker.shutdown()
        self.assertIsNone(worker._queue.get_nowait())  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
