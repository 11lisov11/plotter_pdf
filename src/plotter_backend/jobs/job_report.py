from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import JobResult


def write_job_report(result: JobResult, output_dir: Path) -> JobResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = output_dir / "report.json"
    summary = output_dir / "summary.csv"
    report.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    with summary.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ok", "line_count", "draw_moves", "travel_moves", "bounds", "message"])
        writer.writerow([result.ok, result.line_count, result.draw_moves, result.travel_moves, result.bounds, result.message])
    result.report_json_path = report
    result.summary_csv_path = summary
    return result
