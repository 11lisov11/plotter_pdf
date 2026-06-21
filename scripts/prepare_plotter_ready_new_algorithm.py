from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import gost_text_replace_experiment as gost
from scripts import gost_lff_text_experiment as lff_text
from scripts import prepare_folder1_packages as prep
from scripts import render_gcode_preview
from scripts import stitch_gcode_polylines

backend = prep.backend

CG_DIR = "".join(
    chr(c)
    for c in (
        0x041A,
        0x043E,
        0x043C,
        0x043F,
        0x044C,
        0x044E,
        0x0442,
        0x0435,
        0x0440,
        0x043D,
        0x0430,
        0x044F,
        0x20,
        0x0433,
        0x0440,
        0x0430,
        0x0444,
        0x0438,
        0x043A,
        0x0430,
    )
)
VARIANT9_DIR = "9 " + "".join(chr(c) for c in (0x0432, 0x0430, 0x0440, 0x0438, 0x0430, 0x043D, 0x0442))
DEFAULT_VARIANT_ROOT = ROOT / CG_DIR / VARIANT9_DIR

LFF_FONT_PATH = ROOT / "assets" / "single_line_fonts" / "lc_opengost-ar.lff"
LFF_FILL = 0.86
LFF_STAMP_FILL = 0.62
LFF_SHEAR = 0.24

Point = tuple[float, float]
Polyline = list[Point]

A3_FIT_RE = re.compile(r"Fit to work area: scale=([-0-9.]+), translate=\(([-0-9.]+),([-0-9.]+)\)")
A3_PASS_RE = re.compile(r"Pass window: .* shift=\(([-0-9.]+),([-0-9.]+)\)")
A3_POST_TRANSLATE_RE = re.compile(r"translating geometry by \(([-0-9.]+),([-0-9.]+)\) mm")

SERVICE_TEXT_PARTS = (
    "KOMPAS",
    "\u041a\u041e\u041c\u041f\u0410\u0421",
    "\u041d\u0435 \u0434\u043b\u044f",
    "\u043a\u043e\u043c\u043c\u0435\u0440\u0447",
    "\u0424\u043e\u0440\u043c\u0430\u0442",
    "\u0418\u043d\u0432.",
    "\u0412\u0437\u0430\u043c.",
    "\u0421\u043f\u0440\u0430\u0432.",
    "\u041f\u0435\u0440\u0432.",
    "\u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043b",
)


@dataclass(frozen=True)
class Settings:
    drawing_mode: str = "computer_graphics"
    x_compensation_mm: float = 0.0
    a3_pass_01_x_offset_mm: float = 0.0
    a3_pass_01_y_offset_mm: float = 0.0
    a3_pass_02_x_offset_mm: float = 0.0
    a3_pass_02_y_offset_mm: float = 0.0
    stitch_eps_mm: float = 0.08
    feed_travel: float = 15000.0
    feed_draw: float = 2200.0
    z_down: float = 11.9
    work_width: float = 180.0
    work_height: float = 280.0
    work_min_y: float = -285.0
    paper_transform: str = "plotter_y_mirror"
    keep_debug_artifacts: bool = False


@dataclass(frozen=True)
class Transform:
    scale: float
    translate_x: float
    translate_y: float
    shift_x: float = 0.0
    shift_y: float = 0.0
    rotate_180: bool = False
    post_translate_x: float = 0.0
    post_translate_y: float = 0.0


@dataclass(frozen=True)
class SourceBuild:
    source_pdf: Path
    page_w_mm: float
    page_h_mm: float
    polylines: list[Polyline]
    geometry_polylines: int
    text_polylines: int
    text_lines_found: int
    text_lines_rendered: int
    text_lines_skipped: int
    missing_chars: list[str]
    logs: list[str]
    artifacts: dict[str, str]
    preserve_source_frame: bool = False
    dense_onepass_source: bool = False



def _normalize_drawing_mode(value: str | None, variant_root: Path | None = None) -> str:
    raw = str(value or "auto").strip().casefold().replace("-", "_")
    if raw in {"computer", "computer_graphics", "cg", "компьютерная_графика"}:
        return "computer_graphics"
    if raw in {"descriptive", "descriptive_geometry", "nachert", "начерт", "начертательная_геометрия"}:
        return "descriptive_geometry"
    if raw not in {"", "auto"}:
        raise ValueError(f"Unknown drawing mode: {value}")
    if variant_root is not None and "начерт" in str(variant_root).casefold():
        return "descriptive_geometry"
    return "computer_graphics"


def _is_computer_graphics_mode(settings: Settings) -> bool:
    return str(settings.drawing_mode or "computer_graphics") == "computer_graphics"


def _is_descriptive_geometry_mode(settings: Settings) -> bool:
    return str(settings.drawing_mode or "computer_graphics") == "descriptive_geometry"

def _dist(a: Point, b: Point) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _draw_len(polylines: list[Polyline]) -> float:
    return sum(_dist(poly[i], poly[i - 1]) for poly in polylines for i in range(1, len(poly)))


def _bounds(polylines: list[Polyline]) -> tuple[float, float, float, float]:
    points = [pt for poly in polylines for pt in poly]
    if not points:
        return 0.0, 0.0, 0.0, 0.0
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _segment_key(a: Point, b: Point, *, precision: int = 2) -> tuple[Point, Point]:
    pa = (round(float(a[0]), precision), round(float(a[1]), precision))
    pb = (round(float(b[0]), precision), round(float(b[1]), precision))
    return tuple(sorted((pa, pb)))  # type: ignore[return-value]


def _dedup_segments(polylines: list[Polyline], *, precision: int = 2) -> list[Polyline]:
    seen: set[tuple[Point, Point]] = set()
    out: list[Polyline] = []
    for poly in polylines:
        current: Polyline = []
        for idx in range(1, len(poly)):
            a = poly[idx - 1]
            b = poly[idx]
            if _dist(a, b) <= 0.005:
                continue
            key = _segment_key(a, b, precision=precision)
            if key in seen:
                if len(current) >= 2:
                    out.append(current)
                current = []
                continue
            seen.add(key)
            if not current:
                current = [a, b]
            elif _dist(current[-1], a) > 0.005:
                if len(current) >= 2:
                    out.append(current)
                current = [a, b]
            else:
                current.append(b)
        if len(current) >= 2:
            out.append(current)
    return out


def _segment_axis_for_overlap(a: Point, b: Point, *, min_len: float = 0.30) -> tuple[float, float, float, float, float, float, float] | None:
    x0, y0 = float(a[0]), float(a[1])
    x1, y1 = float(b[0]), float(b[1])
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length < min_len:
        return None
    ux = dx / length
    uy = dy / length
    if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0.0):
        ux = -ux
        uy = -uy
    nx = -uy
    ny = ux
    offset = x0 * nx + y0 * ny
    t0 = x0 * ux + y0 * uy
    t1 = x1 * ux + y1 * uy
    if t0 > t1:
        t0, t1 = t1, t0
    return ux, uy, nx, ny, offset, t0, t1


def _segments_overlap_for_plotter(a: Point, b: Point, c: Point, d: Point) -> bool:
    first = _segment_axis_for_overlap(a, b)
    second = _segment_axis_for_overlap(c, d)
    if first is None or second is None:
        return False
    ux, uy, _nx, _ny, _offset, _t0, _t1 = first
    oux, ouy, onx, ony, other_offset, other_t0, other_t1 = second
    dot = max(-1.0, min(1.0, ux * oux + uy * ouy))
    if math.acos(abs(dot)) > math.radians(1.0):
        return False
    cur_t0 = float(a[0]) * oux + float(a[1]) * ouy
    cur_t1 = float(b[0]) * oux + float(b[1]) * ouy
    if cur_t0 > cur_t1:
        cur_t0, cur_t1 = cur_t1, cur_t0
    overlap_len = min(cur_t1, other_t1) - max(cur_t0, other_t0)
    if overlap_len <= 0.0:
        return False
    current_len = max(1e-9, cur_t1 - cur_t0)
    other_len = max(1e-9, other_t1 - other_t0)
    if overlap_len < 0.40 or overlap_len / min(current_len, other_len) < 0.90:
        return False
    overlap_mid_t = (max(cur_t0, other_t0) + min(cur_t1, other_t1)) * 0.5
    other_mid_x = oux * overlap_mid_t + onx * other_offset
    other_mid_y = ouy * overlap_mid_t + ony * other_offset
    current_mid_t = (other_mid_x - float(a[0])) * ux + (other_mid_y - float(a[1])) * uy
    current_mid_x = float(a[0]) + ux * current_mid_t
    current_mid_y = float(a[1]) + uy * current_mid_t
    return math.hypot(current_mid_x - other_mid_x, current_mid_y - other_mid_y) <= 0.12


def _split_redundant_backtrack_segments(polylines: list[Polyline], logger=None) -> list[Polyline]:
    out: list[Polyline] = []
    dropped = 0
    for poly in polylines:
        if len(poly) < 3:
            if len(poly) >= 2:
                out.append(poly)
            continue
        current: Polyline = [poly[0], poly[1]]
        prev_a = poly[0]
        prev_b = poly[1]
        for point in poly[2:]:
            if _segments_overlap_for_plotter(prev_a, prev_b, prev_b, point):
                if len(current) >= 2:
                    out.append(current)
                current = [point]
                dropped += 1
                prev_a = prev_b
                prev_b = point
                continue
            if len(current) == 1:
                current.append(point)
            else:
                current.append(point)
            prev_a = prev_b
            prev_b = point
        if len(current) >= 2:
            out.append(current)
    if dropped and logger:
        logger(f"Backtrack overlap cleanup: split {dropped} redundant reverse draw segment(s) into pen-up travel.")
    return out


def _translate(polylines: list[Polyline], dx: float, dy: float = 0.0) -> list[Polyline]:
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return polylines
    return [[(float(x) + float(dx), float(y) + float(dy)) for x, y in poly] for poly in polylines]


def _safe_trailer_text() -> str:
    return "\n".join(
        [
            "; new-source-algorithm safe trailer",
            "G0 Z3.500 F5000",
            "G0 X0.000 Y0.000 F5000",
            "M5",
            "$1=0",
            "",
        ]
    )


