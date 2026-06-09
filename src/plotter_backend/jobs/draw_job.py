from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .job_report import write_job_report
from .models import JobResult, JobSettings
from .prepare_job import _append_sheet_args, _plotter_cli_command, _runtime_root, prepare_gcode_job


def _hardware_enabled(settings: JobSettings, confirm_hardware: bool) -> bool:
    env_ok = os.environ.get("PLOTTER_HARDWARE") == "1"
    env_com = os.environ.get("PLOTTER_COM")
    if env_ok and env_com and str(env_com).strip().upper() == str(settings.com or "").strip().upper():
        return True
    return bool(confirm_hardware)


def draw_job(settings: JobSettings, *, confirm_hardware: bool = False) -> JobResult:
    if settings.dry_run or settings.preview:
        return prepare_gcode_job(settings)
    output_dir = settings.normalized_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = settings.normalized_input_path()
    if input_path is None:
        result = JobResult(False, "Нужно выбрать файл чертежа.", output_dir=output_dir, errors=["missing_input"])
        return write_job_report(result, output_dir)
    if not settings.com:
        result = JobResult(False, "Не найден COM-порт плоттера.", output_dir=output_dir, errors=["missing_com"])
        return write_job_report(result, output_dir)
    if not _hardware_enabled(settings, confirm_hardware):
        result = JobResult(
            False,
            "Рисование на плоттере заблокировано до подтверждения операции.",
            output_dir=output_dir,
            errors=["hardware_not_confirmed"],
        )
        return write_job_report(result, output_dir)

    nc_path = output_dir / f"{Path(input_path).stem}_draw.nc"
    cmd = [
        *_plotter_cli_command(),
        str(input_path),
        "--output",
        str(nc_path),
        "--skip-calibration-confirmation",
        "--com",
        str(settings.com),
        "--baud",
        str(settings.baud),
    ]
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
    result = JobResult(
        proc.returncode == 0,
        "Рисование завершено." if proc.returncode == 0 else f"Рисование завершилось с ошибкой (код {proc.returncode}).",
        output_dir=output_dir,
        nc_path=nc_path if nc_path.exists() else None,
        errors=[] if proc.returncode == 0 else [proc.stdout.strip()],
    )
    return write_job_report(result, output_dir)
