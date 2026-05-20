from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class TcpEndpoint:
    host: str
    port: int


_TCP_SCHEME_RE = re.compile(r"^(?:tcp|wifi|socket|telnet)://", re.I)


def parse_tcp_endpoint(value: str, *, default_port: int = 23) -> Optional[TcpEndpoint]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if _TCP_SCHEME_RE.match(raw):
        parsed = urlparse(raw)
        if not parsed.hostname:
            return None
        return TcpEndpoint(parsed.hostname, int(parsed.port or default_port))
    if raw.lower().startswith("COM".lower()):
        return None
    if ":" in raw and "\\" not in raw and "/" not in raw:
        host, port_text = raw.rsplit(":", 1)
        try:
            return TcpEndpoint(host.strip(), int(port_text.strip()))
        except Exception:
            return None
    return None


def is_tcp_endpoint(value: str) -> bool:
    return parse_tcp_endpoint(value) is not None


class TcpGrblConnection:
    def __init__(self, host: str, port: int, *, timeout: float = 1.0) -> None:
        self.host = str(host)
        self.port = int(port)
        self._timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._rx = bytearray()
        self.dtr = False
        self.rts = False

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = float(value)
        if self._sock is not None:
            self._sock.settimeout(max(0.01, self._timeout))

    def open(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=max(0.05, self._timeout))
        sock.settimeout(max(0.01, self._timeout))
        self._sock = sock

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def flush(self) -> None:
        return

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    def reset_output_buffer(self) -> None:
        return

    def write(self, data: bytes) -> int:
        if self._sock is None:
            raise OSError("TCP GRBL connection is not open")
        payload = bytes(data)
        self._sock.sendall(payload)
        return len(payload)

    def read(self, size: int = 1) -> bytes:
        if self._sock is None:
            return b""
        deadline = time.time() + max(0.01, self._timeout)
        while len(self._rx) < max(1, int(size)) and time.time() < deadline:
            try:
                chunk = self._sock.recv(max(1, int(size) - len(self._rx)))
            except socket.timeout:
                break
            if not chunk:
                break
            self._rx.extend(chunk)
        if size <= 0:
            return b""
        out = bytes(self._rx[:size])
        del self._rx[:size]
        return out

    def readline(self) -> bytes:
        if self._sock is None:
            return b""
        deadline = time.time() + max(0.01, self._timeout)
        while b"\n" not in self._rx and time.time() < deadline:
            try:
                chunk = self._sock.recv(256)
            except socket.timeout:
                break
            if not chunk:
                break
            self._rx.extend(chunk)
        if b"\n" in self._rx:
            idx = self._rx.index(10) + 1
            out = bytes(self._rx[:idx])
            del self._rx[:idx]
            return out
        out = bytes(self._rx)
        self._rx.clear()
        return out


def open_grbl_transport(port_or_endpoint: str, baud: int, *, timeout_s: float = 1.0):
    endpoint = parse_tcp_endpoint(port_or_endpoint)
    if endpoint is not None:
        conn = TcpGrblConnection(endpoint.host, endpoint.port, timeout=timeout_s)
        conn.open()
        return conn

    import serial  # pyserial

    ser = serial.Serial()
    ser.port = port_or_endpoint
    ser.baudrate = int(baud)
    ser.timeout = float(timeout_s)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    ser.open()
    return ser
