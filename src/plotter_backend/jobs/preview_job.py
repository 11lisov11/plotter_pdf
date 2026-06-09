from __future__ import annotations

import os
import re
from dataclasses import asdict
from pathlib import Path

from .models import JobResult, JobSettings
from .prepare_job import prepare_gcode_job

from scripts.gcode_to_svg_preview import gcode_to_polylines, write_svg


_WORD_RE = re.compile(r"([A-Z])\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def _detect_pen_z(lines: list[str]) -> tuple[float | None, float | None]:
    values: list[float] = []
    for line in lines:
        for letter, value in _WORD_RE.findall(line):
            if letter.upper() != "Z":
                continue
            try:
                values.append(float(value))
            except ValueError:
                continue

    rounded = sorted({round(v, 4) for v in values})
    if len(rounded) < 2:
        return None, None
    return min(rounded), max(rounded)


def _open_preview(path: Path) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]


def preview_job(settings: JobSettings) -> JobResult:
    preview_settings = JobSettings(**asdict(settings))
    preview_settings.preview = True
    preview_settings.dry_run = True
    result = prepare_gcode_job(preview_settings)
    if not result.ok or result.nc_path is None:
        return result

    nc_path = result.nc_path
    svg_path = nc_path.with_suffix(".preview.svg")

    try:
        lines = nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        z_up, z_down = _detect_pen_z(lines)
        polylines = gcode_to_polylines(lines, z_up=z_up, z_down=z_down)
        write_svg(polylines, svg_path)
        result.preview_svg_path = svg_path
        result.message = f"Предпросмотр открыт: {svg_path}"
        _open_preview(svg_path)
    except Exception as exc:
        result.message = f"Файл подготовлен: {nc_path}"
        result.warnings.append(f"Не удалось открыть визуальный предпросмотр: {exc}")

    return result
