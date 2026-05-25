import sys
import time
import argparse

try:
    from src.plotter_backend.machine.windows_bt_spp import build_serial_open_hint
except Exception:
    try:
        from plotter_backend.machine.windows_bt_spp import build_serial_open_hint  # type: ignore
    except Exception:
        def build_serial_open_hint(_port: str, diagnostics=None) -> str:
            return ""


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
except Exception:
    print("Missing dependency: pyserial")
    raise


def usage() -> None:
    print("Usage: python release_motors.py COMx [115200] [--sleep]")


def _safe_pen_up_commands() -> tuple[str, ...]:
    # G-code jobs use Z_UP=0 and Z_DOWN>0. After abort/reset GRBL can have a
    # stale work Z coordinate, so a plain "G1 Z0" may not physically lift.
    # Force the current physical position to Z4, then move to Z0 before release.
    return (
        "$X",
        "G21",
        "G90",
        "G92 Z4.0000",
        "G0 Z0.0000 F800.0",
        "G4 P0.10",
        "G92 Z0.0000",
        "G0 Z0.0000 F800.0",
        "G4 P0.05",
        "M5",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("port", nargs="?")
    parser.add_argument("baud", nargs="?", default="115200")
    parser.add_argument("--sleep", action="store_true", help="Send $SLP (guaranteed stepper off; requires reset to wake).")
    parser.add_argument("-h", "--help", action="store_true")
    ns, _ = parser.parse_known_args(argv[1:])

    if ns.help or not ns.port:
        usage()
        return 2

    port = ns.port
    baud = int(ns.baud)

    try:
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
    except Exception as exc:
        print(f"Cannot open {port} @ {baud}: {exc}")
        try:
            hint = str(build_serial_open_hint(port) or "").strip()
        except Exception:
            hint = ""
        if hint:
            print(hint)
        print("Close UGS/any sender that is connected to the same COM port and retry.")
        return 1

    try:
        time.sleep(0.2)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # If controller is sleeping ($SLP), it won't answer. Wake via reset.
        try:
            ser.write(b"?")
            ser.flush()
            time.sleep(0.2)
            if not ser.in_waiting:
                ser.write(b"\x18")  # Ctrl-X soft reset
                ser.flush()
                time.sleep(0.35)
        except Exception:
            pass

        # Best-effort safe teardown: force pen up, return home, release steppers.
        for cmd in (*_safe_pen_up_commands(), "G0 X0.0000 Y0.0000 F900.0", "$1=0"):
            try:
                ser.write((cmd + "\n").encode("ascii"))
                ser.flush()
                time.sleep(0.12)
            except Exception:
                pass

        if ns.sleep:
            try:
                ser.write(b"$SLP\n")
                ser.flush()
                time.sleep(0.12)
            except Exception:
                pass

        if ns.sleep:
            print("Motors released ($1=0, $SLP).")
        else:
            print("Motors released ($1=0).")
        return 0
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    _force_utf8_stdio()
    raise SystemExit(main(sys.argv))
