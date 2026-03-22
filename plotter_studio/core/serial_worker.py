from __future__ import annotations

import json
import queue
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


class Signal:
    def __init__(self) -> None:
        self._subscribers: list[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        if callable(callback):
            self._subscribers.append(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for callback in list(self._subscribers):
            callback(*args, **kwargs)


class OperationCanceledError(RuntimeError):
    pass


@dataclass
class WorkerOperation:
    op_id: str
    title: str
    handler: Callable[["OperationContext"], tuple[bool, str]]


class OperationContext:
    def __init__(self, worker: "SerialWorker | Any", op_id: str) -> None:
        self._worker = worker
        self._op_id = str(op_id or "").strip() or "op-unknown"

    @property
    def op_id(self) -> str:
        return self._op_id

    @property
    def cancel_event(self) -> threading.Event:
        return self._worker.cancel_event

    def is_canceled(self) -> bool:
        return self.cancel_event.is_set()

    def check_canceled(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCanceledError("Операция отменена пользователем.")

    def set_active_process(self, proc) -> None:
        self._worker.set_active_process(proc)

    def emit_log(self, text: str) -> None:
        self._worker.log_line.emit(f"[{self._op_id}] {text}")

    def emit_progress(self, value: int, text: str = "") -> None:
        self._worker.progress.emit(value, text)


class SerialWorker:
    def __init__(self) -> None:
        self.operation_started = Signal()
        self.operation_finished = Signal()
        self.busy_changed = Signal()
        self.progress = Signal()
        self.log_line = Signal()

        self._queue: queue.Queue[Optional[WorkerOperation]] = queue.Queue()
        self._active_process = None
        self._active_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run, name="serial-worker", daemon=True)
        self._thread.start()

    def wait(self, timeout_ms: Optional[int] = None) -> bool:
        if self._thread is None:
            return True
        timeout_s = None if timeout_ms is None else max(0.0, float(timeout_ms) / 1000.0)
        self._thread.join(timeout_s)
        return not self._thread.is_alive()

    def enqueue(self, operation: WorkerOperation) -> None:
        self._queue.put(operation)

    def shutdown(self) -> None:
        self._queue.put(None)

    def cancel_current(self) -> None:
        self.cancel_event.set()
        with self._active_lock:
            proc = self._active_process
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
        except Exception:
            pass

    def set_active_process(self, proc) -> None:
        with self._active_lock:
            self._active_process = proc

    @staticmethod
    def _write_operation_diagnostic(
        *,
        op: WorkerOperation,
        ok: bool,
        message: str,
        error_trace: str = "",
    ) -> None:
        try:
            diagnostics_dir = Path.cwd() / "_tmp" / "diagnostics"
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "op_id": str(op.op_id),
                "title": str(op.title),
                "ok": bool(ok),
                "message": str(message or ""),
                "error_trace": str(error_trace or ""),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            target = diagnostics_dir / f"{op.op_id}.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def run(self) -> None:
        while True:
            op = self._queue.get()
            if op is None:
                return
            self.cancel_event.clear()
            self.set_active_process(None)
            self.busy_changed.emit(True)
            self.progress.emit(0, op.title)
            self.operation_started.emit(op.op_id, op.title)
            self.log_line.emit(f"[{op.op_id}] operation started: {op.title}")
            ok = False
            message = ""
            error_trace = ""
            try:
                context = OperationContext(self, op.op_id)
                ok, message = op.handler(context)
                if context.is_canceled():
                    ok = False
                    message = "Операция отменена пользователем."
            except OperationCanceledError as exc:
                ok = False
                message = str(exc)
            except Exception as exc:
                ok = False
                message = f"{type(exc).__name__}: {exc}"
                error_trace = traceback.format_exc()
                self.log_line.emit(error_trace)
            finally:
                self.set_active_process(None)
                self.busy_changed.emit(False)
                self.progress.emit(0, "")
                self._write_operation_diagnostic(
                    op=op,
                    ok=ok,
                    message=message,
                    error_trace=error_trace,
                )
                self.log_line.emit(f"[{op.op_id}] operation finished: ok={str(bool(ok)).lower()}")
                self.operation_finished.emit(op.op_id, ok, message)
