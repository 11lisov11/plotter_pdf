"""Manually confirmed registered job runner. NEVER called by the preparer.

Keeps one connection and XY reference throughout the job. Does not home,
auto-unlock, flash firmware, or use the ordinary sender's release trailer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.plotter_backend.geometry.small_sheet_tiling import PAPER_REGISTRATION, SCHEMA

EXPECTED_BOARD = "BtWriter(A4:F0:0F:75:C5:0E)"


def checked_file(root: Path, record: dict) -> Path:
    path = (root / record["file"]).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Job file is missing or escapes its job directory")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"NC changed after preparation: {path.name}; prepare the job again")
    return path


class Session:
    def __init__(self, port: str, baud: int):
        import serial
        self.serial = serial.Serial()
        self.serial.port = port
        self.serial.baudrate = baud
        self.serial.timeout = 0.2
        self.serial.write_timeout = 3
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.open()
        self.wco = None
        time.sleep(2)

    def line(self) -> str:
        line = self.serial.readline().decode("ascii", errors="replace").strip()
        if line.startswith(("ALARM", "error:")):
            raise RuntimeError(line)
        return line

    def command(self, command: str) -> list[str]:
        self.serial.write((command + "\n").encode("ascii"))
        response = []
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            line = self.line()
            if line == "ok":
                return response
            if line:
                response.append(line)
        raise TimeoutError(f"No acknowledgement for {command!r}")

    def idle(self, *, target=None, xy_offset=None, timeout=3600, require_idle=False) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.serial.write(b"?")
            end = time.monotonic() + 0.8
            while time.monotonic() < end:
                line = self.line()
                if not line.startswith("<"):
                    continue
                fields = line.strip("<>").split("|")
                values = dict(field.split(":", 1) for field in fields[1:] if ":" in field)
                if "WCO" in values:
                    self.wco = tuple(map(float, values["WCO"].split(",")))
                if fields[0] != "Idle":
                    if require_idle:
                        raise RuntimeError(f"Controller is busy: {fields[0]}; existing motion was not interrupted")
                    if not fields[0].startswith(("Run", "Jog")):
                        raise RuntimeError(f"Controller is not ready: {fields[0]}")
                    break
                if self.wco is None:
                    break
                if xy_offset is not None and any(abs(a - b) > 0.01 for a, b in zip(self.wco[:2], xy_offset)):
                    raise RuntimeError("XY coordinate offset changed; alignment reference has been lost")
                position = tuple(map(float, values["WPos"].split(","))) if "WPos" in values else tuple(
                    a - b for a, b in zip(map(float, values["MPos"].split(",")), self.wco))
                if target is not None and any(abs(a - b) > 0.05 for a, b in zip(position[:2], target)):
                    raise RuntimeError(f"Controller did not reach the alignment point: {position[:2]} vs {target}")
                return {"position": position, "wco": self.wco}
            time.sleep(0.15)
        raise TimeoutError("No confirmed Idle position; do not move the paper")

    def send_file(self, path: Path) -> None:
        for raw in path.read_text(encoding="ascii").splitlines():
            line = raw.split(";", 1)[0].strip()
            if line:
                self.command(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--port", required=True, help="Explicit SMALL plotter port; never auto-detect another machine")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    job_path = args.job.resolve()
    root = job_path.parent
    job = json.loads(job_path.read_text(encoding="ascii"))
    if (job.get("schema") != SCHEMA or job.get("machine_profile") != "a4_desktop"
            or job.get("paper_registration") != PAPER_REGISTRATION or job.get("sheet_format") not in ("A2", "A1")):
        raise ValueError("Not a registered small-plotter A2/A1 job")
    tiles, transitions = job["tiles"], job["transitions"]
    if not tiles or len(transitions) != len(tiles) - 1:
        raise ValueError("Incomplete job queue")
    files = [job["initialize"], *tiles]
    for transition in transitions:
        files += [transition["check_secondary"], transition["return_primary"]]
    for record in files:
        checked_file(root, record)
    print("One continuous session. Do NOT reset coordinates, rotate the sheet, release motors or move the carriage by hand.")
    first_window = tiles[0]["window_mm"]
    print(f"PASS 01 covers source-sheet window {first_window} mm (origin at the source top-left).")
    print("Position THAT window in the plotter field, with the normal paper orientation; it need not be the sheet corner.")
    print("Use the placement overview before starting. Pen needs clearance for the usual 4 mm initial lift.")
    if input("Type START to connect and prepare the pen, or anything else to cancel: ").strip() != "START":
        return 0
    session = Session(args.port, args.baud)
    succeeded = False
    motion_owned = False
    try:
        identity = "\n".join(session.command("$I"))
        if EXPECTED_BOARD not in identity:
            raise RuntimeError("Not the known SMALL plotter; no motion commands sent")
        initial = session.idle(timeout=8, require_idle=True)
        offset = initial["wco"][:2]
        settings = session.command("$$")
        hold = next((re.fullmatch(r"\$1=(\d+)", line) for line in settings if line.startswith("$1=")), None)
        if hold is None:
            raise RuntimeError("Could not read the original motor-hold setting")
        original_hold = int(hold.group(1))
        initialize = checked_file(root, job["initialize"])
        motion_owned = True
        session.send_file(initialize)
        session.idle(xy_offset=offset)
        for index, tile in enumerate(tiles):
            if index:
                transition = transitions[index - 1]
                primary, secondary = transition["next_machine_mm"]
                while True:
                    print(f"PASS {tile['number']:02d}: move PAPER ONLY until its existing cross A is precisely under the raised pen.")
                    input("Secure the sheet without rotating it. Press Enter to check cross B: ")
                    session.send_file(checked_file(root, transition["check_secondary"]))
                    session.idle(target=secondary, xy_offset=offset)
                    answer = input("Is the raised pen exactly over cross B? Type YES, or Enter to return to A and realign: ").strip()
                    session.send_file(checked_file(root, transition["return_primary"]))
                    session.idle(target=primary, xy_offset=offset)
                    if answer == "YES":
                        break
            if input(f"Type DRAW {tile['number']} to draw this pass, or anything else to abort: ").strip() != f"DRAW {tile['number']}":
                raise KeyboardInterrupt
            session.send_file(checked_file(root, tile))
            session.idle(target=tile["end_park_mm"], xy_offset=offset)
            print(f"PASS {tile['number']:02d} completed. Pen up; motors held.")
        session.command(f"$1={original_hold}")
        succeeded = True
        print("Job completed; original motor-hold setting restored. Registration marks can now be removed.")
    finally:
        try:
            if not succeeded and motion_owned:
                # Only stop motion started by THIS verified session. Identity
                # rejection or an initially busy controller must never reset
                # another machine/job. Do not queue a lift behind unknown motion.
                try:
                    session.serial.write(b"!")
                    time.sleep(0.2)
                    session.serial.write(b"\x18")
                    print("ABORTED. Queue cleared; registration must be restarted. Check/lift the pen before touching paper.")
                except OSError as error:
                    print(f"ABORT connection failed: {error}. Stop the machine manually; do not move the paper.")
            elif not succeeded:
                print("Drawing was not started. No hold/reset commands were sent.")
        finally:
            session.serial.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
