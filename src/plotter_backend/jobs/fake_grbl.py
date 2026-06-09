from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(slots=True)
class FakeGrblController:
    alarm: bool = False
    error_code: int | None = None
    disconnected: bool = False
    timeout: bool = False
    rx_buffer_limit: int = 128
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    commands: list[str] = field(default_factory=list)

    def handle_command(self, raw: str) -> str:
        if self.disconnected:
            raise OSError("fake disconnect")
        if self.timeout:
            return ""
        line = raw.strip()
        if not line:
            return "ok"
        if len(line) > self.rx_buffer_limit:
            return "error:24"
        self.commands.append(line)
        if line == "?":
            state = "Alarm" if self.alarm else "Idle"
            x, y, z = self.position
            return f"<{state}|MPos:{x:.3f},{y:.3f},{z:.3f}|FS:0,0>"
        if self.alarm:
            return "ALARM:1"
        if self.error_code is not None:
            return f"error:{self.error_code}"
        return "ok"


class FakeSerial:
    def __init__(self, controller: FakeGrblController | None = None, scripted_reads: Iterable[bytes | str] = ()) -> None:
        self.controller = controller or FakeGrblController()
        self.port = "FAKE"
        self.baudrate = 115200
        self.timeout = 1.0
        self.is_open = False
        self.writes: list[bytes] = []
        self._reads: deque[bytes] = deque(
            item if isinstance(item, bytes) else item.encode("ascii", errors="replace") for item in scripted_reads
        )
        self._reads.append(b"Grbl 1.1h ['$' for help]\r\n")

    def open(self) -> None:
        if self.controller.disconnected:
            raise OSError("fake disconnect")
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def flush(self) -> None:
        return None

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise OSError("port is closed")
        self.writes.append(bytes(data))
        text = data.decode("ascii", errors="replace")
        for line in text.replace("\r", "\n").split("\n"):
            if not line.strip():
                continue
            response = self.controller.handle_command(line)
            if response:
                self._reads.append((response + "\r\n").encode("ascii", errors="replace"))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if not self._reads:
            return b""
        chunk = self._reads.popleft()
        if len(chunk) <= size:
            return chunk
        self._reads.appendleft(chunk[size:])
        return chunk[:size]

    def readline(self) -> bytes:
        return self.read(4096)
