import sys
import time
from pathlib import Path
import argparse
from collections import deque


def _force_utf8_stdio() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


try:
    import serial  # pyserial
except Exception as e:
    print('Missing dependency: pyserial')
    raise
try:
    from serial.serialutil import SerialException
except Exception:
    SerialException = Exception


_PRINT_ENABLED = True


def _safe_print(*args, **kwargs) -> None:
    global _PRINT_ENABLED
    if not _PRINT_ENABLED:
        return
    try:
        print(*args, **kwargs)
    except (BrokenPipeError, OSError):
        # If stdout is closed (e.g., caller timed out / pipe closed), continue streaming silently.
        _PRINT_ENABLED = False


def usage():
    _safe_print('Usage: python send_grbl_file.py COMx 115200 path\\to\\file.nc [--sleep]')


def _format_duration_hms(seconds: float) -> str:
    s = max(0.0, float(seconds))
    total = int(round(s))
    h = total // 3600
    m = (total % 3600) // 60
    sec = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def open_grbl(port: str, baud: int):
    try:
        # Some boards reset on DTR when opening the serial port.
        # Create the object first, force DTR/RTS low, then open.
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.timeout = 1
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        ser.open()
    except SerialException as exc:
        raise RuntimeError(f"Cannot open {port} @ {baud}: {exc}") from exc
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    def _query_status() -> str:
        try:
            ser.write(b"?")
            ser.flush()
        except Exception:
            return ""
        time.sleep(0.2)
        try:
            data = ser.read(4096)
        except Exception:
            data = b""
        return data.decode("ascii", errors="replace").strip()

    # Wake up / flush any banner.
    ser.write(b"\r\n")
    ser.flush()
    time.sleep(0.2)

    banner = ser.read(4096).decode("ascii", errors="replace").strip()
    status = _query_status()
    combined = (banner + "\n" + status).strip()

    if "<Sleep" in combined or combined.startswith("<Sleep"):
        # Controller is sleeping: wake requires soft reset, then job's leading $X will unlock.
        try:
            ser.write(b"\x18")  # Ctrl-X soft reset
            ser.flush()
            time.sleep(1.0)
        except Exception:
            pass
        banner2 = ser.read(4096).decode("ascii", errors="replace").strip()
        status2 = _query_status()
        combined = (combined + "\n" + banner2 + "\n" + status2).strip()

    if combined:
        _safe_print("--- startup ---")
        _safe_print(combined)
        _safe_print("--------------")
    return ser


def _clean_gcode_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if not line:
            continue
        if line.startswith(";") or line.startswith("("):
            continue
        out.append(line)
    return out


def release_axes(ser, *, sleep: bool = False, wait: bool = True):
    def _send_no_throw(cmd: str):
        try:
            ser.write((cmd + '\n').encode('ascii'))
            ser.flush()
        except Exception:
            # Ignore cleanup errors; we are in teardown path.
            pass
        # Optional ack wait: best effort, never fail teardown.
        t0 = time.time()
        while time.time() - t0 < 0.35:
            try:
                raw = ser.readline()
            except Exception:
                break
            if not raw:
                continue
            try:
                reply = raw.decode('ascii', errors='replace').strip()
            except Exception:
                continue
            if reply == "ok" or reply.startswith("error:") or reply.startswith("ALARM:"):
                break
        try:
            ser.flush()
        except Exception:
            pass

    # Lift pen (best-effort), stop any spindle/servo.
    _send_no_throw("G90")
    _send_no_throw("G1 Z0 F800")
    _send_no_throw("G4 P0.05")
    _send_no_throw("M5")
    # Best-effort motor release commands for broader firmware compatibility.
    _send_no_throw("M18")
    _send_no_throw("M84")
    _send_no_throw("$1=0")
    if sleep:
        _send_no_throw("$SLP")

    # Give controller one small cycle to apply settings.
    if wait:
        time.sleep(0.1)
    if sleep:
        _safe_print("Motors released ($1=0, $SLP).")
    else:
        _safe_print("Motors released ($1=0).")


def _parse_status_state(line: str) -> str:
    # Example: <Idle|MPos:0.000,0.000,0.000|FS:0,0>
    if not line.startswith("<") or "|" not in line:
        return ""
    try:
        return line[1 : line.index("|")]
    except Exception:
        return ""


def _query_status(ser) -> str:
    try:
        ser.write(b"?")
        ser.flush()
    except Exception:
        return ""

    # Read a few lines; status is usually one line like "<Idle|...>"
    t0 = time.time()
    while time.time() - t0 < 0.6:
        try:
            raw = ser.readline()
        except Exception:
            break
        if not raw:
            continue
        line = raw.decode("ascii", errors="replace").strip()
        if line.startswith("<") and line.endswith(">"):
            return line
    return ""


def wait_for_idle(ser, *, timeout_s: float = 3600.0) -> None:
    t0 = time.time()
    last_print = 0.0
    while True:
        if time.time() - t0 > timeout_s:
            raise RuntimeError("Timeout waiting for machine to become Idle.")
        st = _query_status(ser)
        state = _parse_status_state(st) if st else ""
        if state == "Idle":
            return
        # Keep the console alive for long jobs.
        if time.time() - last_print > 5.0:
            if st:
                _safe_print(st)
            last_print = time.time()
        time.sleep(0.25)


