from __future__ import annotations

import html
import os
import re
from dataclasses import asdict
from pathlib import Path

from .models import JobResult, JobSettings
from .prepare_job import prepare_gcode_job


_WORD_RE = re.compile(r"([A-Z])\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_SHEET_SIZES_MM = {
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "work": (180.0, 280.0),
    "notebook": (180.0, 280.0),
}
_WORKSPACE_BOUNDS = (0.0, 180.0, -285.0, -5.0)


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


def _strip_gcode_comment(line: str) -> str:
    out: list[str] = []
    in_paren = False
    for char in line:
        if char == "(":
            in_paren = True
            continue
        if char == ")":
            in_paren = False
            continue
        if char == ";" and not in_paren:
            break
        if not in_paren:
            out.append(char)
    return "".join(out)


def _parse_gcode_words(line: str) -> dict[str, float]:
    return {letter.upper(): float(value) for letter, value in _WORD_RE.findall(_strip_gcode_comment(line))}


def _gcode_to_polylines(
    lines: list[str],
    *,
    z_up: float | None,
    z_down: float | None,
) -> list[list[tuple[float, float]]]:
    out: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = 0.0
    y = 0.0
    z = z_up if z_up is not None else 0.0
    abs_mode = True
    modal_g = 0
    pen_down = False
    z_tol = 0.05

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            out.append(current)
        current = []

    for raw_line in lines:
        line = _strip_gcode_comment(raw_line).strip().upper()
        if not line:
            continue
        if "G90" in line:
            abs_mode = True
        if "G91" in line:
            abs_mode = False
        if "M3" in line:
            pen_down = True
        if "M5" in line:
            pen_down = False
            flush()

        words = _parse_gcode_words(line)
        if "G" in words:
            next_g = int(words["G"])
            if next_g in {0, 1, 2, 3, 92}:
                modal_g = next_g
            if next_g == 92:
                if "X" in words:
                    x = float(words["X"])
                if "Y" in words:
                    y = float(words["Y"])
                flush()
                continue

        if "Z" in words:
            next_z = float(words["Z"]) if abs_mode else z + float(words["Z"])
            if z_down is not None and abs(next_z - z_down) <= z_tol:
                pen_down = True
            elif z_up is not None and abs(next_z - z_up) <= z_tol:
                pen_down = False
                flush()
            z = next_z

        has_xy = "X" in words or "Y" in words
        if not has_xy:
            continue

        next_x = x
        next_y = y
        if "X" in words:
            value = float(words["X"])
            next_x = value if abs_mode else x + value
        if "Y" in words:
            value = float(words["Y"])
            next_y = value if abs_mode else y + value

        is_motion = modal_g in {0, 1, 2, 3}
        draw_active = pen_down or (z_up is None and z_down is None)
        if is_motion and modal_g != 0 and draw_active:
            if not current:
                current = [(x, y)]
            current.append((next_x, next_y))
        else:
            flush()

        x = next_x
        y = next_y

    flush()
    return out


def _open_preview(path: Path) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]


def _polyline_bounds(polylines: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for poly in polylines for x, _y in poly]
    ys = [y for poly in polylines for _x, y in poly]
    if not xs or not ys:
        return _WORKSPACE_BOUNDS
    return min(xs), max(xs), min(ys), max(ys)


def _sheet_size(settings: JobSettings) -> tuple[float, float]:
    if settings.sheet_format == "custom" and settings.sheet_width_mm and settings.sheet_height_mm:
        return float(settings.sheet_width_mm), float(settings.sheet_height_mm)
    return _SHEET_SIZES_MM.get(str(settings.sheet_format).lower(), _SHEET_SIZES_MM["a4"])