def _write_new_gcode(path: Path, polylines: list[Polyline], settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stitch_gcode_polylines.write_gcode(
        path,
        polylines,
        feed_travel=settings.feed_travel,
        feed_draw=settings.feed_draw,
        z_down=settings.z_down,
    )
    payload = path.read_text(encoding="utf-8")
    payload = (
        "; new-algorithm-v2: source PDF -> geometry_without_pdf_text -> OpenGOST_LFF_singleline_text -> pass transform\n"
        "; old page_01/pass_*.nc are not used as source\n"
        f"; text_font={LFF_FONT_PATH}\n"
        f"; x_compensation_mm={settings.x_compensation_mm:.3f}\n"
        + payload.rstrip()
        + "\n"
        + _safe_trailer_text()
    )
    path.write_text(payload, encoding="utf-8", newline="\n")
    path.with_suffix(".gcode").write_text(payload, encoding="utf-8", newline="\n")


def _load_report(pack: Path) -> dict[str, Any]:
    report_path = pack / "report.json"
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def _source_pdf_for_pack(pack: Path, report: dict[str, Any]) -> Path | None:
    raw = str(report.get("source_pdf", "") or "").strip()
    if raw:
        path = Path(raw)
        if path.exists():
            return path
    candidate = pack.parent / f"{pack.name.removesuffix('_pack')}.pdf"
    if candidate.exists():
        return candidate
    return None


def _service_regions(source_pdf: Path) -> list[tuple[float, float, float, float]]:
    try:
        regions = prep._kompas_service_regions_from_pdf(source_pdf, page_index=0)
    except Exception:
        return []
    out: list[tuple[float, float, float, float]] = []
    for region in regions or []:
        try:
            x0, y0, x1, y1 = [float(v) for v in region[:4]]
        except Exception:
            continue
        out.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return out


def _point_in_box(point: Point, box: tuple[float, float, float, float], *, pad: float = 0.0) -> bool:
    x, y = point
    x0, y0, x1, y1 = box
    return (x0 - pad) <= x <= (x1 + pad) and (y0 - pad) <= y <= (y1 + pad)


def _repair_pdf_text_mojibake(text: object) -> str:
    raw = str(text or "")
    if not raw:
        return raw
    try:
        repaired = raw.encode("cp1251").decode("utf-8")
    except UnicodeError:
        return raw
    if "�" in repaired:
        return raw
    return repaired


def _repair_text_line(line: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(line)
    repaired["text"] = _repair_pdf_text_mojibake(repaired.get("text", ""))
    return repaired


def _is_service_text(line: dict[str, Any], service_regions: list[tuple[float, float, float, float]]) -> bool:
    text = " ".join(str(line.get("text", "") or "").strip().split())
    if not text:
        return True
    folded = text.casefold()
    if any(part.casefold() in folded for part in SERVICE_TEXT_PARTS):
        return True
    bbox = [float(v) for v in line.get("bbox_mm", (0, 0, 0, 0))[:4]]
    if len(bbox) != 4:
        return False
    cx = (bbox[0] + bbox[2]) * 0.5
    cy = (bbox[1] + bbox[3]) * 0.5
    return any(_point_in_box((cx, cy), region, pad=0.5) for region in service_regions)


def _text_lines_for_source(source_pdf: Path) -> tuple[list[dict[str, Any]], int, int]:
    raw_lines = gost._extract_pdf_text_lines(source_pdf)
    service_regions = _service_regions(source_pdf)
    accepted: list[dict[str, Any]] = []
    skipped = 0
    for raw_line in raw_lines:
        line = _repair_text_line(raw_line)
        if _is_service_text(line, service_regions):
            skipped += 1
            continue
        accepted.append(line)
    return accepted, len(raw_lines), skipped








def _install_stamp_role_cell_overrides() -> None:
    gost.STAMP_ROLE_CELL_BBOXES_MM.update(
        {
            "Разраб.": [20.45, 262.38, 37.40, 267.76],
            "Пров.": [20.45, 267.38, 37.40, 272.76],
            "Т.контр.": [20.45, 272.38, 37.40, 277.76],
            "Н.контр.": [20.45, 282.38, 37.40, 287.76],
            "Утв.": [20.45, 287.38, 37.40, 292.30],
        }
    )


def _unit(vector: Point) -> Point:
    x, y = vector
    length = math.hypot(float(x), float(y))
    if length < 1e-9:
        return 1.0, 0.0
    return float(x) / length, float(y) / length


def _project(point: Point, axis: Point) -> float:
    return float(point[0]) * float(axis[0]) + float(point[1]) * float(axis[1])


def _line_to_ttf_centerline_polys(
    line: dict[str, Any],
    *,
    ttf_path: Path,
    fit_text,
    render_line,
    logger,
) -> list[Polyline]:
    text = str(line.get("text", "") or "").strip()
    bbox = [float(v) for v in line.get("bbox_mm", (0, 0, 0, 0))[:4]]
    if not text or len(bbox) != 4:
        return []
    x0, y0, x1, y1 = bbox
    dx, dy = (line.get("dir") or [1.0, 0.0])[:2]
    u = _unit((float(dx), float(dy)))
    v = (-u[1], u[0])
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ts = [_project(point, u) for point in corners]
    ss = [_project(point, v) for point in corners]
    t_min, t_max = min(ts), max(ts)
    s_min, s_max = min(ss), max(ss)
    target_w = max(1.0, t_max - t_min)
    target_h = max(1.0, s_max - s_min)
    fit = fit_text(text, ttf_path=ttf_path, target_w_u=target_w, target_h_u=target_h)
    if fit is None:
        return []
    font_size_u, _bbox_u = fit
    raw = render_line(
        text,
        ttf_path=ttf_path,
        font_size=float(font_size_u),
        baseline_x=0.0,
        baseline_y=0.0,
        logger=logger,
    )
    raw_polys = [[(float(x), float(y)) for x, y in poly] for poly in list(raw or []) if len(poly) >= 2]
    if not raw_polys:
        return []
    ax0, ay0, ax1, ay1 = _bounds(raw_polys)
    actual_w = max(1e-6, ax1 - ax0)
    actual_h = max(1e-6, ay1 - ay0)
    fill = float(line.get("text_box_fill", 0.94) or 0.94)
    if str(line.get("text", "")) in gost.STAMP_ROLE_LABELS:
        fill = min(fill, float(gost.STAMP_ROLE_TEXT_FILL))
    fill = max(0.35, min(fill, 1.0))
    scale = min((target_w * 0.98) / actual_w, (target_h * fill) / actual_h, 1.0)
    rendered_w = actual_w * scale
    rendered_h = actual_h * scale
    local_x0 = (target_w - rendered_w) * 0.5
    local_y0 = (target_h - rendered_h) * 0.5
    out: list[Polyline] = []
    for poly in raw_polys:
        mapped: Polyline = []
        for x, y in poly:
            local_t = t_min + local_x0 + (float(x) - ax0) * scale
            local_s = s_min + local_y0 + (float(y) - ay0) * scale
            mapped.append((u[0] * local_t + v[0] * local_s, u[1] * local_t + v[1] * local_s))
        if len(mapped) >= 2:
            out.append(mapped)
    return out


def _make_ttf_centerline_text_strokes(text_lines: list[dict[str, Any]], logger) -> tuple[list[Polyline], list[dict[str, Any]], set[str]]:
    _install_stamp_role_cell_overrides()
    resolve_ttf = getattr(backend, "_resolve_handwriting_ttf_path", lambda _font: None)
    ttf_path = (
        resolve_ttf("GOST_AU.ttf")
        or resolve_ttf("GOST_A.TTF")
        or resolve_ttf("GOST_BU.ttf")
        or resolve_ttf("GOST_B.TTF")
        or gost.GOST_AU_FONT
    )
    ttf_path = Path(ttf_path)
    fit_text = getattr(backend, "_fit_formula_ocr_font_size_units", None)
    render_line = getattr(backend, "_render_singleline_text_line_ttf", None)
    if fit_text is None or render_line is None or not ttf_path.exists():
        return [], [], {"TTF_BACKEND_UNAVAILABLE"}
    prev_ttf_backend = str(getattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "autotrace3"))
    strokes: list[Polyline] = []
    accepted: list[dict[str, Any]] = []
    missing: set[str] = set()
    try:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "skeleton")
        for source_line in text_lines:
            for line in gost._stamp_centered_lines(source_line):
                line_polys = _line_to_ttf_centerline_polys(
                    line,
                    ttf_path=ttf_path,
                    fit_text=fit_text,
                    render_line=render_line,
                    logger=logger,
                )
                if not line_polys:
                    missing.add(str(line.get("text", "")))
                    continue
                strokes.extend(line_polys)
                accepted.append({"text": line.get("text", ""), "bbox_mm": line.get("bbox_mm"), "dir": line.get("dir"), "font": str(ttf_path)})
    finally:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", prev_ttf_backend)
    return strokes, accepted, missing


LFF_STAMP_WORDS = {
    "изм.",
    "лист",
    "листов",
    "№докум.",
    "подп.",
    "дата",
    "лит.",
    "масса",
    "масштаб",
    "разраб.",
    "пров.",
    "т.контр.",
    "н.контр.",
    "утв.",
}


def _lff_line_text(line: dict[str, Any]) -> str:
    text = str(line.get("text", "") or "").strip()
    return re.sub(r"^[□▯◻▫\s]+(?=\d)", "", text)


DIMENSION_TEXT_ALLOWED_WORDS = {
    "r",
    "р",
    "m",
    "x",
    "х",
    "ф",
    "lh",
    "rh",
    "отв",
    "отв.",
    "фаска",
    "фаски",
}

TITLE_BLOCK_TEXT_MARKERS = (
    "изм",
    "лист",
    "листов",
    "докум",
    "подп",
    "дата",
    "лит",
    "масса",
    "масштаб",
    "разраб",
    "пров",
    "контр",
    "утв",
    "пгупс",
    "сталь",
    "гост",
)


def _line_font_size_pt(line: dict[str, Any]) -> float | None:
    for key in ("font_size_pt_median", "font_size_pt", "size"):
        value = line.get(key)
        try:
            size = float(value)
        except (TypeError, ValueError):
            continue
        if 1.0 <= size <= 80.0:
            return size
    return None


def _normalized_text_for_rules(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").casefold().replace(",", "."))


def _looks_like_dimension_annotation(line: dict[str, Any]) -> bool:
    text = _lff_line_text(line)
    compact = _normalized_text_for_rules(text)
    if not compact or not any(ch.isdigit() for ch in compact):
        return False
    if len(compact) > 18:
        return False
    if any(marker in compact for marker in TITLE_BLOCK_TEXT_MARKERS):
        return False
    words = re.findall(r"[a-zа-яё]+", compact, flags=re.IGNORECASE)
    for word in words:
        if word.casefold() not in DIMENSION_TEXT_ALLOWED_WORDS:
            return False
    allowed = set("0123456789.,+-°'\"/()[]")
    allowed.update("rRрРmMxXhHlLнНоОтТвВфФØø⌀φΦ×хХ")
    return all((ch in allowed) or ch.isspace() for ch in text)


def _looks_like_title_block_zone(line: dict[str, Any], page_w_mm: float, page_h_mm: float) -> bool:
    text = _normalized_text_for_rules(_lff_line_text(line))
    if any(marker in text for marker in TITLE_BLOCK_TEXT_MARKERS):
        return True
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return False
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    page_w = max(1.0, float(page_w_mm))
    page_h = max(1.0, float(page_h_mm))
    if page_h >= page_w:
        if cy >= page_h - 70.0:
            return True
        if cx <= 24.0 and cy >= 25.0:
            return True
    else:
        if cy >= page_h - 72.0 and cx >= page_w - 205.0:
            return True
        if cy <= 48.0 and cx <= 135.0:
            return True
    return False


def _dimension_text_box_height_override_mm(
    line: dict[str, Any],
    page_w_mm: float,
    page_h_mm: float,
    *,
    current_box_height_mm: float,
    fill: float,
) -> float | None:
    if not _looks_like_dimension_annotation(line):
        return None
    if _looks_like_title_block_zone(line, page_w_mm, page_h_mm):
        return None
    font_size_pt = _line_font_size_pt(line)
    if font_size_pt is not None:
        target_draw_height = font_size_pt * 25.4 / 72.0 * 1.18
    else:
        target_draw_height = current_box_height_mm * float(fill)
    target_draw_height = max(3.2, min(6.0, float(target_draw_height)))
    target_box_height = target_draw_height / max(0.35, float(fill))
    current_draw_height = current_box_height_mm * float(fill)
    if current_draw_height < target_draw_height * 0.88 or current_draw_height > target_draw_height * 1.12:
        return target_box_height
    return None


def _line_bbox_mm(line: dict[str, Any]) -> tuple[float, float, float, float] | None:
    raw = line.get("bbox_mm") or line.get("bbox")
    if raw is None:
        return None
    try:
        values = [float(v) for v in list(raw)[:4]]
    except Exception:
        return None
    if len(values) != 4:
        return None
    x0, y0, x1, y1 = values
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _looks_like_lff_stamp_cell(line: dict[str, Any], page_w_mm: float, page_h_mm: float) -> bool:
    text = _lff_line_text(line).casefold().replace(" ", "")
    if text in LFF_STAMP_WORDS:
        return True
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return False
    x0, y0, x1, y1 = bbox
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    if x0 < float(page_w_mm) * 0.46 and y0 > float(page_h_mm) * 0.55:
        return True
    return height < 8.0 and width < 80.0


HorizontalRule = tuple[float, float, float]


def _horizontal_table_rules_from_polylines(polylines: list[Polyline]) -> list[HorizontalRule]:
    rules: list[HorizontalRule] = []
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        for a, b in zip(polyline, polyline[1:]):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            dx = abs(bx - ax)
            dy = abs(by - ay)
            if dx < 4.5 or dy > 0.12:
                continue
            rules.append(((ay + by) * 0.5, min(ax, bx), max(ax, bx)))
    return rules


def _dedupe_rule_ys(values: list[float], *, eps: float = 0.22) -> list[float]:
    if not values:
        return []
    out: list[float] = []
    cluster: list[float] = []
    for value in sorted(values):
        if not cluster or abs(value - cluster[-1]) <= eps:
            cluster.append(value)
            continue
        out.append(sum(cluster) / len(cluster))
        cluster = [value]
    if cluster:
        out.append(sum(cluster) / len(cluster))
    return out


def _horizontal_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(float(a1), float(b1)) - max(float(a0), float(b0)))


