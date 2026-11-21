"""Manually confirmed registered job runner. NEVER called by the preparer.

Establishes XY zero ONCE at an explicitly confirmed physical home, then keeps
one connection/reference throughout the job. Never homes automatically,
auto-unlocks, flashes firmware, or uses the ordinary release trailer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.plotter_backend.geometry.small_sheet_tiling import PAPER_REGISTRATION, SCHEMA

EXPECTED_BOARD = "BtWriter(A4:F0:0F:75:C5:0E)"
HOME_CONFIRMATION = "HOME 0 0"


def establish_xy_reference(session) -> tuple[float, float]:
    """Call ONLY after physical-home confirmation; no XY movement is issued.

    Idle/WPos=0 cannot establish a physical reference: a USB/controller reset
    can report zero with the carriage still at the previous pass's top park.
    G92 here binds the user's verified bottom-left home, not the current paper
    corner or an arbitrary reported position. Never call between passes.
    """
    session.command("G21")
    session.command("G90")
    session.command("G92 X0.0000 Y0.0000")
    reference = session.idle(target=(0.0, 0.0), timeout=8, require_idle=True)
    session.record("xy_reference", method="confirmed_physical_bottom_left_home",
                   position=reference["position"], wco=reference["wco"])
    return reference["wco"][:2]


def alignment_pen(session, job: dict, offset, point, *, down: bool) -> None:
    """Touch a stationary registration mark; never travel with the pen down."""
    session.idle(target=point, xy_offset=offset, timeout=20)
    config = job["config"]
    z = config["z_down"] if down else config["z_up"]
    session.command(f"G1 Z{z:.4f} F{config['z_feed']:.1f}")
    session.command("G4 P0.06")
    session.idle(target=point, xy_offset=offset, timeout=20)
    session.record("alignment_pen", point=point, down=down, z=z)


def checked_file(root: Path, record: dict) -> Path:
    path = (root / record["file"]).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("Job file is missing or escapes its job directory")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"NC changed after preparation: {path.name}; prepare the job again")
    return path


class Session:
    def __init__(self, port: str, baud: int, log_path: Path | None = None):
        import serial
        self.log_path = log_path
        self.sequence = 0
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

    def record(self, event: str, **fields) -> None:
        path = getattr(self, "log_path", None)
        if path is not None:
            entry = {"event": event, "utc": datetime.now(timezone.utc).isoformat(), **fields}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def line(self) -> str:
        line = self.serial.readline().decode("ascii", errors="replace").strip()
        if line:
            self.record("rx", line=line)
        if line.startswith(("ALARM", "error:")):
            raise RuntimeError(line)
        return line

    def command(self, command: str) -> list[str]:
        # EEPROM/settings writes are rejected with error:8 while motion is
        # still running, even after all preceding moves were acknowledged.
        if re.fullmatch(r"\$\d+\s*=.*", command.strip()):
            self.idle(timeout=3600)
        self.sequence += 1
        sequence = self.sequence
        self.record("tx", seq=sequence, line=command)
        self.serial.write((command + "\n").encode("ascii"))
        response = []
        started = time.monotonic()
        acknowledgement_timeout = 15.0
        execution_deadline = started + 3600.0
        deadline = started + acknowledgement_timeout
        next_status_poll = started + 1.0
        last_state = None
        # An ACK confirms acceptance, not completion. A synchronizing command
        # (for example G4 after a long contour) can legitimately wait for the
        # planner for longer than 15 seconds. Real-time status remains usable
        # while the normal command parser is waiting for that motion.
        while time.monotonic() < min(deadline, execution_deadline):
            now = time.monotonic()
            if now >= next_status_poll:
                self.serial.write(b"?")
                next_status_poll = now + 1.0
            line = self.line()
            if line == "ok":
                self.record("ack", seq=sequence, response=response)
                return response
            if line.startswith("<") and line.endswith(">"):
                last_state = line[1:-1].split("|", 1)[0]
                if last_state in ("Run", "Jog"):
                    # Renew only on an actual busy response, never merely
                    # because a query was sent. Lost communication, Idle
                    # without an ACK, and paused motion still time out.
                    deadline = min(
                        execution_deadline,
                        time.monotonic() + acknowledgement_timeout,
                    )
                continue
            if line:
                response.append(line)
        self.record(
            "timeout", seq=sequence, line=command,
            elapsed_seconds=time.monotonic() - started,
            last_controller_state=last_state,
            execution_limit_seconds=3600.0,
        )
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
                self.record("idle", position=position, wco=self.wco, target=target)
                return {"position": position, "wco": self.wco}
            time.sleep(0.15)
        raise TimeoutError("No confirmed Idle position; do not move the paper")

    def send_file(self, path: Path) -> None:
        self.record("file_begin", file=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for raw in path.read_text(encoding="ascii").splitlines():
            line = raw.split(";", 1)[0].strip()
            if line:
                self.command(line)
        self.record("file_acked", file=str(path), last_seq=self.sequence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--port", required=True, help="Explicit SMALL plotter port; never auto-detect another machine")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--log", type=Path, help="New JSONL audit file; defaults to tmp/small_sheet_runs")
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
    print("A NEW job requires the carriage at the verified physical bottom-left XY HOME, not the paper corner or a previous top park.")
    print("Prepare that physical reference before starting. This program never moves to home automatically.")
    print("After home confirmation: one continuous session; do NOT reset XY, rotate paper, release motors or move the carriage by hand.")
    first_window = tiles[0]["window_mm"]
    print(f"PASS 01 covers source-sheet window {first_window} mm (origin at the source top-left).")
    print("Position THAT window in the plotter field, with the normal paper orientation; it need not be the sheet corner.")
    print("Use the placement overview before starting. Pen needs clearance for the usual 4 mm initial lift.")
    if input("Type START to connect and prepare the pen, or anything else to cancel: ").strip() != "START":
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = (args.log or ROOT / "tmp" / "small_sheet_runs" / f"{stamp}_{uuid4().hex[:8]}.jsonl").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a previous physical-run record.
    with log_path.open("x", encoding="utf-8"):
        pass
    print(f"Audit log: {log_path}")
    session = Session(args.port, args.baud, log_path)
    succeeded = False
    motion_owned = False
    try:
        identity = "\n".join(session.command("$I"))
        if EXPECTED_BOARD not in identity:
            raise RuntimeError("Not the known SMALL plotter; no motion commands sent")
        initial = session.idle(timeout=8, require_idle=True)
        session.record("initial_reference_unverified", position=initial["position"], wco=initial["wco"])
        settings = session.command("$$")
        hold = next((re.fullmatch(r"\$1=(\d+)", line) for line in settings if line.startswith("$1=")), None)
        if hold is None:
            raise RuntimeError("Could not read the original motor-hold setting")
        original_hold = int(hold.group(1))
        initialize = checked_file(root, job["initialize"])
        print("Idle/reported zero does NOT prove physical home. Do not confirm a carriage left at the top after another pass.")
        answer = input(f"Type {HOME_CONFIRMATION} ONLY if the pen is physically at the calibrated bottom-left HOME, or anything else to cancel: ").strip()
        if answer != HOME_CONFIRMATION:
            session.record("reference_declined")
            return 0
        session.record("reference_confirmation", answer=answer)
        motion_owned = True
        offset = establish_xy_reference(session)
        session.send_file(initialize)
        session.idle(xy_offset=offset)
        for index, tile in enumerate(tiles):
            if index:
                transition = transitions[index - 1]
                primary, secondary = transition["next_machine_mm"]
                print(f"PASS {tile['number']:02d}: with the PEN UP, move PAPER ONLY approximately to cross A.")
                input("Finish the large paper shift first. Press Enter to lower the stationary pen onto A for fine alignment: ")
                alignment_pen(session, job, offset, primary, down=True)
                while True:
                    print("Pen is DOWN at A for fine alignment. Avoid dragging paper under the touching tip; never move the carriage by hand.")
                    input("Align the center of A with the tip and secure the sheet. Press Enter to lift, travel to B, and lower there: ")
                    alignment_pen(session, job, offset, primary, down=False)
                    session.send_file(checked_file(root, transition["check_secondary"]))
                    session.idle(target=secondary, xy_offset=offset)
                    alignment_pen(session, job, offset, secondary, down=True)
                    answer = input("The pen is DOWN at B. Is its tip exactly at the center? Type YES, or Enter to lift, return to A and realign: ").strip()
                    alignment_pen(session, job, offset, secondary, down=False)
                    session.send_file(checked_file(root, transition["return_primary"]))
                    session.idle(target=primary, xy_offset=offset)
                    if answer == "YES":
                        break
                    alignment_pen(session, job, offset, primary, down=True)
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
