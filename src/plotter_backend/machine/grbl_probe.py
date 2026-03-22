from __future__ import annotations

import re
import time
from typing import Any, Optional, Tuple


def open_serial_no_reset(port: str, baud: int, *, timeout_s: float = 1.0):
    # IMPORTANT: Many GRBL boards reset on DTR when opening the port.
    # Open serial the same way as src/send_grbl_file.py to avoid losing coordinates mid-job.
    import serial  # pyserial

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = int(baud)
    ser.timeout = float(timeout_s)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    ser.open()
    time.sleep(0.2)
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
    except Exception:
        pass
    return ser


def grbl_readline_ascii(ser) -> str:
    try:
        raw = ser.readline()
    except Exception:
        return ""
    if not raw:
        return ""
    return raw.decode("ascii", errors="replace").strip()


def grbl_status_line(backend: Any, ser, *, timeout_s: float = 0.8) -> str:
    try:
        ser.write(b"?")
        ser.flush()
    except Exception:
        return ""
    started = time.time()
    while time.time() - started < timeout_s:
        status = backend._grbl_readline_ascii(ser)
        if status.startswith("<") and status.endswith(">"):
            return status
    return ""


def parse_grbl_triplet(tag: str, text: str) -> Optional[Tuple[float, float, float]]:
    match = re.search(rf"{re.escape(tag)}:([^|>]+)", text)
    if not match:
        return None
    parts = match.group(1).split(",")
    if len(parts) < 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except Exception:
        return None


def grbl_query_offsets(backend: Any, ser) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    # Returns (G54, G92)
    try:
        ser.write(b"$#\n")
        ser.flush()
    except Exception:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    started = time.time()
    buf: list[str] = []
    while time.time() - started < 1.5:
        status = backend._grbl_readline_ascii(ser)
        if not status:
            continue
        buf.append(status)
        if status == "ok" or status.startswith("error:") or status.startswith("ALARM:"):
            break
    joined = "\n".join(buf)

    def _parse_bracket(tag: str) -> Tuple[float, float, float]:
        match = re.search(rf"\\[{re.escape(tag)}:([^\\]]+)\\]", joined)
        if not match:
            return (0.0, 0.0, 0.0)
        parts = match.group(1).split(",")
        try:
            vals = [float(p) for p in parts[:3]]
        except Exception:
            return (0.0, 0.0, 0.0)
        while len(vals) < 3:
            vals.append(0.0)
        return (vals[0], vals[1], vals[2])

    return _parse_bracket("G54"), _parse_bracket("G92")


def grbl_wait_for_idle(backend: Any, port: str, baud: str, logger, *, timeout_s: float = 600.0) -> None:
    try:
        ser = backend._open_serial_no_reset(port, int(baud), timeout_s=0.5)
    except Exception as exc:
        raise backend.SerialTransportError(f"Cannot open GRBL serial ({type(exc).__name__}: {exc})") from exc
    try:
        started = time.time()
        last_log = 0.0
        while True:
            if time.time() - started > timeout_s:
                raise backend.SerialTransportError("Timeout waiting for GRBL to become Idle.")
            status = backend._grbl_status_line(ser, timeout_s=0.8)
            if status.startswith("<Idle|"):
                return
            if time.time() - last_log > 2.0 and status:
                logger(status)
                last_log = time.time()
            time.sleep(0.25)
    finally:
        try:
            ser.close()
        except Exception:
            pass


def grbl_get_wpos_xyz(backend: Any, port: str, baud: str) -> Tuple[float, float, float]:
    # Prefer WPos if present; else compute from MPos and WCO/($#).
    try:
        ser = backend._open_serial_no_reset(port, int(baud), timeout_s=0.8)
    except Exception as exc:
        raise backend.SerialTransportError(f"Cannot open GRBL serial ({type(exc).__name__}: {exc})") from exc
    try:
        status = backend._grbl_status_line(ser, timeout_s=0.8)
        wpos = backend._parse_grbl_triplet("WPos", status) if status else None
        if wpos is not None:
            return wpos
        mpos = backend._parse_grbl_triplet("MPos", status) if status else None
        if mpos is None:
            raise backend.SerialTransportError(f"Cannot read GRBL position (status='{status}').")
        wco = backend._parse_grbl_triplet("WCO", status) if status else None
        if wco is None:
            g54, g92 = backend._grbl_query_offsets(ser)
            wco = (g54[0] + g92[0], g54[1] + g92[1], g54[2] + g92[2])
        return (mpos[0] - wco[0], mpos[1] - wco[1], mpos[2] - wco[2])
    finally:
        try:
            ser.close()
        except Exception:
            pass
