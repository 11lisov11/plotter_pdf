from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .job_report import summarize_existing_gcode, write_job_report
from .models import JobResult, JobSettings


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def _plotter_cli_command() -> list[str]:
    if getattr(sys, "frozen", False):
        exe = _runtime_root() / "plotter-pdf.exe"
        if exe.exists():
            return [str(exe)]
    return [sys.executable, str(_project_root() / "main.py")]


def _append_sheet_args(args: list[str], settings: JobSettings) -> None:
    args.extend(["--machine-profile", settings.machine_profile])
    args.extend(["--calibration-layout", settings.calibration_layout])
    args.extend(["--sheet-format", settings.sheet_format])
    if settings.sheet_width_mm is not None:
        args.extend(["--sheet-width-mm", str(settings.sheet_width_mm)])
    if settings.sheet_height_mm is not None:
        args.extend(["--sheet-height-mm", str(settings.sheet_height_mm)])
    args.extend(["--sheet-anchor", settings.sheet_anchor])
    args.extend(["--sheet-offset-x-mm", str(settings.sheet_offset_x_mm)])
    args.extend(["--sheet-offset-y-mm", str(settings.sheet_offset_y_mm)])
    pass_cols = max(1, int(settings.pass_cols))
    pass_rows = max(1, int(settings.pass_rows))
    args.extend(["--pass-cols", str(pass_cols)])
    args.extend(["--pass-rows", str(pass_rows)])
    args.extend(["--pass-col", str(max(1, int(settings.pass_col)))])
    args.extend(["--pass-row", str(max(1, int(settings.pass_row)))])
    if str(settings.sheet_format).strip().lower() == "a3" and pass_cols == 1 and pass_rows == 1:
        args.append("--auto-pass-grid")
    args.extend(["--tool", settings.tool])
    args.extend(["--quality", settings.quality])
    args.extend(["--draw-order", settings.draw_order])
    args.append("--safe-travel-up" if settings.safe_travel_up else "--no-safe-travel-up")
    args.append("--handwriting" if settings.handwriting else "--no-handwriting")


def prepare_gcode_job(settings: JobSettings) -> JobResult:
    input_path = settings.normalized_input_path()
    output_dir = settings.normalized_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    if input_path is None:
        result = JobResult(False, "Нужно выбрать файл чертежа.", output_dir=output_dir, errors=["missing_input"])
        return write_job_report(result, output_dir)
    if not input_path.exists():
        result = JobResult(False, f"Файл не найден: {input_path}", output_dir=output_dir, errors=["input_not_found"])
        return write_job_report(result, output_dir)

    nc_path = output_dir / f"{input_path.stem}_prepared.nc"
    gcode_path = output_dir / f"{input_path.stem}_prepared.gcode"
    cmd = [
        *_plotter_cli_command(),
        str(input_path),
        "--dry-run",
        "--output",
        str(nc_path),
        "--skip-calibration",
        "--skip-calibration-confirmation",
        "--baud",
        str(settings.baud),
    ]
    if settings.com:
        cmd.extend(["--com", str(settings.com)])
    _append_sheet_args(cmd, settings)

    proc = subprocess.run(
        cmd,
        cwd=str(_runtime_root()),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        result = JobResult(
            False,
            f"Подготовка завершилась с ошибкой (код {proc.returncode}).",
            output_dir=output_dir,
            nc_path=nc_path,
            gcode_path=gcode_path,
            errors=[proc.stdout.strip()],
        )
        return write_job_report(result, output_dir)

    if nc_path.exists():
        shutil.copyfile(nc_path, gcode_path)
    line_count, draw_moves, travel_moves, bounds = summarize_existing_gcode(nc_path)
    result = JobResult(
        True,
        f"G-code подготовлен: {nc_path}",
        output_dir=output_dir,
        nc_path=nc_path if nc_path.exists() else None,
        gcode_path=gcode_path if gcode_path.exists() else None,
        bounds=bounds,
        line_count=line_count,
        draw_moves=draw_moves,
        travel_moves=travel_moves,
    )
    return write_job_report(result, output_dir)