def _table_row_band_for_line(line: dict[str, Any], rules: list[HorizontalRule]) -> tuple[float, float] | None:
    if not rules:
        return None
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return None
    text = _lff_line_text(line)
    if not text:
        return None
    x0, y0, x1, y1 = bbox
    width = max(0.1, x1 - x0)
    height = max(0.1, y1 - y0)
    if height > 14.0:
        return None
    u = _unit(tuple(line.get("dir", (1.0, 0.0))))  # type: ignore[arg-type]
    if abs(u[1]) > 0.22 or abs(u[0]) < 0.72:
        return None
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    relevant_ys: list[float] = []
    for rule_y, rule_x0, rule_x1 in rules:
        rule_width = float(rule_x1) - float(rule_x0)
        if rule_width < 4.5:
            continue
        overlap = _horizontal_overlap(x0, x1, rule_x0 - 0.8, rule_x1 + 0.8)
        contains_center = (float(rule_x0) - 1.5) <= cx <= (float(rule_x1) + 1.5)
        if not contains_center and overlap < min(width * 0.35, 2.5):
            continue
        relevant_ys.append(float(rule_y))
    ys = _dedupe_rule_ys(relevant_ys)
    if len(ys) < 3:
        return None
    upper_candidates = [value for value in ys if value < cy - 0.2]
    lower_candidates = [value for value in ys if value > cy + 0.2]
    if not upper_candidates or not lower_candidates:
        return None
    upper = max(upper_candidates)
    lower = min(lower_candidates)
    gap = lower - upper
    if gap < 3.2 or gap > 18.5:
        return None
    nearby = [value for value in ys if upper - gap * 3.0 <= value <= lower + gap * 3.0]
    if len(nearby) < 3:
        return None
    return upper, lower


def _center_text_line_in_table_row(line: dict[str, Any], rules: list[HorizontalRule]) -> dict[str, Any]:
    band = _table_row_band_for_line(line, rules)
    if band is None:
        return line
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return line
    x0, y0, x1, y1 = bbox
    upper, lower = band
    row_height = lower - upper
    current_height = max(0.1, y1 - y0)
    target_height = min(current_height, max(0.1, row_height * 0.86))
    row_center = (upper + lower) * 0.5
    new_y0 = row_center - target_height * 0.5
    new_y1 = row_center + target_height * 0.5
    if abs(new_y0 - y0) <= 0.05 and abs(new_y1 - y1) <= 0.05:
        return line
    patched = dict(line)
    patched["bbox_mm"] = [round(float(x0), 4), round(float(new_y0), 4), round(float(x1), 4), round(float(new_y1), 4)]
    patched["table_row_centered"] = {
        "row_band_mm": [round(float(upper), 4), round(float(lower), 4)],
        "dy_mm": round(float(((new_y0 + new_y1) - (y0 + y1)) * 0.5), 4),
    }
    return patched




def _is_new_algorithm_specification_source(source_pdf: Path) -> bool:
    try:
        text = str(source_pdf.parent if source_pdf.name.casefold() == "source.pdf" else source_pdf).casefold()
    except Exception:
        return False
    normalized = re.sub(r"[\\/_.\-]+", " ", text)
    return bool(re.search(r"(^|\s)сп(\s|$)", normalized) or "специфик" in normalized)


def _looks_like_specification_table_geometry(polylines: list[Polyline]) -> bool:
    """Detect a specification sheet by its table grid, not by a pack name only."""

    horizontal: list[float] = []
    vertical: list[float] = []
    axis_segments = 0
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        xs = [point[0] for point in polyline]
        ys = [point[1] for point in polyline]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max_x - min_x
        height = max_y - min_y
        if width >= 18.0 and height <= 0.55:
            horizontal.append((min_y + max_y) * 0.5)
            axis_segments += 1
        elif height >= 18.0 and width <= 0.55:
            vertical.append((min_x + max_x) * 0.5)
            axis_segments += 1

    def cluster_count(values: list[float], tolerance: float = 0.9) -> int:
        if not values:
            return 0
        clusters = 1
        current = sorted(values)[0]
        for value in sorted(values)[1:]:
            if abs(value - current) > tolerance:
                clusters += 1
                current = value
            else:
                current = (current + value) * 0.5
        return clusters

    horizontal_rows = cluster_count(horizontal)
    vertical_columns = cluster_count(vertical)
    return axis_segments >= 30 and horizontal_rows >= 14 and vertical_columns >= 5


def _is_new_algorithm_specification(source_pdf: Path, polylines: list[Polyline]) -> bool:
    return _is_new_algorithm_specification_source(source_pdf) or _looks_like_specification_table_geometry(polylines)

def _merge_grid_intervals(intervals: list[tuple[float, float]], *, gap_eps: float = 0.55) -> list[tuple[float, float]]:
    if not intervals:
        return []
    merged: list[list[float]] = []
    for start, end in sorted((min(float(a), float(b)), max(float(a), float(b))) for a, b in intervals):
        if end - start <= 0.35:
            continue
        if not merged or start > merged[-1][1] + gap_eps:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(float(start), float(end)) for start, end in merged]


def _snap_axis_grid_segments(
    segments: list[tuple[float, float, float]],
    *,
    coord_eps: float,
    gap_eps: float,
    horizontal: bool,
) -> list[Polyline]:
    if not segments:
        return []
    clusters: list[dict[str, Any]] = []
    for coord, span0, span1 in sorted(segments, key=lambda item: item[0]):
        coord = float(coord)
        span0 = float(span0)
        span1 = float(span1)
        weight = max(0.1, abs(span1 - span0))
        if not clusters or abs(coord - float(clusters[-1]["coord"])) > coord_eps:
            clusters.append({"coord": coord, "weight": weight, "intervals": [(span0, span1)]})
            continue
        cluster = clusters[-1]
        old_weight = float(cluster["weight"])
        new_weight = old_weight + weight
        cluster["coord"] = (float(cluster["coord"]) * old_weight + coord * weight) / new_weight
        cluster["weight"] = new_weight
        cluster["intervals"].append((span0, span1))

    out: list[Polyline] = []
    for cluster in clusters:
        coord = float(cluster["coord"])
        for start, end in _merge_grid_intervals(list(cluster["intervals"]), gap_eps=gap_eps):
            if horizontal:
                out.append([(start, coord), (end, coord)])
            else:
                out.append([(coord, start), (coord, end)])
    return out


def _snap_specification_table_grid_polylines(polylines: list[Polyline], logs: list[str]) -> list[Polyline]:
    """Normalize KOMPAS specification table grid into single straight centerlines.

    KOMPAS/PDF exports often expose table strokes as tiny outline fragments or
    nearly-parallel duplicate edges.  If those are sent to the plotter directly,
    the specification grid looks ragged.  This pass is intentionally limited to
    almost-horizontal/almost-vertical segments and leaves text/diagonal geometry
    alone.
    """
    horizontal_segments: list[tuple[float, float, float]] = []
    vertical_segments: list[tuple[float, float, float]] = []
    kept: list[Polyline] = []
    classified = 0

    for polyline in polylines:
        if len(polyline) < 2:
            continue
        for a, b in zip(polyline, polyline[1:]):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            dx = bx - ax
            dy = by - ay
            adx = abs(dx)
            ady = abs(dy)
            if adx <= 0.35 and ady <= 0.35:
                continue
            if adx >= 1.2 and ady <= max(0.24, adx * 0.006):
                horizontal_segments.append(((ay + by) * 0.5, min(ax, bx), max(ax, bx)))
                classified += 1
                continue
            if ady >= 1.2 and adx <= max(0.24, ady * 0.006):
                vertical_segments.append(((ax + bx) * 0.5, min(ay, by), max(ay, by)))
                classified += 1
                continue
            kept.append([(ax, ay), (bx, by)])

    snapped_horizontal = _snap_axis_grid_segments(
        horizontal_segments,
        coord_eps=0.42,
        gap_eps=0.62,
        horizontal=True,
    )
    snapped_vertical = _snap_axis_grid_segments(
        vertical_segments,
        coord_eps=0.42,
        gap_eps=0.62,
        horizontal=False,
    )
    snapped = [*kept, *snapped_horizontal, *snapped_vertical]
    logs.append(
        "Specification grid snap: "
        f"classified_segments={classified}; "
        f"horizontal={len(horizontal_segments)}->{len(snapped_horizontal)}; "
        f"vertical={len(vertical_segments)}->{len(snapped_vertical)}; "
        f"kept_non_axis={len(kept)}; total={len(polylines)}->{len(snapped)}."
    )
    return snapped

def _line_to_lff_opengost_polys(
    font: lff_text.LffFont,
    line: dict[str, Any],
    *,
    page_w_mm: float,
    page_h_mm: float,
    missing: set[str],
    normalize_dimension_text: bool = False,
) -> list[Polyline]:
    text = _lff_line_text(line)
    if not text:
        return []
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return []
    x0, y0, x1, y1 = bbox
    u = _unit(tuple(line.get("dir", (1.0, 0.0))))  # type: ignore[arg-type]
    v = (-u[1], u[0])
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    ts = [float(x) * u[0] + float(y) * u[1] for x, y in corners]
    ss = [float(x) * v[0] + float(y) * v[1] for x, y in corners]
    t_min, t_max = min(ts), max(ts)
    s_min, s_max = min(ss), max(ss)
    box_width = max(0.1, t_max - t_min)
    box_height = max(0.1, s_max - s_min)

    fill = LFF_STAMP_FILL if _looks_like_lff_stamp_cell(line, page_w_mm, page_h_mm) else LFF_FILL
    if normalize_dimension_text:
        override_height = _dimension_text_box_height_override_mm(
            line,
            page_w_mm,
            page_h_mm,
            current_box_height_mm=box_height,
            fill=fill,
        )
        if override_height is not None:
            s_mid = (s_min + s_max) * 0.5
            half = max(0.1, float(override_height) * 0.5)
            s_min, s_max = s_mid - half, s_mid + half
            box_height = max(0.1, s_max - s_min)

    font_polys, text_width = lff_text.text_to_lff_polylines(
        font,
        text,
        shear=LFF_SHEAR,
        missing=missing,
    )
    if not font_polys or text_width <= 1e-6:
        return []

    font_height = lff_text.FONT_EM_MAX - lff_text.FONT_EM_MIN
    scale = box_height * fill / font_height
    if text_width * scale > box_width * 0.98:
        scale = box_width * 0.98 / text_width
    rendered_width = text_width * scale
    rendered_height = font_height * scale
    local_x0 = (box_width - rendered_width) * 0.5
    local_y0 = (box_height - rendered_height) * 0.5
    glyph_y_values = [float(y) for font_poly in font_polys for _x, y in font_poly]
    if glyph_y_values:
        glyph_y_min = min(glyph_y_values)
        glyph_y_max = max(glyph_y_values)
        glyph_local_min = local_y0 + (lff_text.FONT_EM_MAX - glyph_y_max) * scale
        glyph_local_max = local_y0 + (lff_text.FONT_EM_MAX - glyph_y_min) * scale
        visual_center_shift = (box_height * 0.5) - ((glyph_local_min + glyph_local_max) * 0.5)
    else:
        visual_center_shift = 0.0

    result: list[Polyline] = []
    for font_poly in font_polys:
        mapped: Polyline = []
        for x, y in font_poly:
            local_x = local_x0 + float(x) * scale
            local_y = local_y0 + (lff_text.FONT_EM_MAX - float(y)) * scale + visual_center_shift
            mapped.append((u[0] * (t_min + local_x) + v[0] * (s_min + local_y), u[1] * (t_min + local_x) + v[1] * (s_min + local_y)))
        if len(mapped) >= 2:
            result.append(mapped)
    return result


def _center_a3_top_left_title_line(line: dict[str, Any]) -> dict[str, Any]:
    bbox_raw = line.get("bbox_mm")
    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) < 4:
        return line
    x0, y0, x1, y1 = [float(v) for v in bbox_raw[:4]]
    width = float(x1) - float(x0)
    height = float(y1) - float(y0)
    # A3 KOMPAS corner designation fragment: small frame near source top-left.
    # Its frame is preserved as geometry, while PDF text bbox sometimes sits too
    # high. Center only this designation text inside the preserved frame.
    if not (20.0 <= x0 <= 95.0 and x1 <= 95.5 and y0 <= 25.0 and y1 <= 25.0):
        return line
    if width < 20.0 or height < 3.0:
        return line
    frame_x0, frame_y0, frame_x1, frame_y1 = 24.0, 5.5033, 90.5090, 19.4730
    target_cx = (frame_x0 + frame_x1) * 0.5
    target_cy = (frame_y0 + frame_y1) * 0.5
    dx = target_cx - ((x0 + x1) * 0.5)
    dy = target_cy - ((y0 + y1) * 0.5)
    if abs(dx) <= 1e-6 and abs(dy) <= 1e-6:
        return line
    patched = dict(line)
    patched["bbox_mm"] = [round(x0 + dx, 3), round(y0 + dy, 3), round(x1 + dx, 3), round(y1 + dy, 3)]
    patched["a3_top_left_title_centered"] = {
        "dx_mm": round(float(dx), 3),
        "dy_mm": round(float(dy), 3),
        "frame_bbox_mm": [round(frame_x0, 3), round(frame_y0, 3), round(frame_x1, 3), round(frame_y1, 3)],
    }
    return patched


