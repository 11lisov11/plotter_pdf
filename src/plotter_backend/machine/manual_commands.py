from __future__ import annotations

import time
from typing import Callable, List, Tuple

from ..errors import SerialTransportError, ToolDependencyError


def grbl_send_manual_commands(
    com: str,
    baud: str,
    commands: List[str],
    *,
    default_baud: str,
    soft_reset_first: bool = False,
    read_tail: bool = True,
    serial_timeout_s: float = 1.0,
    wake_delay_s: float = 0.20,
    reset_delay_s: float = 1.0,
    command_delay_s: float = 0.16,
    tail_delay_s: float = 0.35,
    wake_read_bytes: int = 4096,
    tail_read_bytes: int = 8192,
    serial_factory: Callable[[], object] | None = None,
) -> Tuple[bool, str]:
    serial_module = None
    if serial_factory is None:
        try:
            import serial as _serial  # type: ignore

            serial_module = _serial
        except Exception as exc:
            return False, (
                f"{ToolDependencyError.__name__}: pyserial not available "
                f"({type(exc).__name__}: {exc})"
            )

    port = (com or "").strip()
    if not port:
        return False, "COM port is empty."
    try:
        baud_i = int(str(baud).strip() or default_baud)
    except Exception:
        baud_i = int(default_baud)

    ser = None
    timeout_s = max(0.05, float(serial_timeout_s))
    wake_delay = max(0.0, float(wake_delay_s))
    reset_delay = max(0.0, float(reset_delay_s))
    command_delay = max(0.0, float(command_delay_s))
    tail_delay = max(0.0, float(tail_delay_s))
    wake_read = max(0, int(wake_read_bytes))
    tail_read = max(0, int(tail_read_bytes))
    try:
        if serial_factory is not None:
            ser = serial_factory()
        else:
            ser = serial_module.Serial()
        ser.port = port
        ser.baudrate = baud_i
        ser.timeout = timeout_s
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        ser.open()

        # Wake channel.
        ser.write(b"\r\n")
        ser.flush()
        time.sleep(wake_delay)
        if wake_read > 0:
            ser.read(wake_read)

        if soft_reset_first:
            ser.write(b"\x18")
            ser.flush()
            time.sleep(reset_delay)
            if wake_read > 0:
                ser.read(wake_read)

        for cmd in commands:
            line = (cmd or "").strip()
            if not line:
                continue
            ser.write((line + "\n").encode("ascii", errors="replace"))
            ser.flush()
            time.sleep(command_delay)

        if not read_tail:
            return True, "ok"

        time.sleep(tail_delay)
        tail = ser.read(tail_read).decode("ascii", errors="replace").strip() if tail_read > 0 else ""
        return True, tail or "ok"
    except Exception as exc:
        return False, f"{SerialTransportError.__name__}: {type(exc).__name__}: {exc}"
    finally:
        try:
            if ser is not None:
                ser.close()
        except Exception:
            pass
