from __future__ import annotations

import html
import os
import re
from dataclasses import asdict
from pathlib import Path

import fitz

from .models import JobResult, JobSettings
from .prepare_job import prepare_gcode_job

try:
    from src.plotter_backend.machine import profiles as machine_profiles_mod
except ImportError:  # pragma: no cover
    from plotter_backend.machine import profiles as machine_profiles_mod


_WORD_RE = re.compile(r"([A-Z])\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_SHEET_SIZES_MM = {
    "a4": (210.0, 297.0),
    "a3": (420.0, 297.0),
    "a2": (420.0, 594.0),
    "work": (180.0, 280.0),
    "notebook": (165.0, 205.0),
}
_WORKSPACE_BOUNDS = (0.0, 180.0, -285.0, -5.0)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MACHINE_PROFILE_PATH = _PROJECT_ROOT / "config" / "machine_profiles.json"


def _workspace_bounds(settings: JobSettings) -> tuple[float, float, float, float]:
    try:
        profile = machine_profiles_mod.resolve_machine_profile(settings.machine_profile, _MACHINE_PROFILE_PATH)
        work = machine_profiles_mod.profile_work_area(profile)
        return (
            work["min_x_mm"] + work["offset_x_mm"],
            work["max_x_mm"] + work["offset_x_mm"],
            work["min_y_mm"] + work["offset_y_mm"],
            work["max_y_mm"] + work["offset_y_mm"],
        )
    except Exception:
        return _WORKSPACE_BOUNDS


def _detect_pen_z(
    lines: list[str],
    settings: JobSettings | None = None,
) -> tuple[float | None, float | None]:
    if settings is not None:
        try:
            profile = machine_profiles_mod.resolve_machine_profile(settings.machine_profile, _MACHINE_PROFILE_PATH)
            pen = profile.get("pen", {})
            if pen.get("lift_mode", "z") == "z":
                return float(pen["z_up_mm"]), float(pen["z_down_mm"])
        except (KeyError, TypeError, ValueError):
            pass
    values = [float(value) for line in lines for letter, value in _WORD_RE.findall(line) if letter.upper() == "Z"]
    rounded = sorted({round(value, 4) for value in values})
    return (min(rounded), max(rounded)) if len(rounded) >= 2 else (None, None)


def _strip_gcode_comment(line: str) -> str:
    out: list[str] = []
    in_paren = False
    for char in line:
        if char == "(":
            in_paren = True
        elif char == ")":
            in_paren = False
        elif char == ";" and not in_paren:
            break
        elif not in_paren:
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
    output: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = y = 0.0
    z = z_up if z_up is not None else 0.0
    absolute = True
    modal_g = 0
    pen_down = False

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            output.append(current)
        current = []

    for raw_line in lines:
        line = _strip_gcode_comment(raw_line).strip().upper()
        if not line:
            continue
        g_codes = [
            float(value)
            for letter, value in _WORD_RE.findall(line)
            if letter.upper() == "G"
        ]
        if any(abs(code - 90.0) < 1e-9 for code in g_codes):
            absolute = True
        if any(abs(code - 91.0) < 1e-9 for code in g_codes):
            absolute = False
        if "M3" in line:
            pen_down = True
        if "M5" in line:
            pen_down = False
            flush()
        words = _parse_gcode_words(line)
        if "G" in words:
            command = int(words["G"])
            if command in {0, 1, 2, 3, 92}:
                modal_g = command
            if command == 92:
                x = float(words.get("X", x))
                y = float(words.get("Y", y))
                flush()
                continue
        if "Z" in words:
            next_z = float(words["Z"]) if absolute else z + float(words["Z"])
            if z_down is not None and abs(next_z - z_down) <= 0.05:
                pen_down = True
            elif z_up is not None and abs(next_z - z_up) <= 0.05:
                pen_down = False
                flush()
            z = next_z
        if "X" not in words and "Y" not in words:
            continue
        next_x = (float(words["X"]) if absolute else x + float(words["X"])) if "X" in words else x
        next_y = (float(words["Y"]) if absolute else y + float(words["Y"])) if "Y" in words else y
        if modal_g in {1, 2, 3} and (pen_down or (z_up is None and z_down is None)):
            if not current:
                current = [(x, y)]
            current.append((next_x, next_y))
        else:
            flush()
        x, y = next_x, next_y
    flush()
    return output


def _bounds(polylines: list[list[tuple[float, float]]], fallback) -> tuple[float, float, float, float]:
    points = [point for polyline in polylines for point in polyline]
    if not points:
        return fallback
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), max(xs), min(ys), max(ys)


def _paper_orientation_polylines(
    polylines: list[list[tuple[float, float]]],
    settings: JobSettings,
) -> list[list[tuple[float, float]]]:
    _wx0, _wx1, wy0, wy1 = _workspace_bounds(settings)
    if not (wy0 < 0.0 and wy1 <= 0.0):
        return polylines
    _sx0, _sx1, sy0, sy1 = _sheet_bounds(settings)
    mirror_sum = sy0 + sy1
    return [[(x, mirror_sum - y) for x, y in polyline] for polyline in polylines]