def _make_lff_opengost_text_strokes(
    text_lines: list[dict[str, Any]],
    page_w_mm: float,
    page_h_mm: float,
    logger,
    *,
    use_stamp_overrides: bool = True,
    center_a3_top_left_title: bool = False,
    normalize_dimension_text: bool = False,
    table_rules: list[HorizontalRule] | None = None,
) -> tuple[list[Polyline], list[dict[str, Any]], set[str]]:
    if use_stamp_overrides:
        _install_stamp_role_cell_overrides()
    if not LFF_FONT_PATH.exists():
        return [], [], {"LFF_FONT_UNAVAILABLE"}
    font = lff_text.load_lff_font(LFF_FONT_PATH)
    strokes: list[Polyline] = []
    accepted: list[dict[str, Any]] = []
    missing: set[str] = set()
    table_centered = 0
    for source_line in text_lines:
        if center_a3_top_left_title:
            source_line = _center_a3_top_left_title_line(source_line)
        if table_rules:
            centered_line = _center_text_line_in_table_row(source_line, table_rules)
            if centered_line is not source_line:
                table_centered += 1
            source_line = centered_line
        routed_lines = gost._stamp_centered_lines(source_line) if use_stamp_overrides else [source_line]
        for line in routed_lines:
            line_polys = _line_to_lff_opengost_polys(
                font,
                line,
                page_w_mm=page_w_mm,
                page_h_mm=page_h_mm,
                missing=missing,
                normalize_dimension_text=normalize_dimension_text,
            )
            if not line_polys:
                missing.add(str(line.get("text", "")))
                continue
            strokes.extend(line_polys)
            accepted.append({"text": line.get("text", ""), "bbox_mm": line.get("bbox_mm"), "dir": line.get("dir"), "font": str(LFF_FONT_PATH)})
            logger(
                f"OpenGOST LFF text: '{_lff_line_text(line)}' -> {len(line_polys)} stroke(s), "
                f"font={LFF_FONT_PATH.name}, fill={LFF_STAMP_FILL if _looks_like_lff_stamp_cell(line, page_w_mm, page_h_mm) else LFF_FILL:.2f}, shear={LFF_SHEAR:.2f}"
            )
            if line.get("a3_top_left_title_centered"):
                meta = line.get("a3_top_left_title_centered") or {}
                logger(
                    "A3 top-left title text centered: "
                    f"dx={float(meta.get('dx_mm', 0.0)):.3f} mm; "
                    f"dy={float(meta.get('dy_mm', 0.0)):.3f} mm."
                )
    if table_centered:
        logger(f"OpenGOST LFF table row vertical centering: adjusted {table_centered} text line(s).")
    return strokes, accepted, missing


def _geometry_polylines_from_pdf(source_pdf: Path, work_dir: Path, logs: list[str]) -> tuple[list[Polyline], float, float, Path]:
    geometry_svg = work_dir / "source_geometry_without_pdf_text.svg"
    page_w_mm, page_h_mm = prep._export_pdf_page_to_mupdf_svg(source_pdf, 0, geometry_svg, text_as_path=False)
    path_items = backend.extract_polylines(geometry_svg)
    page_items, _unit_scale = backend.normalize_path_units_to_page(
        path_items,
        float(page_w_mm),
        float(page_h_mm),
        logger=logs.append,
    )
    with prep._backend_override_context(
        {
            "HANDWRITING_TEXT_ENABLED": False,
            "HANDWRITING_STROKE_ACTIVE": False,
            "SINGLE_STROKE_TEXT_ENABLED": False,
            "SINGLE_STROKE_OUTLINE_TEXT_ENABLED": False,
            "TECH_TEXT_JOIN_ENABLE": False,
        }
    ):
        if prep._drawing_frame_class(source_pdf) == "kompas_full_frame":
            geometry = prep._kompas_source_to_drawing_polylines(page_items, source_pdf=source_pdf, page_index=0)
        else:
            geometry = backend.to_drawing_polylines(page_items)
    return geometry, float(page_w_mm), float(page_h_mm), geometry_svg


def _cleanup_source_geometry(
    source_pdf: Path,
    geometry: list[Polyline],
    page_w_mm: float,
    page_h_mm: float,
    report: dict[str, Any],
    logs: list[str],
) -> tuple[list[Polyline], dict[str, Any]]:
    meta: dict[str, Any] = {}
    if prep._drawing_frame_class(source_pdf) == "kompas_full_frame":
        geometry, archive_meta = prep._cleanup_kompas_archive_strip_polylines(
            geometry,
            page_w_mm=float(page_w_mm),
            page_h_mm=float(page_h_mm),
            specification_table=prep._is_kompas_specification_table_source(source_pdf),
            service_regions_mm=prep._kompas_service_regions_from_pdf(source_pdf, page_index=0),
        )
        meta["archive_strip"] = archive_meta
        if bool(report.get("a3_two_pass")) or max(page_w_mm, page_h_mm) > 300.0:
            geometry, a3_frame_meta = prep._strip_kompas_a3_outer_sheet_frame_polylines(
                geometry,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            meta["a3_outer_sheet_frame"] = a3_frame_meta
    logs.append(
        "source geometry cleanup: "
        f"frame_class={prep._drawing_frame_class(source_pdf)}; "
        f"polylines={len(geometry)}; "
        f"a3={bool(report.get('a3_two_pass'))}."
    )
    return geometry, meta


def _write_source_artifacts(
    work_dir: Path,
    polylines: list[Polyline],
    page_w_mm: float,
    page_h_mm: float,
) -> dict[str, str]:
    combined_svg = work_dir / "source_new_algorithm_combined.svg"
    combined_pdf = work_dir / "source_new_algorithm_combined.pdf"
    gost._write_polylines_svg(polylines, combined_svg, float(page_w_mm), float(page_h_mm))
    prep._render_polylines_pdf(
        polylines=polylines,
        out_pdf=combined_pdf,
        canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)),
    )
    return {"combined_svg": str(combined_svg), "combined_pdf": str(combined_pdf)}