def _sheet_bounds(settings: JobSettings) -> tuple[float, float, float, float]:
    wx0, wx1, wy0, wy1 = _WORKSPACE_BOUNDS
    ww = wx1 - wx0
    wh = wy1 - wy0
    sw, sh = _sheet_size(settings)
    anchor = str(settings.sheet_anchor or "center").lower()
    ox = float(settings.sheet_offset_x_mm or 0.0)
    oy = float(settings.sheet_offset_y_mm or 0.0)

    if "left" in anchor:
        x0 = wx0 + ox
    elif "right" in anchor:
        x0 = wx1 - sw + ox
    else:
        x0 = wx0 + (ww - sw) / 2.0 + ox

    if "top" in anchor:
        y1 = wy1 + oy
        y0 = y1 - sh
    elif "bottom" in anchor:
        y0 = wy0 + oy
        y1 = y0 + sh
    else:
        y0 = wy0 + (wh - sh) / 2.0 + oy
        y1 = y0 + sh

    return x0, x0 + sw, y0, y1


def _display_rect(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, x1, y0, y1 = bounds
    return x0, -y1, x1 - x0, y1 - y0


def _path_d(polyline: list[tuple[float, float]]) -> str:
    first_x, first_y = polyline[0]
    parts = [f"M {first_x:.4f} {-first_y:.4f}"]
    parts.extend(f"L {x:.4f} {-y:.4f}" for x, y in polyline[1:])
    return " ".join(parts)


def _union_bounds(*bounds_items: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (
        min(item[0] for item in bounds_items),
        max(item[1] for item in bounds_items),
        min(item[2] for item in bounds_items),
        max(item[3] for item in bounds_items),
    )


def _grid_shape(settings: JobSettings) -> tuple[int, int]:
    cols = max(1, int(settings.pass_cols or 1))
    rows = max(1, int(settings.pass_rows or 1))
    if str(settings.sheet_format).lower() == "a3" and cols == 1 and rows == 1:
        rows = 2
    return cols, rows


def _write_interactive_preview(
    polylines: list[list[tuple[float, float]]],
    svg_path: Path,
    html_path: Path,
    settings: JobSettings,
) -> None:
    sheet = _sheet_bounds(settings)
    drawing = _polyline_bounds(polylines)
    union = _union_bounds(_WORKSPACE_BOUNDS, sheet, drawing)
    ux0, ux1, uy0, uy1 = union
    pad = 12.0
    view_x = ux0 - pad
    view_y = -uy1 - pad
    view_w = (ux1 - ux0) + pad * 2.0
    view_h = (uy1 - uy0) + pad * 2.0

    sheet_x, sheet_y, sheet_w, sheet_h = _display_rect(sheet)
    work_x, work_y, work_w, work_h = _display_rect(_WORKSPACE_BOUNDS)
    cols, rows = _grid_shape(settings)
    pass_col = min(max(1, int(settings.pass_col or 1)), cols)
    pass_row = min(max(1, int(settings.pass_row or 1)), rows)
    cell_w = sheet_w / cols
    cell_h = sheet_h / rows
    selected_x = sheet_x + (pass_col - 1) * cell_w
    selected_y = sheet_y + (pass_row - 1) * cell_h

    paths = "\n".join(
        f'      <path d="{_path_d(polyline)}" />'
        for polyline in polylines
        if len(polyline) >= 2
    )
    vertical_splits = "\n".join(
        f'      <line x1="{sheet_x + cell_w * col:.4f}" y1="{sheet_y:.4f}" x2="{sheet_x + cell_w * col:.4f}" y2="{sheet_y + sheet_h:.4f}" />'
        for col in range(1, cols)
    )
    horizontal_splits = "\n".join(
        f'      <line x1="{sheet_x:.4f}" y1="{sheet_y + cell_h * row:.4f}" x2="{sheet_x + sheet_w:.4f}" y2="{sheet_y + cell_h * row:.4f}" />'
        for row in range(1, rows)
    )
    sheet_label = "A3 склеенный формат" if str(settings.sheet_format).lower() == "a3" else f"Лист {settings.sheet_format}"
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
     width="{view_w:.3f}mm" height="{view_h:.3f}mm" viewBox="{view_x:.3f} {view_y:.3f} {view_w:.3f} {view_h:.3f}">
  <rect x="{view_x:.4f}" y="{view_y:.4f}" width="{view_w:.4f}" height="{view_h:.4f}" fill="#f7f4ec" />
  <g fill="none" vector-effect="non-scaling-stroke">
    <g id="sheet">
      <rect x="{sheet_x:.4f}" y="{sheet_y:.4f}" width="{sheet_w:.4f}" height="{sheet_h:.4f}" fill="#ffffff" stroke="#2563eb" stroke-width="0.7" />
      <rect x="{selected_x:.4f}" y="{selected_y:.4f}" width="{cell_w:.4f}" height="{cell_h:.4f}" fill="#dbeafe" fill-opacity="0.35" stroke="#1d4ed8" stroke-width="0.5" />
{vertical_splits}
{horizontal_splits}
      <text x="{sheet_x + 3.0:.4f}" y="{sheet_y + 7.0:.4f}" fill="#1d4ed8" font-family="Segoe UI, Arial, sans-serif" font-size="4">{html.escape(sheet_label)}</text>
      <text x="{selected_x + 3.0:.4f}" y="{selected_y + 13.0:.4f}" fill="#1e40af" font-family="Segoe UI, Arial, sans-serif" font-size="3.5">текущий проход {pass_col}/{pass_row}</text>
    </g>
    <g id="workspace">
      <rect x="{work_x:.4f}" y="{work_y:.4f}" width="{work_w:.4f}" height="{work_h:.4f}" stroke="#f97316" stroke-width="0.45" stroke-dasharray="4 3" />
      <text x="{work_x + 3.0:.4f}" y="{work_y + work_h - 4.0:.4f}" fill="#c2410c" font-family="Segoe UI, Arial, sans-serif" font-size="3.5">рабочая область плоттера</text>
    </g>
    <g id="drawing" stroke="#111827" stroke-width="0.25" stroke-linecap="round" stroke-linejoin="round">
{paths}
    </g>
  </g>
</svg>
"""
    svg_path.write_text(svg, encoding="utf-8")

    svg_embed = svg.split("\n", 1)[1] if svg.startswith("<?xml") else svg
    title = html.escape(f"Предпросмотр Plotter PDF - {Path(settings.input_path or 'чертеж').name}")
    html_text = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    html, body {{ margin: 0; height: 100%; overflow: hidden; background: #111; color: #eee; font-family: "Segoe UI", Arial, sans-serif; }}
    .bar {{ position: fixed; left: 12px; top: 12px; z-index: 2; padding: 8px 10px; border-radius: 10px; background: rgba(17, 24, 39, 0.88); box-shadow: 0 8px 24px rgba(0,0,0,.35); font-size: 14px; }}
    .bar b {{ color: #93c5fd; }}
    svg {{ width: 100vw; height: 100vh; display: block; cursor: grab; background: #1f2937; }}
    svg.dragging {{ cursor: grabbing; }}
  </style>
</head>
<body>
  <div class="bar"><b>Предпросмотр:</b> колесо - масштаб, мышью - таскать, двойной клик - сброс.</div>
  {svg_embed}
  <script>
    const svg = document.querySelector('svg');
    const initial = svg.getAttribute('viewBox').split(/\\s+/).map(Number);
    let view = initial.slice();
    let dragging = false;
    let last = null;
    function apply() {{ svg.setAttribute('viewBox', view.join(' ')); }}
    function point(evt) {{
      const r = svg.getBoundingClientRect();
      return [
        view[0] + (evt.clientX - r.left) / r.width * view[2],
        view[1] + (evt.clientY - r.top) / r.height * view[3],
      ];
    }}
    svg.addEventListener('wheel', (evt) => {{
      evt.preventDefault();
      const p = point(evt);
      const k = evt.deltaY > 0 ? 1.15 : 0.87;
      view[0] = p[0] - (p[0] - view[0]) * k;
      view[1] = p[1] - (p[1] - view[1]) * k;
      view[2] *= k;
      view[3] *= k;
      apply();
    }}, {{ passive: false }});
    svg.addEventListener('pointerdown', (evt) => {{ dragging = true; last = point(evt); svg.classList.add('dragging'); svg.setPointerCapture(evt.pointerId); }});
    svg.addEventListener('pointermove', (evt) => {{
      if (!dragging) return;
      const p = point(evt);
      view[0] += last[0] - p[0];
      view[1] += last[1] - p[1];
      apply();
      last = point(evt);
    }});
    svg.addEventListener('pointerup', () => {{ dragging = false; svg.classList.remove('dragging'); }});
    svg.addEventListener('pointercancel', () => {{ dragging = false; svg.classList.remove('dragging'); }});
    svg.addEventListener('dblclick', () => {{ view = initial.slice(); apply(); }});
  </script>
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")


def _write_interactive_preview(
    polylines: list[list[tuple[float, float]]],
    svg_path: Path,
    html_path: Path,
    settings: JobSettings,
    job_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    drawing = job_bounds or _polyline_bounds(polylines)
    union = _union_bounds(_WORKSPACE_BOUNDS, drawing)
    ux0, ux1, uy0, uy1 = union
    pad = 10.0
    view_x = ux0 - pad
    view_y = -uy1 - pad
    view_w = (ux1 - ux0) + pad * 2.0
    view_h = (uy1 - uy0) + pad * 2.0

    draw_x, draw_y, draw_w, draw_h = _display_rect(drawing)
    work_x, work_y, work_w, work_h = _display_rect(_WORKSPACE_BOUNDS)
    cols = max(1, int(settings.pass_cols or 1))
    rows = max(1, int(settings.pass_rows or 1))
    if str(settings.sheet_format).lower() == "a3" and cols == 1 and rows == 1:
        cols = 2
        rows = 1
    pass_col = min(max(1, int(settings.pass_col or 1)), cols)
    pass_row = min(max(1, int(settings.pass_row or 1)), rows)
    cell_w = work_w / cols
    cell_h = work_h / rows
    selected_x = work_x + (pass_col - 1) * cell_w
    selected_y = work_y + (pass_row - 1) * cell_h

    paths = "\n".join(
        f'      <path d="{_path_d(polyline)}" />'
        for polyline in polylines
        if len(polyline) >= 2
    )
    vertical_splits = "\n".join(
        f'      <line x1="{work_x + cell_w * col:.4f}" y1="{work_y:.4f}" x2="{work_x + cell_w * col:.4f}" y2="{work_y + work_h:.4f}" />'
        for col in range(1, cols)
    )
    horizontal_splits = "\n".join(
        f'      <line x1="{work_x:.4f}" y1="{work_y + cell_h * row:.4f}" x2="{work_x + work_w:.4f}" y2="{work_y + cell_h * row:.4f}" />'
        for row in range(1, rows)
    )
    sheet_label = html.escape(str(settings.sheet_format).upper())
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
     width="{view_w:.3f}mm" height="{view_h:.3f}mm" viewBox="{view_x:.3f} {view_y:.3f} {view_w:.3f} {view_h:.3f}">
  <rect x="{view_x:.4f}" y="{view_y:.4f}" width="{view_w:.4f}" height="{view_h:.4f}" fill="#f7f4ec" />
  <g fill="none" vector-effect="non-scaling-stroke">
    <g id="workspace">
      <rect x="{work_x:.4f}" y="{work_y:.4f}" width="{work_w:.4f}" height="{work_h:.4f}" stroke="#f97316" stroke-width="0.45" stroke-dasharray="4 3" />
      <rect x="{selected_x:.4f}" y="{selected_y:.4f}" width="{cell_w:.4f}" height="{cell_h:.4f}" fill="#dbeafe" fill-opacity="0.25" stroke="#1d4ed8" stroke-width="0.4" />
{vertical_splits}
{horizontal_splits}
      <text x="{work_x + 3.0:.4f}" y="{work_y + work_h - 4.0:.4f}" fill="#c2410c" font-family="Segoe UI, Arial, sans-serif" font-size="3.5">рабочая область плоттера / проход {pass_col}x{pass_row} из {cols}x{rows}</text>
    </g>
    <g id="prepared-bounds">
      <rect x="{draw_x:.4f}" y="{draw_y:.4f}" width="{draw_w:.4f}" height="{draw_h:.4f}" stroke="#2563eb" stroke-width="0.45" />
      <text x="{draw_x + 2.0:.4f}" y="{draw_y + 6.0:.4f}" fill="#1d4ed8" font-family="Segoe UI, Arial, sans-serif" font-size="3.5">реальные границы подготовленного G-code ({sheet_label})</text>
    </g>
    <g id="drawing" stroke="#111827" stroke-width="0.25" stroke-linecap="round" stroke-linejoin="round">
{paths}
    </g>
  </g>
</svg>
"""
    svg_path.write_text(svg, encoding="utf-8")

    svg_embed = svg.split("\n", 1)[1] if svg.startswith("<?xml") else svg
    title = html.escape(f"Предпросмотр Plotter PDF - {Path(settings.input_path or 'чертеж').name}")
    html_text = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    html, body {{ margin: 0; height: 100%; overflow: hidden; background: #111; color: #eee; font-family: "Segoe UI", Arial, sans-serif; }}
    .bar {{ position: fixed; left: 12px; top: 12px; z-index: 2; padding: 8px 10px; border-radius: 10px; background: rgba(17, 24, 39, 0.88); box-shadow: 0 8px 24px rgba(0,0,0,.35); font-size: 14px; }}
    .bar b {{ color: #93c5fd; }}
    svg {{ width: 100vw; height: 100vh; display: block; cursor: grab; background: #1f2937; }}
    svg.dragging {{ cursor: grabbing; }}
  </style>
</head>
<body>
  <div class="bar"><b>Предпросмотр:</b> показан реальный G-code после всех правил. Колесо - масштаб, мышью - таскать, двойной клик - сброс.</div>
  {svg_embed}
  <script>
    const svg = document.querySelector('svg');
    const initial = svg.getAttribute('viewBox').split(/\\s+/).map(Number);
    let view = initial.slice();
    let dragging = false;
    let last = null;
    function apply() {{ svg.setAttribute('viewBox', view.join(' ')); }}
    function point(evt) {{
      const r = svg.getBoundingClientRect();
      return [
        view[0] + (evt.clientX - r.left) / r.width * view[2],
        view[1] + (evt.clientY - r.top) / r.height * view[3],
      ];
    }}
    svg.addEventListener('wheel', (evt) => {{
      evt.preventDefault();
      const p = point(evt);
      const k = evt.deltaY > 0 ? 1.15 : 0.87;
      view[0] = p[0] - (p[0] - view[0]) * k;
      view[1] = p[1] - (p[1] - view[1]) * k;
      view[2] *= k;
      view[3] *= k;
      apply();
    }}, {{ passive: false }});
    svg.addEventListener('pointerdown', (evt) => {{ dragging = true; last = point(evt); svg.classList.add('dragging'); svg.setPointerCapture(evt.pointerId); }});
    svg.addEventListener('pointermove', (evt) => {{
      if (!dragging) return;
      const p = point(evt);
      view[0] += last[0] - p[0];
      view[1] += last[1] - p[1];
      apply();
      last = point(evt);
    }});
    svg.addEventListener('pointerup', () => {{ dragging = false; svg.classList.remove('dragging'); }});
    svg.addEventListener('pointercancel', () => {{ dragging = false; svg.classList.remove('dragging'); }});
    svg.addEventListener('dblclick', () => {{ view = initial.slice(); apply(); }});
  </script>
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")


def preview_job(settings: JobSettings) -> JobResult:
    preview_settings = JobSettings(**asdict(settings))
    preview_settings.preview = True
    preview_settings.dry_run = True
    result = prepare_gcode_job(preview_settings)
    if not result.ok or result.nc_path is None:
        return result

    nc_path = result.nc_path
    svg_path = nc_path.with_suffix(".preview.svg")
    html_path = nc_path.with_suffix(".preview.html")

    try:
        lines = nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        z_up, z_down = _detect_pen_z(lines)
        polylines = _gcode_to_polylines(lines, z_up=z_up, z_down=z_down)
        _write_interactive_preview(polylines, svg_path, html_path, preview_settings, result.bounds)
        result.preview_svg_path = svg_path
        result.message = f"Предпросмотр открыт: {html_path}"
        _open_preview(html_path)
    except Exception as exc:
        result.message = f"Файл подготовлен: {nc_path}"
        result.warnings.append(f"Не удалось открыть визуальный предпросмотр: {exc}")

    return result
