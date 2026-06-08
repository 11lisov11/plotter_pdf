from __future__ import annotations

import time
from collections import deque


class FakeGrblSerial:
    def __init__(self, *, responses: list[str] | None = None, error_at_line: int | None = None, alarm_at_line: int | None = None, timeout: bool = False, disconnect: bool = False, rx_buffer_size: int = 128):
        self.port = "COM_FAKE"
        self.baudrate = 115200
        self.timeout = 0.1
        self.is_open = False
        self.written: list[bytes] = []
        self.closed = False
        self.timeout_mode = timeout
        self.disconnect = disconnect
        self.rx_buffer_size = rx_buffer_size
        self._line_no = 0
        self._error_at_line = error_at_line
        self._alarm_at_line = alarm_at_line
        self._responses = deque(["Grbl 1.1h ['$' for help]", "<Idle|MPos:0.000,0.000,0.000|FS:0,0>"] if responses is None else responses)

    def open(self):
        if self.disconnect:
            raise OSError("fake disconnect")
        self.is_open = True

    def close(self):
        self.closed = True
        self.is_open = False

    def flush(self):
        return None

    def reset_input_buffer(self):
        return None

    def reset_output_buffer(self):
        return None

    def write(self, data: bytes):
        if self.disconnect:
            raise OSError("fake disconnect")
        self.written.append(data)
        text = data.decode("ascii", errors="replace").strip()
        if text == "?":
            self._responses.append("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")
        elif text and not text.startswith("\x18"):
            self._line_no += 1
            if len(data) > self.rx_buffer_size:
                self._responses.append("error:33")
            elif self._alarm_at_line == self._line_no:
                self._responses.append("ALARM:1")
            elif self._error_at_line == self._line_no:
                self._responses.append("error:33")
            else:
                self._responses.append("ok")
        return len(data)

    def read(self, _size: int = 1) -> bytes:
        if self.timeout_mode:
            time.sleep(float(self.timeout or 0.01))
            return b""
        lines = []
        while self._responses:
            lines.append(self._responses.popleft())
        return ("\n".join(lines) + ("\n" if lines else "")).encode("ascii")

    def readline(self) -> bytes:
        if self.timeout_mode:
            time.sleep(float(self.timeout or 0.01))
            return b""
        if not self._responses:
            return b""
        return (self._responses.popleft() + "\n").encode("ascii")


def make_fake_serial_factory(**kwargs):
    created: list[FakeGrblSerial] = []

    def factory():
        ser = FakeGrblSerial(**kwargs)
        created.append(ser)
        return ser

    factory.created = created  # type: ignore[attr-defined]
    return factory