def _clean_source_background_for_pack(pack: Path, source_pdf: Path, report: dict[str, Any]) -> Path | None:
    if bool(report.get("a3_two_pass")):
        return None
    candidates = [
        pack / "a4_clean_source.pdf",
        pack / "clean_source.pdf",
        source_pdf.with_name(f"{source_pdf.stem}_pack") / "a4_clean_source.pdf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _pt_point_to_mm(point: Any) -> Point:
    return float(point.x) * lff_text.PT_TO_MM, float(point.y) * lff_text.PT_TO_MM


def _pt_poly_to_mm(polyline: list[Point]) -> Polyline:
    return [(float(x) * lff_text.PT_TO_MM, float(y) * lff_text.PT_TO_MM) for x, y in polyline]


def _quad_to_mm_polyline(quad: Any) -> Polyline:
    points: list[Any] = []
    for attr in ("ul", "ur", "lr", "ll"):
        if hasattr(quad, attr):
            points.append(getattr(quad, attr))
    if len(points) < 4:
        try:
            points = list(quad)
        except TypeError:
            points = []
    if len(points) < 4:
        return []
    mm_points = [_pt_point_to_mm(point) for point in points[:4]]
    return [*mm_points, mm_points[0]]


def _clean_background_polylines_from_pdf(
    background_pdf: Path,
    text_doc: fitz.Document,
    logs: list[str],
) -> tuple[list[Polyline], dict[str, int], float, float]:
    background = fitz.open(background_pdf)
    try:
        if background.page_count < 1:
            return [], {"removed_background_text_segments": 0, "kept_background_segments": 0}, 0.0, 0.0
        bg_page = background[0]
        text_page = text_doc[0]
        text_rects = [
            lff_text._expanded_rect(lff_text._line_render_rect(line), 0.35)
            for line in lff_text._extract_text_lines(text_page)
        ]
        polylines: list[Polyline] = []
        removed_segments = 0
        kept_segments = 0
        for drawing in bg_page.get_drawings():
            for item in drawing.get("items", []):
                kind = item[0]
                if kind == "l":
                    p0, p1 = item[1], item[2]
                    if lff_text._is_background_service_gutter_segment(p0, p1, bg_page.rect):
                        removed_segments += 1
                        continue
                    if lff_text._should_drop_background_segment(p0, p1, text_rects):
                        removed_segments += 1
                        continue
                    polylines.append([_pt_point_to_mm(p0), _pt_point_to_mm(p1)])
                    kept_segments += 1
                elif kind == "qu":
                    polyline = _quad_to_mm_polyline(item[1])
                    if len(polyline) >= 2:
                        polylines.append(polyline)
                        kept_segments += max(1, len(polyline) - 1)
        logs.append(
            "OpenGOST clean-source background: "
            f"source={background_pdf}; kept_segments={kept_segments}; removed_text_segments={removed_segments}."
        )
        return polylines, {
            "removed_background_text_segments": int(removed_segments),
            "kept_background_segments": int(kept_segments),
        }, float(bg_page.rect.width) * lff_text.PT_TO_MM, float(bg_page.rect.height) * lff_text.PT_TO_MM
    finally:
        background.close()


def _make_experiment_lff_text_strokes(
    source_pdf: Path,
    logs: list[str],
    *,
    normalize_dimension_text: bool = False,
    table_rules: list[HorizontalRule] | None = None,
) -> tuple[list[Polyline], list[dict[str, Any]], set[str], int, int]:
    if not LFF_FONT_PATH.exists():
        return [], [], {"LFF_FONT_UNAVAILABLE"}, 0, 0
    font = lff_text.load_lff_font(LFF_FONT_PATH)
    missing: set[str] = set()
    strokes: list[Polyline] = []
    accepted: list[dict[str, Any]] = []
    text_doc = fitz.open(source_pdf)
    try:
        page = text_doc[0]
        page_w_mm = float(page.rect.width) * lff_text.PT_TO_MM
        page_h_mm = float(page.rect.height) * lff_text.PT_TO_MM
        lines = lff_text._extract_text_lines(page)
        skipped = 0
        table_centered = 0
        for raw_line in lines:
            line = dict(raw_line)
            line["text"] = _repair_pdf_text_mojibake(line.get("text", ""))
            rect = fitz.Rect(line["bbox"])  # type: ignore[arg-type]
            text = str(line["text"])
            if lff_text._is_service_or_footer_text(text, rect, page.rect):
                skipped += 1
                continue
            line_mm = dict(line)
            line_mm["bbox_mm"] = [
                float(rect.x0) * lff_text.PT_TO_MM,
                float(rect.y0) * lff_text.PT_TO_MM,
                float(rect.x1) * lff_text.PT_TO_MM,
                float(rect.y1) * lff_text.PT_TO_MM,
            ]
            if table_rules:
                centered_line = _center_text_line_in_table_row(line_mm, table_rules)
                if centered_line is not line_mm:
                    table_centered += 1
                line_mm = centered_line
            line_fill = LFF_STAMP_FILL if _looks_like_lff_stamp_cell(line_mm, page_w_mm, page_h_mm) else LFF_FILL
            mm_polys = _line_to_lff_opengost_polys(
                font,
                line_mm,
                page_w_mm=page_w_mm,
                page_h_mm=page_h_mm,
                missing=missing,
                normalize_dimension_text=normalize_dimension_text,
            )
            if not mm_polys:
                missing.add(text)
                continue
            strokes.extend(mm_polys)
            accepted.append(
                {
                    "text": text,
                    "bbox": [round(float(v), 4) for v in rect],
                    "dir": line.get("dir"),
                    "font": str(LFF_FONT_PATH),
                    "fill": line_fill,
                }
            )
            logs.append(
                f"OpenGOST LFF experiment text: '{lff_text._line_display_text(line)}' -> "
                f"{len(mm_polys)} stroke(s), font={LFF_FONT_PATH.name}, fill={line_fill:.2f}, shear={LFF_SHEAR:.2f}"
            )
        if table_centered:
            logs.append(f"OpenGOST LFF table row vertical centering: adjusted {table_centered} text line(s).")
        return strokes, accepted, missing, len(lines), skipped
    finally:
        text_doc.close()



def _line_bbox_mm(line: dict[str, Any]) -> tuple[float, float, float, float] | None:
    for key in ("bbox_mm", "bbox", "rect_mm"):
        bbox = line.get(key)
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            except (TypeError, ValueError):
                continue
            return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    keys = ("x0_mm", "y0_mm", "x1_mm", "y1_mm")
    if all(key in line for key in keys):
        try:
            x0, y0, x1, y1 = (float(line[key]) for key in keys)
        except (TypeError, ValueError):
            return None
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    return None


def _polyline_length(poly: Polyline) -> float:
    return sum(_dist(poly[idx - 1], poly[idx]) for idx in range(1, len(poly)))


def _remove_existing_text_geometry(
    geometry: list[Polyline],
    text_lines: list[dict[str, Any]],
    logger,
    *,
    pad_mm: float = 0.75,
) -> list[Polyline]:
    boxes: list[tuple[float, float, float, float, float, float]] = []
    for line in text_lines:
        bbox = _line_bbox_mm(line)
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        width = x1 - x0
        height = y1 - y0
        if width < 0.5 or height < 0.5:
            continue
        boxes.append((x0 - pad_mm, y0 - pad_mm, x1 + pad_mm, y1 + pad_mm, width, height))
    if not boxes:
        return geometry

    kept: list[Polyline] = []
    removed = 0
    for poly in geometry:
        if len(poly) < 2:
            continue
        bx0, by0, bx1, by1 = _bounds([poly])
        bw = bx1 - bx0
        bh = by1 - by0
        length = _polyline_length(poly)
        drop = False
        for tx0, ty0, tx1, ty1, tw, th in boxes:
            if bx0 < tx0 or bx1 > tx1 or by0 < ty0 or by1 > ty1:
                continue
            # Do not eat table/frame lines that happen to cross a text bbox.
            if bh <= 0.08 and bw >= max(12.0, tw * 0.8):
                continue
            if bw <= 0.08 and bh >= max(12.0, th * 0.8):
                continue
            if bw <= tw + 2.0 and bh <= th + 2.0 and length <= max(12.0, 12.0 * (tw + th)):
                drop = True
                break
        if drop:
            removed += 1
        else:
            kept.append(poly)
    if removed:
        before_segments = sum(max(0, len(poly) - 1) for poly in geometry)
        after_segments = sum(max(0, len(poly) - 1) for poly in kept)
        logger(
            "Existing PDF text geometry removed before LFF text overlay: "
            f"polylines={removed}; segments_removed={max(0, before_segments - after_segments)}; "
            f"text_boxes={len(boxes)}."
        )
    return kept

def _build_clean_source_opengost_source(
    pack: Path,
    source_pdf: Path,
    clean_source_pdf: Path,
    settings: Settings,
) -> SourceBuild:
    logs: list[str] = [
        "source route: clean_source_background + OpenGOST LFF experiment renderer; "
        "preserve source frame, do not replace it with work_area_frame=full."
    ]
    work_dir = pack / "_new_algorithm_source"
    work_dir.mkdir(parents=True, exist_ok=True)
    text_doc = fitz.open(source_pdf)
    try:
        geometry, background_meta, page_w_mm, page_h_mm = _clean_background_polylines_from_pdf(clean_source_pdf, text_doc, logs)
    finally:
        text_doc.close()
    text_lines_for_cleanup, _cleanup_lines_found, _cleanup_lines_skipped = _text_lines_for_source(source_pdf)
    geometry = _remove_existing_text_geometry(geometry, text_lines_for_cleanup, logs.append)
    is_specification = _is_new_algorithm_specification(source_pdf, geometry)
    if is_specification:
        geometry = _snap_specification_table_grid_polylines(geometry, logs)
    table_rules = _horizontal_table_rules_from_polylines(geometry)
    text_polys, accepted_text, missing_chars, text_lines_found, text_lines_skipped = _make_experiment_lff_text_strokes(
        source_pdf,
        logs,
        normalize_dimension_text=_is_computer_graphics_mode(settings),
        table_rules=table_rules,
    )
    source_polys = [*geometry, *text_polys]
    source_segments = sum(max(0, len(poly) - 1) for poly in source_polys)
    logs.append(
        "OpenGOST onepass source: "
        f"polylines={len(source_polys)}; dense_segments={source_segments}; "
        "generic backend dedup disabled to preserve LFF arcs."
    )
    artifacts = {
        "clean_source_background_pdf": str(clean_source_pdf),
    }
    artifacts.update(_write_source_artifacts(work_dir, source_polys, page_w_mm, page_h_mm))
    report_payload = {
        "source_pdf": str(source_pdf),
        "background_pdf": str(clean_source_pdf),
        "algorithm": "new-algorithm-v2-clean-source-background-plus-opengost-lff-experiment-text",
        "font_target": "LibreCAD OpenGOST LFF single-line",
        "text_font": str(LFF_FONT_PATH),
        "text_fill": LFF_FILL,
        "text_stamp_fill": LFF_STAMP_FILL,
        "text_shear": LFF_SHEAR,
        "old_nc_used_as_source": False,
        "page_size_mm": [round(page_w_mm, 3), round(page_h_mm, 3)],
        "geometry_polylines": len(geometry),
        "background_cleanup": background_meta,
        "text_lines_found": int(text_lines_found),
        "text_lines_skipped_service": int(text_lines_skipped),
        "text_lines_rendered": len(accepted_text),
        "text_polylines": len(text_polys),
        "source_dense_segments": source_segments,
        "missing_chars": sorted(missing_chars),
        "preserve_source_frame": True,
        "artifacts": artifacts,
        "logs": logs,
    }
    (work_dir / "source_report.json").write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts["source_report"] = str(work_dir / "source_report.json")
    return SourceBuild(
        source_pdf=source_pdf,
        page_w_mm=page_w_mm,
        page_h_mm=page_h_mm,
        polylines=source_polys,
        geometry_polylines=len(geometry),
        text_polylines=len(text_polys),
        text_lines_found=int(text_lines_found),
        text_lines_rendered=len(accepted_text),
        text_lines_skipped=int(text_lines_skipped),
        missing_chars=sorted(missing_chars),
        logs=logs,
        artifacts=artifacts,
        preserve_source_frame=True,
        dense_onepass_source=True,
    )

def _build_source(pack: Path, source_pdf: Path, report: dict[str, Any], settings: Settings) -> SourceBuild:
    clean_source_pdf = _clean_source_background_for_pack(pack, source_pdf, report)
    if clean_source_pdf is not None:
        return _build_clean_source_opengost_source(pack, source_pdf, clean_source_pdf, settings)
    logs: list[str] = []
    work_dir = pack / "_new_algorithm_source"
    work_dir.mkdir(parents=True, exist_ok=True)
    geometry, page_w_mm, page_h_mm, geometry_svg = _geometry_polylines_from_pdf(source_pdf, work_dir, logs)
    geometry, cleanup_meta = _cleanup_source_geometry(source_pdf, geometry, page_w_mm, page_h_mm, report, logs)
    dense_onepass_source = bool(report.get("a3_two_pass"))
    if dense_onepass_source:
        geometry_segments = sum(max(0, len(poly) - 1) for poly in geometry)
        logs.append(
            "A3 dense structural source: "
            f"geometry_segments={geometry_segments}; "
            "stamp grid is preserved; old collinear-overlap simplifier is disabled for A3 geometry and LFF text."
        )
    text_lines, text_lines_found, text_lines_skipped = _text_lines_for_source(source_pdf)
    geometry = _remove_existing_text_geometry(geometry, text_lines, logs.append)
    is_specification = _is_new_algorithm_specification(source_pdf, geometry)
    if is_specification:
        geometry = _snap_specification_table_grid_polylines(geometry, logs)
    table_rules = _horizontal_table_rules_from_polylines(geometry)
    text_polys, accepted_text, missing_chars = _make_lff_opengost_text_strokes(
        text_lines,
        page_w_mm,
        page_h_mm,
        logs.append,
        use_stamp_overrides=not dense_onepass_source and not is_specification,
        center_a3_top_left_title=bool(dense_onepass_source and _is_computer_graphics_mode(settings)),
        normalize_dimension_text=_is_computer_graphics_mode(settings),
        table_rules=table_rules,
    )
    if dense_onepass_source:
        logs.append("A3 dense text placement: A4 stamp cell overrides disabled; using real PDF text bbox coordinates.")
    source_polys = [*geometry, *text_polys]
    if dense_onepass_source:
        source_segments = sum(max(0, len(poly) - 1) for poly in source_polys)
        logs.append(
            "OpenGOST dense A3 source: "
            f"polylines={len(source_polys)}; dense_segments={source_segments}; "
            "generic backend dedup/stitch disabled after text to preserve LFF text strokes."
        )
    else:
        source_polys = backend.deduplicate_segments(source_polys, logger=logs.append)
        source_polys = backend.deduplicate_collinear_overlaps(source_polys, logger=logs.append)
        source_segments = sum(max(0, len(poly) - 1) for poly in source_polys)
    artifacts = {"geometry_svg": str(geometry_svg)}
    artifacts.update(_write_source_artifacts(work_dir, source_polys, page_w_mm, page_h_mm))
    report_payload = {
        "source_pdf": str(source_pdf),
        "algorithm": "new-algorithm-v2-source-pdf-geometry-plus-opengost-lff-singleline-text",
        "font_target": "LibreCAD OpenGOST LFF single-line",
        "text_font": str(LFF_FONT_PATH),
        "text_fill": LFF_FILL,
        "text_stamp_fill": LFF_STAMP_FILL,
        "text_shear": LFF_SHEAR,
        "old_nc_used_as_source": False,
        "page_size_mm": [round(page_w_mm, 3), round(page_h_mm, 3)],
        "geometry_polylines": len(geometry),
        "text_lines_found": int(text_lines_found),
        "text_lines_skipped_service": int(text_lines_skipped),
        "text_lines_rendered": len(accepted_text),
        "text_polylines": len(text_polys),
        "source_dense_segments": source_segments,
        "missing_chars": sorted(missing_chars),
        "cleanup_meta": cleanup_meta,
        "dense_onepass_source": bool(dense_onepass_source),
        "artifacts": artifacts,
        "logs": logs,
    }
    (work_dir / "source_report.json").write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifacts["source_report"] = str(work_dir / "source_report.json")
    return SourceBuild(
        source_pdf=source_pdf,
        page_w_mm=page_w_mm,
        page_h_mm=page_h_mm,
        polylines=source_polys,
        geometry_polylines=len(geometry),
        text_polylines=len(text_polys),
        text_lines_found=int(text_lines_found),
        text_lines_rendered=len(accepted_text),
        text_lines_skipped=int(text_lines_skipped),
        missing_chars=sorted(missing_chars),
        logs=logs,
        artifacts=artifacts,
        dense_onepass_source=bool(dense_onepass_source),
    )


def _parse_fit_transform(logs: list[str]) -> tuple[float, float, float] | None:
    for line in logs:
        match = A3_FIT_RE.search(str(line))
        if match:
            return float(match.group(1)), float(match.group(2)), float(match.group(3))
    return None


def _parse_pass_shift(logs: list[str]) -> tuple[float, float]:
    for line in logs:
        match = A3_PASS_RE.search(str(line))
        if match:
            return float(match.group(1)), float(match.group(2))
    return 0.0, 0.0


def _parse_post_translate(logs: list[str]) -> tuple[float, float]:
    for line in logs:
        match = A3_POST_TRANSLATE_RE.search(str(line))
        if match:
            return float(match.group(1)), float(match.group(2))
    return 0.0, 0.0


def _report_item(report: dict[str, Any], item_name: str) -> dict[str, Any] | None:
    for raw in report.get("items") or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("item") or "") == item_name:
            return raw
        raw_nc = str(raw.get("nc") or "")
        if raw_nc and Path(raw_nc).stem == item_name:
            return raw
    return None


