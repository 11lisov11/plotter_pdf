from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.plotter_backend.geometry.arc_fit import arc_extents_xy, points_distance
from src.plotter_backend.gcode.stats import summarize_gcode_file

from .job_report import write_job_report
from .models import JobResult, JobSettings


def _guess_artifacts(output_dir: Path, input_path: Path) -> tuple[Path, Path, Path]:
    nc = output_dir / f"{input_path.stem}_prepared.nc"
    gcode = output_dir / f"{input_path.stem}_prepared.gcode"
    svg = output_dir / f"{input_path.stem}_trimmed.svg"
    return nc, gcode, svg


def _summarize(path: Path) -> tuple[int, int, int, tuple[float, float, float, float]]:
    return summarize_gcode_file(path, points_distance=points_distance, arc_extents_xy=arc_extents_xy)


def prepare_job(settings: JobSettings, logger: Callable[[str], None] | None = None) -> JobResult:
    log = logger or (lambda _msg: None)
    if not settings.input_path:
        return JobResult(False, "Input file is required.", errors=["missing_input"])
    input_path = Path(settings.input_path)
    if not input_path.exists():
        return JobResult(False, f"Input not found: {input_path}", errors=["missing_input"])
    output_dir = settings.normalized_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    nc_path, gcode_path, preview_svg = _guess_artifacts(output_dir, input_path)
    output_path = nc_path

    from src import plotter_pdf_drawer as backend

    try:
        backend.configure_active_work_area(
            sheet_format=settings.sheet_format,
            sheet_width_mm=settings.sheet_width_mm,
            sheet_height_mm=settings.sheet_height_mm,
            anchor=settings.sheet_anchor,
            offset_x_mm=settings.sheet_offset_x_mm,
            offset_y_mm=settings.sheet_offset_y_mm,
            logger=log,
        )
        backend.PASS_COLS = max(1, int(settings.pass_cols))
        backend.PASS_ROWS = max(1, int(settings.pass_rows))
        backend.PASS_COL = min(max(1, int(settings.pass_col)), backend.PASS_COLS)
        backend.PASS_ROW = min(max(1, int(settings.pass_row)), backend.PASS_ROWS)
        backend.TOOL_MODE = (settings.tool or "pen").lower()
        backend.SAFE_PEN_TRAVEL_UP = bool(settings.safe_travel_up)
        backend.HANDWRITING_TEXT_ENABLED = bool(settings.handwriting)
        backend.DRAW_ORDER_MODE = (settings.draw_order or "auto").lower()
        backend.apply_quality_profile(quality=settings.quality)
        ok, msg = backend.run_pipeline_with_corner_calibration(
            input_path,
            log,
            com=settings.com or backend.detect_com_port(None),
            baud=str(settings.baud),
            send_to_plotter=False,
            output_path=output_path,
            skip_calibration=True,
            skip_confirmation=True,
        )
    except Exception as exc:
        res = JobResult(False, f"Prepare failed: {type(exc).__name__}: {exc}", output_dir=output_dir, errors=[str(exc)])
        return write_job_report(res, output_dir)

    produced = output_path if output_path.exists() else None
    if produced is None and gcode_path.exists():
        produced = gcode_path
    line_count = draw_moves = travel_moves = 0
    bounds = None
    if produced and produced.exists():
        line_count, draw_moves, travel_moves, bounds = _summarize(produced)
    res = JobResult(
        bool(ok), msg, output_dir=output_dir, gcode_path=produced, nc_path=output_path if output_path.exists() else None,
        preview_svg_path=preview_svg if preview_svg.exists() else None, bounds=bounds,
        line_count=line_count, draw_moves=draw_moves, travel_moves=travel_moves,
        errors=[] if ok else [msg],
    )
    return write_job_report(res, output_dir)