def _sheet_size(settings: JobSettings) -> tuple[float, float]:
    if settings.sheet_format == "custom" and settings.sheet_width_mm and settings.sheet_height_mm:
        return float(settings.sheet_width_mm), float(settings.sheet_height_mm)
    if settings.sheet_format == "work":
        x0, x1, y0, y1 = _workspace_bounds(settings)
        return x1 - x0, y1 - y0
    return _SHEET_SIZES_MM.get(str(settings.sheet_format).lower(), _SHEET_SIZES_MM["a4"])


def _sheet_bounds(settings: JobSettings) -> tuple[float, float, float, float]:
    wx0, wx1, wy0, wy1 = _workspace_bounds(settings)
    sw, sh = _sheet_size(settings)
    anchor = str(settings.sheet_anchor or "center").lower()
    ox = float(settings.sheet_offset_x_mm)
    oy = float(settings.sheet_offset_y_mm)
    x0 = wx0 + ox if "left" in anchor else wx1 - sw + ox if "right" in anchor else wx0 + ((wx1 - wx0) - sw) * 0.5 + ox
    if "top" in anchor:
        y1 = wy1 + oy
        y0 = y1 - sh
    elif "bottom" in anchor:
        y0 = wy0 + oy
        y1 = y0 + sh
    else:
        y0 = wy0 + ((wy1 - wy0) - sh) * 0.5 + oy
        y1 = y0 + sh
    return x0, x0 + sw, y0, y1


def _path_d(polyline: list[tuple[float, float]]) -> str:
    first_x, first_y = polyline[0]
    return " ".join([f"M {first_x:.4f} {-first_y:.4f}"] + [f"L {x:.4f} {-y:.4f}" for x, y in polyline[1:]])


