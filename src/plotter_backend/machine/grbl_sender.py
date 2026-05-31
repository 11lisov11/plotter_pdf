from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ..errors import SerialTransportError, ToolDependencyError
from . import manual_commands


def find_nearest_g0_xy_line(gcode_file: Path, *, x: float, y: float) -> int:
    # Find nearest G0 XY endpoint to current position. Resume at a travel move
    # to avoid dragging pen/pencil through already drawn geometry.
    x_re = re.compile(r"\bX(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
    y_re = re.compile(r"\bY(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")

    cur_x: Optional[float] = None
    cur_y: Optional[float] = None
    best_d = float("inf")
    best_line = 1

    with gcode_file.open("r", encoding="utf-8", errors="ignore") as fh:
        for ln, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("("):
                continue
            sx = x_re.search(line)
            sy = y_re.search(line)
            if sx:
                cur_x = float(sx.group(1))
            if sy:
                cur_y = float(sy.group(1))

            if not line.startswith("G0"):
                continue
            if ("X" not in line) and ("Y" not in line):
                continue
            if cur_x is None or cur_y is None:
                continue
            d = (cur_x - x) ** 2 + (cur_y - y) ** 2
            if d < best_d:
                best_d = d
                best_line = ln

    return best_line


def write_resume_file(
    src_gcode: Path,
    dst_gcode: Path,
    *,
    start_line: int,
    z_up: float,
    safe_lift_feed: float,
    z_delay_up: float,
) -> None:
    # Resume file must NOT include G92 (it would shift coordinates). We only
    # restore modal state and force pen up before continuing.
    src_lines = src_gcode.read_text(encoding="utf-8", errors="ignore").splitlines()
    payload = src_lines[max(0, int(start_line) - 1) :]
    pre = [
        "$X",
        "$1=255",
        "G21",
        "G90",
        "G17",
        "G91.1",
        f"G0 Z{float(z_up):.4f} F{float(safe_lift_feed):.1f}",
        f"G4 P{float(z_delay_up):.2f}",
        f"; AUTO-RESUME from line {int(start_line)} of {src_gcode.name}",
        "",
    ]
    dst_gcode.parent.mkdir(parents=True, exist_ok=True)
    dst_gcode.write_text("\n".join(pre + payload) + "\n", encoding="utf-8")


def send_to_grbl(
    gcode_file: Path,
    com: str,
    baud: str,
    logger,
    *,
    sleep_after: bool = False,
    auto_resume: bool = False,
    max_resume_attempts: int = 1,
    root_dir: Path,
    ensure_local_tmp_root: Callable[[], Path],
    grbl_wait_for_idle: Callable[[str, str, object], None],
    grbl_get_wpos_xyz: Callable[[str, str], Tuple[float, float, float]],
    z_up: float,
    safe_lift_feed: float,
    z_delay_up: float,
) -> float:
    sender = root_dir / "src" / "send_grbl_file.py"
    if not sender.exists():
        raise ToolDependencyError("send_grbl_file.py not found")

    def _load_sender_module():
        # In frozen/embedded runs, launching sys.executable may reopen the wrapper.
        # Run sender in-process to avoid recursive launcher spawn.
        module_name = "_plotter_sender_inline"
        existing = sys.modules.get(module_name)
        if existing is not None:
            return existing
        spec = importlib.util.spec_from_file_location(module_name, str(sender))
        if spec is None or spec.loader is None:
            raise ToolDependencyError("Cannot load send_grbl_file.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _run_sender_inline() -> Tuple[int, List[str], Optional[float], float]:
        sender_mod = _load_sender_module()
        out_lines: List[str] = []
        sender_plot_time_s: Optional[float] = None
        started_local = time.perf_counter()

        original_print = getattr(sender_mod, "_safe_print", None)
        original_enabled = getattr(sender_mod, "_PRINT_ENABLED", True)

        def _forward_print(*args, **kwargs):
            nonlocal sender_plot_time_s
            line = " ".join(str(a) for a in args).strip()
            if not line:
                return
            out_lines.append(line)
            logger(line)
            if line.startswith("PLOT_TIME_SECONDS="):
                try:
                    sender_plot_time_s = float(line.split("=", 1)[1].strip())
                except Exception:
                    pass

        try:
            sender_mod._PRINT_ENABLED = True
            sender_mod._safe_print = _forward_print
            argv = ["send_grbl_file.py", com, baud, str(gcode_file)]
            if sleep_after:
                argv.append("--sleep")
            rc = int(sender_mod.main(argv))
        finally:
            if original_print is not None:
                sender_mod._safe_print = original_print
            sender_mod._PRINT_ENABLED = original_enabled

        elapsed_local = time.perf_counter() - started_local
        return rc, out_lines, sender_plot_time_s, elapsed_local

    logger("Sending to Grbl ...")
    use_inline = bool(getattr(sys, "frozen", False)) or os.environ.get("PLOTTER_INLINE_SENDER") == "1"

    def _best_effort_safe_release_after_sender_failure(reason: str) -> None:
        try:
            logger(f"Sender stopped before normal teardown ({reason}); forcing safe park/release...")
            ok_release, msg_release = manual_commands.grbl_safe_park_release(
                com,
                baud,
                default_baud=baud,
                soft_reset_first=True,
                read_tail=True,
                sleep=bool(sleep_after),
                release=True,
                hold=False,
                home=True,
                z_up=z_up,
                z_feed=safe_lift_feed,
                travel_feed=15000.0,
                append_status_query=True,
                serial_timeout_s=1.0,
                wake_delay_s=0.10,
                reset_delay_s=0.80,
                command_delay_s=0.10,
                tail_delay_s=0.20,
            )
            logger(f"Safe park/release after sender failure: {'ok' if ok_release else 'failed'}: {msg_release}")
        except Exception as release_exc:  # pragma: no cover - best-effort safety path
            logger(
                "Safe park/release after sender failure failed "
                f"({type(release_exc).__name__}: {release_exc})"
            )

    if use_inline:
        try:
            rc, out_lines, sender_plot_time_s, elapsed = _run_sender_inline()
        except ToolDependencyError:
            raise
        except Exception as exc:
            raise SerialTransportError(
                f"Inline sender execution failed ({type(exc).__name__}: {exc})"
            ) from exc
    else:
        cmd = [sys.executable, str(sender), com, baud, str(gcode_file)]
        if sleep_after:
            cmd.append("--sleep")
        started = time.perf_counter()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            raise SerialTransportError(
                f"Failed to start sender process ({type(exc).__name__}: {exc})"
            ) from exc
        if proc.stdout is None:
            raise SerialTransportError("Failed to read sender output")
        out_lines = []
        sender_plot_time_s = None
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                s = line.strip()
                out_lines.append(s)
                logger(s)
                if s.startswith("PLOT_TIME_SECONDS="):
                    try:
                        sender_plot_time_s = float(s.split("=", 1)[1].strip())
                    except Exception:
                        pass
            rc = proc.wait()
            elapsed = time.perf_counter() - started
        except Exception as exc:
            raise SerialTransportError(
                f"Sender process I/O failed ({type(exc).__name__}: {exc})"
            ) from exc

    if rc == 0:
        return sender_plot_time_s if sender_plot_time_s is not None else max(0.0, elapsed)

    if not auto_resume or max_resume_attempts <= 0:
        _best_effort_safe_release_after_sender_failure(f"rc={rc}")
        tail = "\n".join(out_lines[-8:]) if out_lines else ""
        raise SerialTransportError(f"Sender error code: {rc}\n{tail}".strip())

    logger("Sender failed. Waiting for machine to become Idle, then auto-resuming from current position...")
    grbl_wait_for_idle(com, baud, logger)
    wx, wy, _wz = grbl_get_wpos_xyz(com, baud)
    start_line = find_nearest_g0_xy_line(gcode_file, x=wx, y=wy)
    resume_path = ensure_local_tmp_root() / f"resume_{gcode_file.stem}_from_{start_line}.nc"
    write_resume_file(
        gcode_file,
        resume_path,
        start_line=start_line,
        z_up=z_up,
        safe_lift_feed=safe_lift_feed,
        z_delay_up=z_delay_up,
    )
    logger(f"Auto-resume: WPos=({wx:.3f},{wy:.3f}), start_line={start_line}, file={resume_path}")
    resumed = send_to_grbl(
        resume_path,
        com,
        baud,
        logger,
        sleep_after=sleep_after,
        auto_resume=False,
        max_resume_attempts=0,
        root_dir=root_dir,
        ensure_local_tmp_root=ensure_local_tmp_root,
        grbl_wait_for_idle=grbl_wait_for_idle,
        grbl_get_wpos_xyz=grbl_get_wpos_xyz,
        z_up=z_up,
        safe_lift_feed=safe_lift_feed,
        z_delay_up=z_delay_up,
    )
    return max(0.0, elapsed) + max(0.0, resumed)
