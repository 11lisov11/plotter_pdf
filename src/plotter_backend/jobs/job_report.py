from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Optional

from ..gcode import stats as gcode_stats
from .models import JobResult


def _points_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _arc_extents_xy(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    cw: bool,
) -> tuple[float, float, float, float]:
    del cw
    radius = max(_points_distance(start, center), _points_distance(end, center))
    return center[0] - radius, center[0] + radius, center[1] - radius, center[1] + radius


def summarize_existing_gcode(gcode_path: Optional[Path]) -> tuple[int, int, int, Optional[tuple[float, float, float, float]]]:
    if gcode_path is None or not gcode_path.exists():
        return 0, 0, 0, None
    line_count, draw_moves, travel_moves, bounds = gcode_stats.summarize_gcode_file(
        gcode_path,
        points_distance=_points_distance,
        arc_extents_xy=_arc_extents_xy,
    )
    return int(line_count), int(draw_moves), int(travel_moves), bounds


def write_job_report(result: JobResult, output_dir: Path) -> JobResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    summary_path = output_dir / "summary.csv"
    result.report_json_path = report_path
    result.summary_csv_path = summary_path
    report_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["ok", "message", "line_count", "draw_moves", "travel_moves", "bounds", "gcode_path", "nc_path"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "ok": result.ok,
                "message": result.message,
                "line_count": result.line_count,
                "draw_moves": result.draw_moves,
                "travel_moves": result.travel_moves,
                "bounds": result.bounds,
                "gcode_path": result.gcode_path,
                "nc_path": result.nc_path,
            }
        )
    return result