def _display_rect(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, x1, y0, y1 = bounds
    return x0, -y1, x1 - x0, y1 - y0


def _union(*items: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return min(v[0] for v in items), max(v[1] for v in items), min(v[2] for v in items), max(v[3] for v in items)


def _write_preview_files(
    polylines: list[list[tuple[float, float]]],
    *,
    svg_path: Path,
    html_path: Path,
    pdf_path: Path,
    settings: JobSettings,
) -> None:
    workspace = _workspace_bounds(settings)
    sheet = _sheet_bounds(settings)
    drawing = _bounds(polylines, workspace)
    ux0, ux1, uy0, uy1 = _union(workspace, sheet, drawing)
    pad = 10.0
    header = 13.0
    view_x = ux0 - pad
    view_y = -uy1 - pad - header
    view_w = ux1 - ux0 + 2.0 * pad
    view_h = uy1 - uy0 + 2.0 * pad + header
    sheet_x, sheet_y, sheet_w, sheet_h = _display_rect(sheet)
    work_x, work_y, work_w, work_h = _display_rect(workspace)
    draw_x, draw_y, draw_w, draw_h = _display_rect(drawing)
    cols = max(1, int(settings.pass_cols))
    rows = max(1, int(settings.pass_rows))
    col = min(max(1, int(settings.pass_col)), cols)
    row = min(max(1, int(settings.pass_row)), rows)
    cell_w = sheet_w / cols
    cell_h = sheet_h / rows
    selected_x = sheet_x + (col - 1) * cell_w
    selected_y = sheet_y + (row - 1) * cell_h
    split_lines = [
        f'<line x1="{sheet_x + cell_w * index:.4f}" y1="{sheet_y:.4f}" x2="{sheet_x + cell_w * index:.4f}" y2="{sheet_y + sheet_h:.4f}" />'
        for index in range(1, cols)
    ] + [
        f'<line x1="{sheet_x:.4f}" y1="{sheet_y + cell_h * index:.4f}" x2="{sheet_x + sheet_w:.4f}" y2="{sheet_y + cell_h * index:.4f}" />'
        for index in range(1, rows)
    ]
    paths = "\n".join(f'<path d="{_path_d(polyline)}" />' for polyline in polylines if len(polyline) >= 2)
    title = html.escape(
        f"{Path(settings.input_path or 'чертёж').name} • {settings.sheet_format.upper()} • "
        f"проход {col}/{cols} × {row}/{rows} • поворот {int(settings.output_rotation_deg) % 360}°"
    )
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{view_w:.3f}mm" height="{view_h:.3f}mm" viewBox="{view_x:.3f} {view_y:.3f} {view_w:.3f} {view_h:.3f}">
  <rect x="{view_x:.3f}" y="{view_y:.3f}" width="{view_w:.3f}" height="{view_h:.3f}" fill="#eef2f7" />
  <text x="{view_x + 4:.3f}" y="{view_y + 7:.3f}" fill="#102a43" font-family="Segoe UI, Arial" font-size="4.2">{title}</text>
  <g fill="none" vector-effect="non-scaling-stroke">
    <rect x="{sheet_x:.4f}" y="{sheet_y:.4f}" width="{sheet_w:.4f}" height="{sheet_h:.4f}" fill="#fff" stroke="#2563eb" stroke-width="0.7" />
    <rect x="{selected_x:.4f}" y="{selected_y:.4f}" width="{cell_w:.4f}" height="{cell_h:.4f}" fill="#dbeafe" fill-opacity="0.42" stroke="#1d4ed8" stroke-width="0.45" />
    <g stroke="#2563eb" stroke-width="0.35" stroke-dasharray="3 2">{''.join(split_lines)}</g>
    <rect x="{work_x:.4f}" y="{work_y:.4f}" width="{work_w:.4f}" height="{work_h:.4f}" stroke="#f97316" stroke-width="0.5" stroke-dasharray="4 3" />
    <rect x="{draw_x:.4f}" y="{draw_y:.4f}" width="{draw_w:.4f}" height="{draw_h:.4f}" stroke="#16a34a" stroke-width="0.35" />
    <g stroke="#111827" stroke-width="0.24" stroke-linecap="round" stroke-linejoin="round">{paths}</g>
  </g>
</svg>'''
    svg_path.write_text(svg, encoding="utf-8")
    embedded = svg.split("\n", 1)[1]
    html_path.write_text(
        f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{title}</title>
<style>html,body{{margin:0;height:100%;overflow:hidden;background:#111827}}svg{{width:100vw;height:100vh;cursor:grab}}svg.dragging{{cursor:grabbing}}</style></head>
<body>{embedded}<script>
const svg=document.querySelector('svg'),initial=svg.getAttribute('viewBox').split(/\\s+/).map(Number);let view=initial.slice(),drag=false,last=null;
const apply=()=>svg.setAttribute('viewBox',view.join(' '));const point=e=>{{const r=svg.getBoundingClientRect();return[view[0]+(e.clientX-r.left)/r.width*view[2],view[1]+(e.clientY-r.top)/r.height*view[3]]}};
svg.addEventListener('wheel',e=>{{e.preventDefault();const p=point(e),k=e.deltaY>0?1.15:.87;view[0]=p[0]-(p[0]-view[0])*k;view[1]=p[1]-(p[1]-view[1])*k;view[2]*=k;view[3]*=k;apply()}},{{passive:false}});
svg.addEventListener('pointerdown',e=>{{drag=true;last=point(e);svg.classList.add('dragging');svg.setPointerCapture(e.pointerId)}});svg.addEventListener('pointermove',e=>{{if(!drag)return;const p=point(e);view[0]+=last[0]-p[0];view[1]+=last[1]-p[1];apply();last=point(e)}});svg.addEventListener('pointerup',()=>{{drag=false;svg.classList.remove('dragging')}});svg.addEventListener('dblclick',()=>{{view=initial.slice();apply()}});
</script></body></html>''',
        encoding="utf-8",
    )
    svg_for_pdf = svg.replace(
        f'width="{view_w:.3f}mm" height="{view_h:.3f}mm"',
        f'width="{view_w:.3f}" height="{view_h:.3f}"',
        1,
    )
    svg_doc = fitz.open(stream=svg_for_pdf.encode("utf-8"), filetype="svg")
    pdf_bytes = svg_doc.convert_to_pdf()
    svg_doc.close()
    source_pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    pdf_doc = fitz.open()
    target_page = pdf_doc.new_page(width=view_w * 72.0 / 25.4, height=view_h * 72.0 / 25.4)
    target_page.show_pdf_page(target_page.rect, source_pdf, 0)
    if pdf_path.exists():
        pdf_path.unlink()
    pdf_doc.save(pdf_path, garbage=4, deflate=True)
    pdf_doc.close()
    source_pdf.close()


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
    svg_path = result.nc_path.with_suffix(".preview.svg")
    html_path = result.nc_path.with_suffix(".preview.html")
    pdf_path = result.nc_path.with_suffix(".preview.pdf")
    try:
        lines = result.nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        z_up, z_down = _detect_pen_z(lines, preview_settings)
        polylines = _gcode_to_polylines(lines, z_up=z_up, z_down=z_down)
        polylines = _paper_orientation_polylines(polylines, preview_settings)
        _write_preview_files(polylines, svg_path=svg_path, html_path=html_path, pdf_path=pdf_path, settings=preview_settings)
        result.preview_svg_path = svg_path
        result.preview_pdf_path = pdf_path
        result.message = f"Предпросмотр итогового G-code готов: {pdf_path}"
        _open_preview(pdf_path)
    except Exception as exc:
        result.message = f"G-code подготовлен: {result.nc_path}"
        result.warnings.append(f"Не удалось сформировать PDF предпросмотра: {exc}")
    return result