def stream_lines_to_grbl(
    ser,
    lines: list[str],
    *,
    rx_buffer_size: int = 128,
    verbose: bool = False,
) -> None:
    # Classic GRBL character-count streaming.
    # NOTE: GRBL replies "ok" when a line is parsed and queued, not when executed.
    if rx_buffer_size < 32:
        rx_buffer_size = 32

    # Use a small timeout for responsive streaming.
    try:
        ser.timeout = 0.1
    except Exception:
        pass

    pending: deque[tuple[int, int, str]] = deque()  # (len_bytes, line_no_1based, line_text)
    buf_used = 0
    i = 0
    n = len(lines)
    last_progress = 0.0
    progress_interval_s = 5.0

    def _progress():
        nonlocal last_progress
        now = time.time()
        if now - last_progress < progress_interval_s:
            return
        pct = (i / n * 100.0) if n else 100.0
        _safe_print(f"progress: {i}/{n} lines ({pct:.1f}%), pending={len(pending)}, buf={buf_used}/{rx_buffer_size}")
        last_progress = now

    while i < n or pending:
        # Fill RX buffer with as many lines as possible.
        while i < n:
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            data = (line + "\n").encode("ascii", errors="replace")
            l = len(data)
            if l >= rx_buffer_size:
                raise RuntimeError(f"Line too long for GRBL RX buffer ({rx_buffer_size}): {line[:120]!r}")
            if buf_used + l > rx_buffer_size:
                break
            try:
                ser.write(data)
            except Exception as exc:
                raise RuntimeError(f"Serial write failed: {exc}") from exc
            pending.append((l, i + 1, line))
            buf_used += l
            i += 1

        try:
            ser.flush()
        except Exception:
            pass

        # Drain responses to free buffer space.
        raw = b""
        try:
            raw = ser.readline()
        except Exception:
            raw = b""
        if not raw:
            _progress()
            continue

        resp = raw.decode("ascii", errors="replace").strip()
        if not resp:
            continue
        if resp == "ok" or resp.startswith("error:") or resp.startswith("ALARM:"):
            acked = pending.popleft() if pending else None
            if acked is not None:
                buf_used -= acked[0]
                if buf_used < 0:
                    buf_used = 0
            if resp.startswith("error:") or resp.startswith("ALARM:"):
                if acked is not None:
                    _l, line_no, line_text = acked
                    _safe_print(f"Offending line #{line_no}: {line_text}")
                _safe_print(resp)
                raise RuntimeError(f"Controller reported: {resp}")
            if verbose:
                _safe_print(resp)
        else:
            # Status reports (<Idle|...>), startup banners, etc.
            if verbose:
                _safe_print(resp)

        _progress()


def main(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("port", nargs="?")
    parser.add_argument("baud", nargs="?")
    parser.add_argument("file", nargs="?")
    parser.add_argument("--sleep", action="store_true", help="Send $SLP at end (fully disable steppers; requires reset to wake).")
    parser.add_argument("--rx-buffer", type=int, default=128, help="GRBL RX buffer size in bytes (default 128)")
    parser.add_argument("--verbose", action="store_true", help="Print non-ok chatter (status, banners) while streaming")
    parser.add_argument("-h", "--help", action="store_true")
    ns, _ = parser.parse_known_args(argv[1:])

    if ns.help or not ns.port or not ns.baud or not ns.file:
        usage()
        _safe_print("  --sleep   Optional: put GRBL into Sleep at end to guarantee motors are off/cool.")
        return 2

    port = ns.port
    baud = int(ns.baud)
    file_path = Path(ns.file)
    if not file_path.exists():
        _safe_print(f'File not found: {file_path}')
        return 2

    ser = None
    try:
        ser = open_grbl(port, baud)
    except RuntimeError as exc:
        _safe_print(exc)
        _safe_print("Make sure the machine is on COM port and no other program is using it.")
        return 1

    return_code = 0
    try:
        # Stream the file fast enough to keep GRBL's planner full (reduces stutter on dense curves).
        lines = _clean_gcode_lines(file_path.read_text(encoding="utf-8", errors="ignore"))
        if not lines:
            raise RuntimeError("No G-code lines found in file.")
        _safe_print(f"Streaming {len(lines)} lines ...")
        t_plot_start = time.perf_counter()
        stream_lines_to_grbl(
            ser,
            lines,
            rx_buffer_size=int(ns.rx_buffer),
            verbose=bool(ns.verbose),
        )
        # Wait until the machine is actually done (GRBL 'ok' is only "accepted", not "executed").
        wait_for_idle(ser, timeout_s=6 * 60 * 60)
        plot_time_s = max(0.0, time.perf_counter() - t_plot_start)
        _safe_print(f"PLOT_TIME_SECONDS={plot_time_s:.3f}")
        _safe_print(f"PLOT_TIME_HMS={_format_duration_hms(plot_time_s)}")
        _safe_print("Done.")
    except RuntimeError as exc:
        _safe_print('Execution interrupted.')
        _safe_print(exc)
        return_code = 1
    except Exception as exc:
        _safe_print('Execution interrupted.')
        _safe_print(exc)
        return_code = 1
    except KeyboardInterrupt:
        _safe_print('Execution interrupted by user.')
        return_code = 1
    finally:
        # Ensure motors are not held when job ends or fails.
        if ser is not None:
            release_axes(ser, sleep=bool(ns.sleep))
            ser.close()
    return return_code


if __name__ == '__main__':
    _force_utf8_stdio()
    raise SystemExit(main(sys.argv))