def _transform_for_item(report: dict[str, Any], item_name: str) -> Transform | None:
    item = _report_item(report, item_name)
    if item is None:
        return None
    logs = [str(line) for line in list(item.get("logs") or [])]
    if bool(report.get("a3_two_pass")) or item_name.startswith("pass_"):
        fit = _parse_fit_transform(logs)
        if fit is None:
            if any("Fit guard (1:1 mm)" in line or "keeping scale=1.0" in line for line in logs):
                fit = (1.0, 0.0, 0.0)
            else:
                return None
        shift_x, shift_y = _parse_pass_shift(logs)
        post_x, post_y = _parse_post_translate(logs)
        rotate_180 = item_name == "pass_02" or "pass_02_rotated_180_for_sheet_flip=True" in str(item.get("notes", ""))
        return Transform(
            scale=float(fit[0]),
            translate_x=float(fit[1]),
            translate_y=float(fit[2]),
            shift_x=float(shift_x),
            shift_y=float(shift_y),
            rotate_180=bool(rotate_180),
            post_translate_x=float(post_x),
            post_translate_y=float(post_y),
        )
    meta = item.get("clean_bbox_fit_meta")
    if isinstance(meta, dict):
        return Transform(
            scale=float(meta.get("content_scale", 1.0) or 1.0),
            translate_x=float(meta.get("translate_x_mm", 0.0) or 0.0),
            translate_y=float(meta.get("translate_y_mm", 0.0) or 0.0),
        )
    fit = _parse_fit_transform(logs)
    if fit is not None:
        return Transform(scale=float(fit[0]), translate_x=float(fit[1]), translate_y=float(fit[2]))
    return None


def _transform_point(point: Point, transform: Transform) -> Point:
    x = float(point[0]) * transform.scale + transform.translate_x + transform.shift_x
    y = float(point[1]) * transform.scale + transform.translate_y + transform.shift_y
    if transform.rotate_180:
        work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
        center_x = 0.5 * (float(work_x0) + float(work_x1))
        center_y = 0.5 * (float(work_y0) + float(work_y1))
        x = (2.0 * center_x) - x
        y = (2.0 * center_y) - y
    return x + transform.post_translate_x, y + transform.post_translate_y


def _map_to_item(source_polys: list[Polyline], transform: Transform, settings: Settings, logs: list[str]) -> list[Polyline]:
    mapped = [[_transform_point(point, transform) for point in poly] for poly in source_polys if len(poly) >= 2]
    mapped = _translate(mapped, settings.x_compensation_mm, 0.0)
    clipped = backend.clip_polylines_to_work_area(mapped, logger=logs.append)
    clipped = backend.deduplicate_segments(clipped, logger=logs.append)
    clipped = backend.deduplicate_collinear_overlaps(clipped, logger=logs.append)
    stitched = stitch_gcode_polylines.stitch_polylines(clipped, eps=settings.stitch_eps_mm)
    ordered = stitch_gcode_polylines.nearest_order(stitched)
    final = _dedup_segments(ordered)
    final = backend.deduplicate_collinear_overlaps(final, logger=logs.append)
    return _dedup_segments(final)


def _stitch_touching_polylines(
    polylines: list[Polyline],
    settings: Settings,
    logs: list[str],
    *,
    label: str,
) -> list[Polyline]:
    before_paths = len(polylines)
    before_segments = sum(max(0, len(poly) - 1) for poly in polylines)
    stitched = stitch_gcode_polylines.stitch_polylines(polylines, eps=settings.stitch_eps_mm)
    ordered = stitch_gcode_polylines.nearest_order(stitched)
    after_paths = len(ordered)
    after_segments = sum(max(0, len(poly) - 1) for poly in ordered)
    if after_paths != before_paths:
        logs.append(
            f"{label}: endpoint-only stitch {before_paths}->{after_paths} paths; "
            f"segments {before_segments}->{after_segments}; eps={settings.stitch_eps_mm:.3f} mm; "
            "nearest-order enabled after stitching; no collinear simplifier applied."
        )
    return ordered


def _strip_work_area_outer_border_segments(
    polylines: list[Polyline],
    logs: list[str],
    *,
    eps_mm: float = 1.15,
    min_len_mm: float = 35.0,
) -> list[Polyline]:
    work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
    removed = 0
    out: list[Polyline] = []

    def is_outer_border_segment(a: Point, b: Point) -> bool:
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        dx = abs(bx - ax)
        dy = abs(by - ay)
        if dy <= float(eps_mm) and dx >= float(min_len_mm):
            y = (ay + by) * 0.5
            return abs(y - float(work_y0)) <= float(eps_mm) or abs(y - float(work_y1)) <= float(eps_mm)
        if dx <= float(eps_mm) and dy >= float(min_len_mm):
            x = (ax + bx) * 0.5
            return abs(x - float(work_x0)) <= float(eps_mm) or abs(x - float(work_x1)) <= float(eps_mm)
        return False

    for poly in polylines:
        current: Polyline = []
        for idx in range(1, len(poly)):
            a = poly[idx - 1]
            b = poly[idx]
            if is_outer_border_segment(a, b):
                removed += 1
                if len(current) >= 2:
                    out.append(current)
                current = []
                continue
            if not current:
                current = [a, b]
            elif _dist(current[-1], a) > 0.005:
                if len(current) >= 2:
                    out.append(current)
                current = [a, b]
            else:
                current.append(b)
        if len(current) >= 2:
            out.append(current)

    if removed:
        logs.append(
            "A3 work-area outer border strip: "
            f"removed={removed}; eps={eps_mm:.2f} mm; min_len={min_len_mm:.1f} mm; "
            f"work_bounds=({work_x0:.3f},{work_x1:.3f},{work_y0:.3f},{work_y1:.3f})."
        )
    return out


def _is_a3_top_left_title_fragment_source(poly: Polyline) -> bool:
    if len(poly) < 2:
        return False
    x0, y0, x1, y1 = _bounds([poly])
    return 20.0 <= float(x0) <= 95.0 and float(x1) <= 95.5 and float(y0) <= 25.0 and float(y1) <= 25.0


def _map_to_item_dense_onepass(
    source_polys: list[Polyline],
    transform: Transform,
    settings: Settings,
    logs: list[str],
) -> list[Polyline]:
    computer_graphics_frame_rules = _is_computer_graphics_mode(settings)
    mapped_tagged: list[tuple[Polyline, bool]] = []
    for poly in source_polys:
        if len(poly) < 2:
            continue
        mapped_poly = [_transform_point(point, transform) for point in poly]
        mapped_tagged.append((mapped_poly, computer_graphics_frame_rules and (not transform.rotate_180) and _is_a3_top_left_title_fragment_source(poly)))
    if abs(float(settings.x_compensation_mm)) > 1e-9:
        mapped_tagged = [(_translate([poly], settings.x_compensation_mm, 0.0)[0], tag) for poly, tag in mapped_tagged]
    if not transform.rotate_180:
        corner_polys = [poly for poly, tag in mapped_tagged if tag]
        if corner_polys:
            work_x0, _work_x1, work_y0, _work_y1 = prep._machine_work_area_bounds_mm()
            bx0, by0, _bx1, _by1 = _bounds(corner_polys)
            corner_dx = float(work_x0) - float(bx0) if 0.0 <= float(bx0) - float(work_x0) <= 20.0 else 0.0
            corner_dy = float(work_y0) - float(by0) if 0.0 < float(by0) - float(work_y0) <= 20.0 else 0.0
            if abs(corner_dx) > 1e-6 or abs(corner_dy) > 1e-6:
                shifted: list[tuple[Polyline, bool]] = []
                for poly, tag in mapped_tagged:
                    shifted.append(([(float(x) + (corner_dx if tag else 0.0), float(y) + (corner_dy if tag else 0.0)) for x, y in poly], tag))
                mapped_tagged = shifted
                logs.append(
                    "A3 pass_01 title-fragment corner anchor: "
                    f"dx={corner_dx:.3f} mm; dy={corner_dy:.3f} mm; "
                    f"bbox_min_before=({bx0:.3f},{by0:.3f}); work_min=({work_x0:.3f},{work_y0:.3f}); "
                    f"polylines={len(corner_polys)}."
                )
    mapped = [poly for poly, _tag in mapped_tagged]
    pre_clip_segments = sum(max(0, len(poly) - 1) for poly in mapped)
    clipped = backend.clip_polylines_to_work_area(mapped, logger=logs.append)
    if transform.rotate_180 and clipped:
        work_x0, _work_x1, work_y0, _work_y1 = prep._machine_work_area_bounds_mm()
        bx0, by0, _bx1, _by1 = _bounds(clipped)
        anchor_dx = float(work_x0) - float(bx0) if 0.0 < float(bx0) - float(work_x0) <= 20.0 else 0.0
        anchor_dy = float(work_y0) - float(by0) if 0.0 < float(by0) - float(work_y0) <= 20.0 else 0.0
        if abs(anchor_dx) > 1e-6 or abs(anchor_dy) > 1e-6:
            clipped = _translate(clipped, anchor_dx, anchor_dy)
            logs.append(
                "A3 rotated pass corner anchor: "
                f"dx={anchor_dx:.3f} mm; dy={anchor_dy:.3f} mm; "
                f"bbox_min_before=({bx0:.3f},{by0:.3f}); work_min=({work_x0:.3f},{work_y0:.3f})."
            )
            clipped = backend.clip_polylines_to_work_area(clipped, logger=logs.append)
    if computer_graphics_frame_rules:
        clipped = _strip_work_area_outer_border_segments(clipped, logs)
    else:
        logs.append("A3 descriptive-geometry frame profile: work-area outer-border strip disabled; standard task frame kept.")
    clipped_segments = sum(max(0, len(poly) - 1) for poly in clipped)
    deduped = _dedup_segments(clipped)
    final = _stitch_touching_polylines(
        deduped,
        settings,
        logs,
        label="A3 dense onepass continuity",
    )
    final_segments = sum(max(0, len(poly) - 1) for poly in final)
    logs.append(
        "A3 dense onepass route: "
        "old collinear-overlap simplifier is disabled; endpoint-only stitch and nearest-order are enabled; "
        f"pre_clip_segments={pre_clip_segments}; clipped_segments={clipped_segments}; "
        f"dense_lff_segments_preserved={final_segments}; dedup_removed={max(0, clipped_segments - final_segments)}."
    )
    return final


def _source_frame_bbox(source_polys: list[Polyline]) -> tuple[float, float, float, float]:
    try:
        return prep._structural_outer_frame_bbox_mm(source_polys)
    except Exception:
        return _bounds(source_polys)


