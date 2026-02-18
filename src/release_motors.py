import sys
import time
import argparse


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

        # Best-effort safe teardown: pen up, stop spindle/servo, release steppers.
        for cmd in ("G90", "G1 Z0 F800", "G4 P0.05", "M5", "$1=0"):
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
