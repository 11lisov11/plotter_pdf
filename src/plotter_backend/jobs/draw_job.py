from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.plotter_backend.gcode.preflight import preflight_check_gcode

from .models import JobResult, JobSettings
from .prepare_job import prepare_job


def draw_job(settings: JobSettings, logger: Callable[[str], None] | None = None, *, confirmed: bool = False) -> JobResult:
    log = logger or (lambda _msg: None)
    if not confirmed:
        return JobResult(False, "Hardware draw requires explicit user confirmation.", errors=["not_confirmed"])
    if not settings.com:
        return JobResult(False, "COM port is required for Draw.", errors=["missing_com"])
    prepared = prepare_job(settings, log)
    if not prepared.ok or not prepared.gcode_path:
        return prepared
    from src import plotter_pdf_drawer as backend
    ok, msg = preflight_check_gcode(
        Path(prepared.gcode_path), log, preflight_enabled=True, preflight_max_gcode_lines=backend.PREFLIGHT_MAX_GCODE_LINES,
        preflight_max_travel_to_draw_ratio=backend.PREFLIGHT_MAX_TRAVEL_TO_DRAW_RATIO,
        preflight_bounds_margin_mm=backend.PREFLIGHT_BOUNDS_MARGIN_MM, z_up=backend.Z_UP, z_down=backend.Z_DOWN,
        bounds=prepared.bounds, work_area_bounds=backend.work_area_bounds, summarize_gcode_file=backend.summarize_gcode_file,
        gcode_draw_bounds=backend.gcode_draw_bounds,
    )
    if not ok:
        prepared.ok = False
        prepared.message = f"Preflight failed: {msg}"
        prepared.errors.append(prepared.message)
        return prepared
    try:
        backend.run_sender(prepared.gcode_path, settings.com, str(settings.baud), log)
    except Exception as exc:
        prepared.ok = False
        prepared.message = f"Draw failed: {type(exc).__name__}: {exc}"
        prepared.errors.append(str(exc))
        return prepared
    prepared.message = "Draw completed."
    return prepared