def _map_a4_preserving_source_frame(source_build: SourceBuild, settings: Settings, logs: list[str]) -> tuple[list[Polyline], dict[str, Any]]:
    work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
    src_x0, src_y0, src_x1, src_y1 = _source_frame_bbox(source_build.polylines)
    source_w = max(1e-9, float(src_x1) - float(src_x0))
    source_h = max(1e-9, float(src_y1) - float(src_y0))
    work_w = max(1e-9, float(work_x1) - float(work_x0))
    work_h = max(1e-9, float(work_y1) - float(work_y0))
    scale_x = work_w / source_w
    scale_y = work_h / source_h
    dx = ((work_x0 + work_x1) * 0.5) - (((src_x0 + src_x1) * 0.5) * scale_x)
    dy = ((work_y0 + work_y1) * 0.5) - (((src_y0 + src_y1) * 0.5) * scale_y)
    snap_eps = 0.70

    stamp_band_low_y1 = float(src_y0) + 62.0
    stamp_band_high_y0 = float(src_y1) - 62.0
    draw_dx = float(work_x0) - float(src_x0)
    draw_dy = float(work_y0) - float(src_y0)
    frame_scaled_polylines = 0
    drawing_1to1_polylines = 0

    def poly_bbox(poly: Polyline) -> tuple[float, float, float, float]:
        xs = [float(point[0]) for point in poly]
        ys = [float(point[1]) for point in poly]
        return min(xs), min(ys), max(xs), max(ys)

    def use_frame_scaled(poly: Polyline) -> bool:
        px0, py0, px1, py1 = poly_bbox(poly)
        if px0 <= float(src_x0) + snap_eps or px1 >= float(src_x1) - snap_eps:
            return True
        if py0 <= float(src_y0) + snap_eps or py1 >= float(src_y1) - snap_eps:
            return True
        center_y = (py0 + py1) * 0.5
        return center_y <= stamp_band_low_y1 or center_y >= stamp_band_high_y0

    def map_frame_point(point: Point) -> Point:
        x, y = point
        mapped_x = float(x) * scale_x + dx
        mapped_y = float(y) * scale_y + dy
        if abs(float(x) - float(src_x0)) <= snap_eps:
            mapped_x = float(work_x0)
        elif abs(float(x) - float(src_x1)) <= snap_eps:
            mapped_x = float(work_x1)
        if abs(float(y) - float(src_y0)) <= snap_eps:
            mapped_y = float(work_y0)
        elif abs(float(y) - float(src_y1)) <= snap_eps:
            mapped_y = float(work_y1)
        return mapped_x, mapped_y

    def map_drawing_point(point: Point) -> Point:
        x, y = point
        return float(x) + draw_dx, float(y) + draw_dy

    mapped: list[Polyline] = []
    for poly in source_build.polylines:
        if len(poly) < 2:
            continue
        if use_frame_scaled(poly):
            frame_scaled_polylines += 1
            mapped_poly = [map_frame_point((float(x), float(y))) for x, y in poly]
        else:
            drawing_1to1_polylines += 1
            mapped_poly = [map_drawing_point((float(x), float(y))) for x, y in poly]
        if len(mapped_poly) >= 2:
            mapped.append(mapped_poly)

    mapped = _translate(mapped, settings.x_compensation_mm, 0.0)
    pre_clip_segments = sum(max(0, len(poly) - 1) for poly in mapped)
    mapped = backend.clip_polylines_to_work_area(mapped, logger=logs.append)
    pre_segments = sum(max(0, len(poly) - 1) for poly in mapped)
    # Keep the dense OpenGOST LFF geometry. The generic collinear-overlap cleanup
    # calls simplify_polyline() on rebuilt paths and collapses the onepass LFF
    # arcs/letters from ~4.6k segments to ~0.8k segments, which is exactly what
    # made page_01_new_algorithm differ from the accepted 07_lff...dedup_xfixed file.
    deduped = _dedup_segments(mapped)
    final = _stitch_touching_polylines(
        deduped,
        settings,
        logs,
        label="A4 clean-source onepass continuity",
    )
    post_segments = sum(max(0, len(poly) - 1) for poly in final)
    logs.append(
        "A4 clean-source onepass route: "
        f"source_frame_bbox={[round(float(v), 4) for v in (src_x0, src_y0, src_x1, src_y1)]}; "
        f"scale_x={scale_x:.6f}; scale_y={scale_y:.6f}; translate=({dx:.4f},{dy:.4f}) mm; "
        f"snap_outer_frame_to_work_area=True; frame_scaled_polylines={frame_scaled_polylines}; "
        f"drawing_1to1_polylines={drawing_1to1_polylines}; clipped_segments={max(0, pre_clip_segments - pre_segments)}; "
        f"dense_lff_segments_preserved={post_segments}; dedup_removed={max(0, pre_segments - post_segments)}."
    )
    return final, {
        "applied": True,
        "mode": "clean_source_onepass_opengost_lff_fast_dedup_xfixed",
        "source_bbox": [round(float(v), 4) for v in (src_x0, src_y0, src_x1, src_y1)],
        "scale_x": round(float(scale_x), 6),
        "scale_y": round(float(scale_y), 6),
        "translate_x_mm": round(float(dx), 6),
        "translate_y_mm": round(float(dy), 6),
        "snap_outer_frame_to_work_area": True,
        "stamp_band_low_y1": round(float(stamp_band_low_y1), 6),
        "stamp_band_high_y0": round(float(stamp_band_high_y0), 6),
        "drawing_1to1_translate_x_mm": round(float(draw_dx), 6),
        "drawing_1to1_translate_y_mm": round(float(draw_dy), 6),
        "frame_scaled_polylines": int(frame_scaled_polylines),
        "drawing_1to1_polylines": int(drawing_1to1_polylines),
        "clipped_segments": int(max(0, pre_clip_segments - pre_segments)),
        "dense_lff_segments_preserved": int(post_segments),
        "dedup_removed": int(max(0, pre_segments - post_segments)),
        "work_area_bounds": [round(float(v), 4) for v in (work_x0, work_x1, work_y0, work_y1)],
    }


def _prepare_a4_page(source_build: SourceBuild, settings: Settings, logs: list[str]) -> tuple[list[Polyline], dict[str, Any]]:
    if source_build.preserve_source_frame:
        return _map_a4_preserving_source_frame(source_build, settings, logs)
    final_polys, fit_meta = prep._prepare_kompas_a4_clean_bbox_fit_polylines(source_build.polylines, logs=logs)
    if not final_polys:
        work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
        sx0, sy0, sx1, sy1 = _bounds(source_build.polylines)
        src_w = max(1e-9, sx1 - sx0)
        src_h = max(1e-9, sy1 - sy0)
        scale = min((work_x1 - work_x0) / src_w, (work_y1 - work_y0) / src_h)
        tx = ((work_x0 + work_x1) * 0.5) - (((sx0 + sx1) * 0.5) * scale)
        ty = ((work_y0 + work_y1) * 0.5) - (((sy0 + sy1) * 0.5) * scale)
        mapped = [[(float(x) * scale + tx, float(y) * scale + ty) for x, y in poly] for poly in source_build.polylines]
        final_polys = backend.clip_polylines_to_work_area(mapped, logger=logs.append)
        fit_meta = {
            "applied": True,
            "fallback_generic_fit": True,
            "content_scale": round(float(scale), 6),
            "translate_x_mm": round(float(tx), 6),
            "translate_y_mm": round(float(ty), 6),
        }
    final_polys = _translate(final_polys, settings.x_compensation_mm, 0.0)
    final_polys = backend.deduplicate_segments(final_polys, logger=logs.append)
    final_polys = backend.deduplicate_collinear_overlaps(final_polys, logger=logs.append)
    stitched = stitch_gcode_polylines.stitch_polylines(final_polys, eps=settings.stitch_eps_mm)
    ordered = stitch_gcode_polylines.nearest_order(stitched)
    final = _dedup_segments(ordered)
    final = backend.deduplicate_collinear_overlaps(final, logger=logs.append)
    return _dedup_segments(final), fit_meta

def _output_items(report: dict[str, Any]) -> list[str]:
    if bool(report.get("a3_two_pass")):
        names = [str(item.get("item")) for item in report.get("items") or [] if isinstance(item, dict)]
        pass_names = [name for name in names if re.fullmatch(r"pass_\d+", name or "")]
        return sorted(set(pass_names)) or ["pass_01", "pass_02"]
    names = [str(item.get("item")) for item in report.get("items") or [] if isinstance(item, dict)]
    page_names = [name for name in names if re.fullmatch(r"page_\d+", name or "")]
    return sorted(set(page_names)) or ["page_01"]




def _render_pdf_to_png(pdf_path: Path, png_path: Path, *, dpi: int = 190) -> None:
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(float(dpi) / 72.0, float(dpi) / 72.0), alpha=False)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(png_path)


def _write_clean_preview_from_final_gcode(out_nc: Path, settings: Settings) -> tuple[Path, Path]:
    # This reads the final new-algorithm G-code only to render a human preview.
    # It is not used as source geometry for building the job.
    polylines = stitch_gcode_polylines.read_draw_polylines(out_nc)
    clean_pdf = out_nc.with_name(out_nc.stem + "_clean_preview.pdf")
    clean_png = out_nc.with_name(out_nc.stem + "_clean_preview.png")
    bx0, by0, bx1, by1 = _bounds(polylines)
    canvas_x0 = min(0.0, bx0) - 1.0
    canvas_x1 = max(float(settings.work_width), bx1) + 1.0
    canvas_y0 = min(float(settings.work_min_y), by0) - 1.0
    canvas_y1 = max(float(settings.work_min_y + settings.work_height), by1) + 1.0
    prep._render_polylines_pdf(
        polylines=polylines,
        out_pdf=clean_pdf,
        canvas_bounds_mm=(canvas_x0, canvas_x1, canvas_y0, canvas_y1),
    )
    _render_pdf_to_png(clean_pdf, clean_png, dpi=190)
    return clean_pdf, clean_png


def _write_item_outputs(pack: Path, item_name: str, polylines: list[Polyline], settings: Settings) -> dict[str, Any]:
    out_nc = pack / f"{item_name}_new_algorithm.nc"
    _write_new_gcode(out_nc, polylines, settings)
    preview_prefix = out_nc.with_name(out_nc.stem + "_preview")
    preview_pdf, preview_png, preview_bounds, preview_segments = render_gcode_preview.render_gcode_preview(
        out_nc,
        output_prefix=preview_prefix,
        transform=settings.paper_transform,
        work_width=settings.work_width,
        work_height=settings.work_height,
        work_min_y=settings.work_min_y,
    )
    clean_preview_pdf, clean_preview_png = _write_clean_preview_from_final_gcode(out_nc, settings)
    bx0, by0, bx1, by1 = _bounds(polylines)
    return {
        "output_nc": str(out_nc),
        "output_gcode": str(out_nc.with_suffix(".gcode")),
        "preview_pdf": str(preview_pdf),
        "preview_png": str(preview_png),
        "clean_preview_pdf": str(clean_preview_pdf),
        "clean_preview_png": str(clean_preview_png),
        "final_polylines": len(polylines),
        "segments_preview": int(preview_segments),
        "draw_length_mm": round(_draw_len(polylines), 3),
        "x_min": round(bx0, 3),
        "x_max": round(bx1, 3),
        "y_min": round(by0, 3),
        "y_max": round(by1, 3),
        "preview_x_min": round(float(preview_bounds[0]), 3),
        "preview_x_max": round(float(preview_bounds[2]), 3),
        "preview_y_min": round(float(preview_bounds[1]), 3),
        "preview_y_max": round(float(preview_bounds[3]), 3),
    }



