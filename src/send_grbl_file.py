import sys
import time
from pathlib import Path

try:
    import serial  # pyserial
except Exception as e:
    print('Missing dependency: pyserial')
    raise
try:
    from serial.serialutil import SerialException
except Exception:
    SerialException = Exception


def usage():
    print('Usage: python send_grbl_file.py COMx 115200 path\\to\\file.nc')


def open_grbl(port: str, baud: int):
    try:
        ser = serial.Serial(port, baudrate=baud, timeout=1)
    except SerialException as exc:
        raise RuntimeError(f"Cannot open {port} @ {baud}: {exc}") from exc
    # Avoid toggling DTR here; some boards reset on DTR.
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # Wake up / flush any banner.
    ser.write(b'\r\n')
    ser.flush()
    time.sleep(0.2)
    banner = ser.read(4096).decode('ascii', errors='replace').strip()
    if banner:
        print('--- startup ---')
        print(banner)
        print('--------------')
    return ser


def release_axes(ser, *, wait: bool = True):
    def _send_no_throw(cmd: str):
        try:
            send_line(ser, cmd)
        except Exception:
            # Ignore cleanup errors; we are in teardown path.
            pass

    # Stop any spindle/servo and remove motor hold.
    _send_no_throw("M5")
    _send_no_throw("$1=0")

    # Give controller one small cycle to apply settings.
    if wait:
        time.sleep(0.1)


def read_response(ser, timeout_s=60.0):
    t0 = time.time()
    lines = []
    while time.time() - t0 < timeout_s:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode('ascii', errors='replace').strip()
        if not line:
            continue
        lines.append(line)
        if line == 'ok' or line.startswith('error:') or line.startswith('ALARM:'):
            break
    return lines


def send_line(ser, line):
    ser.write((line + '\n').encode('ascii'))
    ser.flush()
    # Some commands wait in GRBL planner during long travel.
    response = read_response(ser, timeout_s=300.0)
    if response:
        for r in response:
            print(r)
        last = response[-1]
        if last.startswith("error:") or last.startswith("ALARM:"):
            raise RuntimeError(f"Controller rejected '{line}': {last}")
    else:
        raise RuntimeError(f"No response for '{line}'")


def main(argv):
    if len(argv) != 4:
        usage()
        return 2

    port = argv[1]
    baud = int(argv[2])
    file_path = Path(argv[3])
    if not file_path.exists():
        print(f'File not found: {file_path}')
        return 2

    ser = None
    try:
        ser = open_grbl(port, baud)
    except RuntimeError as exc:
        print(exc)
        print("Make sure the machine is on COM port and no other program is using it.")
        return 1

    return_code = 0
    try:
        # Keep motors enabled while running the job for stable moves.
        for idx, raw_line in enumerate(file_path.read_text(encoding='ascii', errors='ignore').splitlines(), start=1):
            line = raw_line.lstrip("\ufeff").strip()
            if not line:
                continue
            if line.startswith(';') or line.startswith('('):
                continue

            try:
                send_line(ser, line)
            except RuntimeError as exc:
                print(f'Aborting at line {idx}: {line}')
                print(exc)
                return_code = 1
                break

        if return_code == 0:
            print('Done.')
    except RuntimeError:
        print('Execution interrupted.')
        return_code = 1
    except Exception as exc:
        print('Execution interrupted.')
        print(exc)
        return_code = 1
    except KeyboardInterrupt:
        print('Execution interrupted by user.')
        return_code = 1
    finally:
        # Ensure motors are not held when job ends or fails.
        if ser is not None:
            release_axes(ser)
            ser.close()
    return return_code


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
