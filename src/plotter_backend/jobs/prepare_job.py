from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .job_report import summarize_existing_gcode, write_job_report
from .models import JobResult, JobSettings
from .pdf_layout import PdfLayoutBuild, build_pdf_layout


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
    cols = max(1, int(settings.pass_cols))
    rows = max(1, int(settings.pass_rows))
    args.extend(["--pass-cols", str(cols)])
    args.extend(["--pass-rows", str(rows)])
    args.extend(["--pass-col", str(min(max(1, int(settings.pass_col)), cols))])
    args.extend(["--pass-row", str(min(max(1, int(settings.pass_row)), rows))])
    args.extend(["--output-rotation", str(int(settings.output_rotation_deg) % 360)])
    args.append("--mirror-x" if settings.mirror_x else "--no-mirror-x")
    args.append("--mirror-y" if settings.mirror_y else "--no-mirror-y")
    args.extend(["--tool", settings.tool])
    args.extend(["--quality", settings.quality])
    args.extend(["--draw-order", settings.draw_order])
    if settings.safe_travel_up is not None:
        args.append("--safe-travel-up" if settings.safe_travel_up else "--no-safe-travel-up")
    args.append("--handwriting" if settings.handwriting else "--no-handwriting")


def _resolve_input(settings: JobSettings) -> tuple[Path | None, PdfLayoutBuild | None]:
    if not settings.input_paths:
        return settings.normalized_input_path(), None
    build = build_pdf_layout(settings)
    selected_page = min(max(1, int(settings.layout_page)), build.page_count)
    return build.page_pdf_paths[selected_page - 1], build


def prepare_gcode_job(settings: JobSettings) -> JobResult:
    output_dir = settings.normalized_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        input_path, layout_build = _resolve_input(settings)
    except Exception as exc:
        return write_job_report(
            JobResult(
                False,
                f"Не удалось подготовить раскладку PDF: {exc}",
                output_dir=output_dir,
                errors=[str(exc)],
            ),
            output_dir,
        )
    if input_path is None:
        return write_job_report(
            JobResult(False, "Нужно выбрать файл чертежа.", output_dir=output_dir, errors=["missing_input"]),
            output_dir,
        )
    if not input_path.exists():
        return write_job_report(
            JobResult(False, f"Файл не найден: {input_path}", output_dir=output_dir, errors=["input_not_found"]),
            output_dir,
        )

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
        return write_job_report(
            JobResult(
                False,
                f"Подготовка завершилась с ошибкой (код {proc.returncode}).",
                output_dir=output_dir,
                nc_path=nc_path,
                gcode_path=gcode_path,
                errors=[proc.stdout.strip()],
                layout_pdf_path=layout_build.output_pdf if layout_build else None,
                layout_preview_pdf_path=layout_build.preview_pdf if layout_build else None,
                layout_manifest_path=layout_build.manifest_path if layout_build else None,
                layout_page_paths=layout_build.page_pdf_paths if layout_build else [],
                layout_page_count=layout_build.page_count if layout_build else 0,
            ),
            output_dir,
        )
    if nc_path.exists():
        shutil.copyfile(nc_path, gcode_path)
    line_count, draw_moves, travel_moves, bounds = summarize_existing_gcode(nc_path)
    return write_job_report(
        JobResult(
            True,
            f"G-code подготовлен: {nc_path}",
            output_dir=output_dir,
            nc_path=nc_path if nc_path.exists() else None,
            gcode_path=gcode_path if gcode_path.exists() else None,
            bounds=bounds,
            line_count=line_count,
            draw_moves=draw_moves,
            travel_moves=travel_moves,
            layout_pdf_path=layout_build.output_pdf if layout_build else None,
            layout_preview_pdf_path=layout_build.preview_pdf if layout_build else None,
            layout_manifest_path=layout_build.manifest_path if layout_build else None,
            layout_page_paths=layout_build.page_pdf_paths if layout_build else [],
            layout_page_count=layout_build.page_count if layout_build else 0,
        ),
        output_dir,
    )