def _copy_if_different(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.resolve() == dst.resolve():
            return
    except OSError:
        pass
    shutil.copy2(src, dst)


def _row_path(row: dict[str, Any], key: str) -> Path | None:
    value = row.get(key)
    if not value:
        return None
    return Path(str(value))


def _plotter_input_gcode_for_row(row: dict[str, Any]) -> Path | None:
    explicit = _row_path(row, "output_gcode")
    if explicit and explicit.exists():
        return explicit
    nc_path = _row_path(row, "output_nc")
    if nc_path is None:
        return None
    sibling = nc_path.with_suffix(".gcode")
    if sibling.exists():
        return sibling
    return nc_path if nc_path.exists() else None


def _item_slot_for_published_output(row: dict[str, Any], fallback_index: int, total: int) -> str:
    candidates = " ".join(
        str(row.get(key, ""))
        for key in ("item", "item_name", "output_nc", "preview_pdf", "clean_preview_pdf")
    ).casefold()
    if "pass_01" in candidates or "pass01" in candidates:
        return "pass_01"
    if "pass_02" in candidates or "pass02" in candidates:
        return "pass_02"
    if total <= 1:
        return ""
    return f"pass_{fallback_index + 1:02d}"


def _a3_preview_dashed_split(page_w_mm: float, page_h_mm: float) -> list[Polyline]:
    split_x = float(page_w_mm) / 2.0
    y = 0.0
    out: list[Polyline] = []
    dash = 8.0
    gap = 5.0
    while y < float(page_h_mm):
        y2 = min(float(page_h_mm), y + dash)
        out.append([(split_x, y), (split_x, y2)])
        y += dash + gap
    return out


def _plotter_passes_to_stitched_preview_polylines(
    rows: list[dict[str, Any]],
    settings: Settings,
) -> list[Polyline]:
    out: list[Polyline] = []
    ok_rows = [row for row in rows if bool(row.get("ok"))]
    total = len(ok_rows)
    for index, row in enumerate(ok_rows):
        slot = _item_slot_for_published_output(row, index, total)
        nc_path = _row_path(row, "output_nc")
        if nc_path is None or not nc_path.exists():
            continue
        try:
            polylines = stitch_gcode_polylines.read_draw_polylines(nc_path)
        except Exception:
            continue
        for poly in polylines:
            mapped: Polyline = []
            for x, y in poly:
                local_x = float(x)
                local_y = float(y) - float(settings.work_min_y)
                if slot == "pass_02":
                    local_x = float(settings.work_width) - local_x
                    local_y = float(settings.work_height) - local_y
                    mapped.append((float(settings.work_width) + local_x, local_y))
                else:
                    mapped.append((local_x, local_y))
            if len(mapped) >= 2:
                out.append(mapped)
    return out


def _stitched_plotter_preview_dashed_split(settings: Settings) -> list[Polyline]:
    split_x = float(settings.work_width)
    y = 0.0
    out: list[Polyline] = []
    dash = 8.0
    gap = 5.0
    while y < float(settings.work_height):
        y2 = min(float(settings.work_height), y + dash)
        out.append([(split_x, y), (split_x, y2)])
        y += dash + gap
    return out


def _write_user_plot_preview(
    pack: Path,
    rows: list[dict[str, Any]],
    source_build: SourceBuild,
    settings: Settings,
) -> Path | None:
    out_pdf = pack / "plot_preview.pdf"
    ok_rows = [row for row in rows if bool(row.get("ok"))]
    has_passes = len(ok_rows) > 1 or any(
        _item_slot_for_published_output(row, index, len(ok_rows))
        for index, row in enumerate(ok_rows)
    )
    if has_passes and source_build.page_w_mm > source_build.page_h_mm:
        # User-facing A3 preview is a straight stitched drawing, not a diagnostic
        # plotter-pass bbox comparison. Real plotter pass offsets are still applied
        # only to plotter_pass_01/02 files via the A3 offset settings.
        preview_polylines = list(source_build.polylines)
        preview_polylines.extend(_a3_preview_dashed_split(source_build.page_w_mm, source_build.page_h_mm))
        prep._render_polylines_pdf(
            polylines=preview_polylines,
            out_pdf=out_pdf,
            canvas_bounds_mm=(0.0, source_build.page_w_mm, 0.0, source_build.page_h_mm),
        )
        return out_pdf
    if ok_rows:
        preview = _row_path(ok_rows[0], "clean_preview_pdf") or _row_path(ok_rows[0], "preview_pdf")
        if preview and preview.exists():
            _copy_if_different(preview, out_pdf)
            return out_pdf
    return None


def _safe_remove_pack_child(pack: Path, child: Path) -> None:
    try:
        pack_resolved = pack.resolve()
        child_resolved = child.resolve()
    except OSError:
        return
    if child_resolved == pack_resolved or pack_resolved not in child_resolved.parents:
        return
    if child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
    else:
        child.unlink(missing_ok=True)


def _publish_clean_pack_outputs(
    pack: Path,
    source_pdf: Path,
    source_build: SourceBuild,
    rows: list[dict[str, Any]],
    settings: Settings,
) -> None:
    if settings.keep_debug_artifacts:
        return
    keep_names: set[str] = set()

    source_out = pack / "source.pdf"
    _copy_if_different(source_pdf, source_out)
    keep_names.add(source_out.name)

    preview_out = _write_user_plot_preview(pack, rows, source_build, settings)
    if preview_out is not None:
        keep_names.add(preview_out.name)

    ok_rows = [row for row in rows if bool(row.get("ok"))]
    total = len(ok_rows)
    for index, row in enumerate(ok_rows):
        slot = _item_slot_for_published_output(row, index, total)
        stem = f"plotter_{slot}" if slot else "plotter"
        nc_src = _row_path(row, "output_nc")
        if nc_src and nc_src.exists():
            nc_dst = pack / f"{stem}.nc"
            _copy_if_different(nc_src, nc_dst)
            keep_names.add(nc_dst.name)
        # In clean user-facing packs the plotter input is the .nc file only.
        # The .gcode twin is kept only with --keep-debug-artifacts via the raw
        # intermediate outputs, otherwise it just duplicates content and clutters packs.

    for child in list(pack.iterdir()):
        if child.name in keep_names:
            continue
        _safe_remove_pack_child(pack, child)


def _a3_pass_plotter_offset(settings: Settings, item_name: str) -> tuple[float, float]:
    if item_name == "pass_01":
        return float(settings.a3_pass_01_x_offset_mm), float(settings.a3_pass_01_y_offset_mm)
    if item_name == "pass_02":
        return float(settings.a3_pass_02_x_offset_mm), float(settings.a3_pass_02_y_offset_mm)
    return 0.0, 0.0


def _apply_a3_pass_plotter_offset(
    polylines: list[Polyline],
    item_name: str,
    settings: Settings,
    logs: list[str],
) -> tuple[list[Polyline], dict[str, float]]:
    dx, dy = _a3_pass_plotter_offset(settings, item_name)
    meta = {"x_mm": round(dx, 6), "y_mm": round(dy, 6)}
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return polylines, meta
    shifted = _translate(polylines, dx, dy)
    logs.append(f"A3 plotter pass offset applied for {item_name}: dx={dx:.3f} mm; dy={dy:.3f} mm.")
    return shifted, meta

def _prepare_one_pack(pack: Path, settings: Settings) -> list[dict[str, Any]]:
    report = _load_report(pack)
    source_pdf = _source_pdf_for_pack(pack, report)
    if source_pdf is None:
        return [
            {
                "package": pack.name,
                "ok": False,
                "message": "source PDF not found",
                "old_nc_used_as_source": False,
            }
        ]
    source_build = _build_source(pack, source_pdf, report, settings)
    rows: list[dict[str, Any]] = []
    for item_name in _output_items(report):
        logs = [*source_build.logs]
        if item_name.startswith("pass_"):
            transform = _transform_for_item(report, item_name)
            if transform is None:
                rows.append(
                    {
                        "package": pack.name,
                        "item": item_name,
                        "ok": False,
                        "message": "pass transform not found in report.json; rebuild package first",
                        "old_nc_used_as_source": False,
                    }
                )
                continue
            if source_build.dense_onepass_source:
                final_polys = _map_to_item_dense_onepass(source_build.polylines, transform, settings, logs)
                mode = "a3_dense_onepass_opengost_lff_from_report_logs"
            else:
                final_polys = _map_to_item(source_build.polylines, transform, settings, logs)
                mode = "a3_pass_transform_from_report_logs"
            fit_meta: dict[str, Any] = {
                "transform": transform.__dict__,
                "mode": mode,
            }
        else:
            final_polys, fit_meta = _prepare_a4_page(source_build, settings, logs)
        if item_name.startswith("pass_"):
            final_polys, a3_offset_meta = _apply_a3_pass_plotter_offset(final_polys, item_name, settings, logs)
            fit_meta["a3_plotter_offset_mm"] = a3_offset_meta
        outputs = _write_item_outputs(pack, item_name, final_polys, settings)
        row = {
            "package": pack.name,
            "item": item_name,
            "ok": bool(final_polys),
            "source_pdf": str(source_pdf),
            "old_nc_used_as_source": False,
            "source_algorithm": (
                "clean source onepass + LibreCAD OpenGOST LFF dense text"
                if source_build.preserve_source_frame
                else (
                    "PDF geometry + LibreCAD OpenGOST LFF dense onepass source text"
                    if source_build.dense_onepass_source
                    else "PDF geometry without text + LibreCAD OpenGOST LFF single-line source text"
                )
            ),
            "geometry_polylines": source_build.geometry_polylines,
            "text_lines_found": source_build.text_lines_found,
            "text_lines_rendered": source_build.text_lines_rendered,
            "text_lines_skipped_service": source_build.text_lines_skipped,
            "text_polylines_source": source_build.text_polylines,
            "missing_chars": "".join(source_build.missing_chars),
            "fit_meta": json.dumps(fit_meta, ensure_ascii=False, sort_keys=True),
            **outputs,
        }
        rows.append(row)
        (pack / f"{item_name}_new_algorithm_report.json").write_text(
            json.dumps({**row, "logs": logs, "source_artifacts": source_build.artifacts}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"new-algorithm-v2: {pack.name}/{item_name}")
    _publish_clean_pack_outputs(pack, source_pdf, source_build, rows, settings)
    return rows


def _rebuild_packages(variant_root: Path) -> None:
    rel = variant_root
    try:
        rel = variant_root.relative_to(ROOT)
    except ValueError:
        pass
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_folder1_packages.py"), "--folder", str(rel)],
        cwd=ROOT,
        check=True,
    )



def _remove_variant_root_artifacts(variant_root: Path) -> None:
    for artifact_name in (
        "_new_algorithm_summary.csv",
        "_prepared_summary.csv",
        "_prepared_reports.json",
        "_audit.json",
        "_audit.txt",
        "_audit",
        "_audit_contact.png",
        "_new_algorithm_a3_passes_contact.png",
        "_new_algorithm_pages_contact.png",
    ):
        artifact = variant_root / artifact_name
        if not artifact.exists():
            continue
        if artifact.is_dir() and not artifact.is_symlink():
            shutil.rmtree(artifact)
        else:
            artifact.unlink()

    # Old prepare_folder1_packages output used root-level folders named after the
    # source PDF. New clean output lives only in *_pack folders, so generated
    # non-pack folders containing plotter artifacts are removed in clean mode.
    for child in list(variant_root.iterdir()):
        if not child.is_dir() or child.name.endswith("_pack"):
            continue
        generated_markers = (
            list(child.glob("*.gcode"))
            or list(child.glob("*.nc"))
            or list(child.glob("*.svg"))
            or list(child.glob("summary.csv"))
            or list(child.glob("source_vs_gcode_compare.*"))
            or (child / "pages").exists()
            or (child / "logs").exists()
            or (child / "_candidates").exists()
        )
        if generated_markers:
            shutil.rmtree(child)

def prepare_variant(variant_root: Path, *, rebuild: bool, settings: Settings) -> list[dict[str, Any]]:
    variant_root = variant_root.resolve()
    packs = sorted(variant_root.glob("*_pack"), key=lambda path: path.name.casefold())
    needs_metadata = rebuild or not packs or any(not (pack / "report.json").exists() for pack in packs)
    if needs_metadata:
        _rebuild_packages(variant_root)
        packs = sorted(variant_root.glob("*_pack"), key=lambda path: path.name.casefold())
    rows: list[dict[str, Any]] = []
    for pack in packs:
        rows.extend(_prepare_one_pack(pack, settings))
    summary = variant_root / "_new_algorithm_summary.csv"
    if rows and settings.keep_debug_artifacts:
        fieldnames = sorted({key for row in rows for key in row.keys()})
        with summary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        _remove_variant_root_artifacts(variant_root)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Build source-driven new-algorithm plotter G-code and previews.")
    parser.add_argument("--variant-root", type=Path, default=DEFAULT_VARIANT_ROOT)
    parser.add_argument("--drawing-mode", choices=["auto", "computer_graphics", "descriptive_geometry"], default="auto", help="Frame/layout profile: computer_graphics for KOMPAS drawing sheets, descriptive_geometry for Начерт tasks.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild package metadata before source-driven output.")
    parser.add_argument("--x-compensation-mm", type=float, default=0.0)
    parser.add_argument("--a3-pass-01-x-offset-mm", type=float, default=0.0, help="Extra plotter-only X offset for A3 pass_01; default keeps current output unchanged.")
    parser.add_argument("--a3-pass-01-y-offset-mm", type=float, default=0.0, help="Extra plotter-only Y offset for A3 pass_01; default keeps current output unchanged.")
    parser.add_argument("--a3-pass-02-x-offset-mm", type=float, default=0.0, help="Extra plotter-only X offset for A3 pass_02; default keeps current output unchanged.")
    parser.add_argument("--a3-pass-02-y-offset-mm", type=float, default=0.0, help="Extra plotter-only Y offset for A3 pass_02; default keeps current output unchanged.")
    parser.add_argument(
        "--keep-debug-artifacts",
        action="store_true",
        help="Keep reports, source SVG/PDF/PNG previews and summary CSV instead of publishing only clean pack files.",
    )
    args = parser.parse_args()
    settings = Settings(
        drawing_mode=_normalize_drawing_mode(args.drawing_mode, args.variant_root),
        x_compensation_mm=float(args.x_compensation_mm),
        a3_pass_01_x_offset_mm=float(args.a3_pass_01_x_offset_mm),
        a3_pass_01_y_offset_mm=float(args.a3_pass_01_y_offset_mm),
        a3_pass_02_x_offset_mm=float(args.a3_pass_02_x_offset_mm),
        a3_pass_02_y_offset_mm=float(args.a3_pass_02_y_offset_mm),
        keep_debug_artifacts=bool(args.keep_debug_artifacts),
    )
    rows = prepare_variant(args.variant_root, rebuild=bool(args.rebuild), settings=settings)
    ok_rows = [row for row in rows if bool(row.get("ok"))]
    print(f"drawing_mode={settings.drawing_mode}")
    print(f"new_algorithm_v2_files={len(ok_rows)}")
    if settings.keep_debug_artifacts:
        print(f"summary={args.variant_root / '_new_algorithm_summary.csv'}")
    else:
        print("summary=disabled; use --keep-debug-artifacts to keep reports and intermediate files")
    return 0 if len(ok_rows) == len(rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
