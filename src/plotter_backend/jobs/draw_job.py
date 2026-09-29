from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .job_report import write_job_report
from .models import JobResult, JobSettings
from .prepare_job import _append_sheet_args, _plotter_cli_command, _resolve_input, _runtime_root, prepare_gcode_job


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
    try:
        input_path, layout_build = _resolve_input(settings)
    except Exception as exc:
        result = JobResult(
            False,
            f"Не удалось подготовить раскладку PDF: {exc}",
            output_dir=output_dir,
            errors=[str(exc)],
        )
        return write_job_report(result, output_dir)
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
    try:
        nc_path.unlink(missing_ok=True)
    except OSError as exc:
        result = JobResult(
            False,
            f"Не удалось очистить предыдущий NC-файл: {exc}",
            output_dir=output_dir,
            errors=[str(exc)],
        )
        return write_job_report(result, output_dir)
    cmd = [
        *_plotter_cli_command(),
        str(input_path),
        "--output",
        str(nc_path),
        "--skip-calibration",
        "--skip-calibration-confirmation",
        "--com",
        str(settings.com),
        "--baud",
        str(settings.baud),
    ]
    _append_sheet_args(cmd, settings)
    try:
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
    except Exception as exc:
        result = JobResult(
            False,
            f"Не удалось запустить рисование: {exc}",
            output_dir=output_dir,
            errors=[str(exc)],
            layout_pdf_path=layout_build.output_pdf if layout_build else None,
            layout_preview_pdf_path=layout_build.preview_pdf if layout_build else None,
            layout_manifest_path=layout_build.manifest_path if layout_build else None,
            layout_page_paths=layout_build.page_pdf_paths if layout_build else [],
            layout_page_count=layout_build.page_count if layout_build else 0,
        )
        return write_job_report(result, output_dir)
    output_ok = nc_path.is_file() and nc_path.stat().st_size > 0
    result_ok = proc.returncode == 0 and output_ok
    if proc.returncode != 0:
        message = f"Рисование завершилось с ошибкой (код {proc.returncode})."
        errors = [proc.stdout.strip()]
    elif not output_ok:
        message = "Команда рисования завершилась без выходного NC-файла."
        errors = ["missing_or_empty_nc_output"]
    else:
        message = "Рисование завершено."
        errors = []
    result = JobResult(
        result_ok,
        message,
        output_dir=output_dir,
        nc_path=nc_path if nc_path.exists() else None,
        errors=errors,
        layout_pdf_path=layout_build.output_pdf if layout_build else None,
        layout_preview_pdf_path=layout_build.preview_pdf if layout_build else None,
        layout_manifest_path=layout_build.manifest_path if layout_build else None,
        layout_page_paths=layout_build.page_pdf_paths if layout_build else [],
        layout_page_count=layout_build.page_count if layout_build else 0,
    )
    return write_job_report(result, output_dir)
