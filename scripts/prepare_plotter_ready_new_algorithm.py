from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
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
METADATA_CACHE_ROOT = ROOT / ".plotter_cache" / "package_metadata"

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
    machine_profile: str = "a4_desktop"
    x_compensation_mm: float = 0.0
    a3_pass_01_x_offset_mm: float = 0.0
    a3_pass_01_y_offset_mm: float = 3.0
    a3_pass_02_x_offset_mm: float = 0.0
    a3_pass_02_y_offset_mm: float = 0.0
    stitch_eps_mm: float = 0.08
    feed_travel: float = 15000.0
    feed_draw: float = 2200.0
    z_down: float = 11.9
    z_up: float = 0.0
    z_feed: float = 2500.0
    home_x: float = 0.0
    home_y: float = 0.0
    home_feed: float = 15000.0
    legacy_z_reference: bool = True
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


def settings_for_machine_profile(
    machine_profile: str = "a4_desktop",
    *,
    drawing_mode: str = "computer_graphics",
    keep_debug_artifacts: bool = False,
) -> Settings:
    """Return one coherent new-algorithm configuration for a physical machine."""
    profile_name = str(machine_profile or "a4_desktop").strip() or "a4_desktop"
    backend.apply_machine_profile(profile_name, logger=None)
    if profile_name.casefold() != "a2_corexy":
        return Settings(
            drawing_mode=drawing_mode,
            machine_profile=profile_name,
            keep_debug_artifacts=bool(keep_debug_artifacts),
        )

    min_x, max_x, min_y, max_y = backend.base_work_area_bounds()
    return Settings(
        drawing_mode=drawing_mode,
        machine_profile=profile_name,
        feed_travel=float(backend.FEED_TRAVEL),
        feed_draw=float(backend.FEED_DRAW),
        z_down=float(backend.Z_DOWN),
        z_up=float(backend.Z_UP),
        z_feed=float(backend.Z_FEED_UP),
        home_x=float(backend.HOME_X),
        home_y=float(backend.HOME_Y),
        home_feed=float(backend.FEED_TRAVEL),
        legacy_z_reference=False,
        work_width=float(max_x) - float(min_x),
        work_height=float(max_y) - float(min_y),
        work_min_y=float(min_y),
        paper_transform="plotter_y_mirror",
        keep_debug_artifacts=bool(keep_debug_artifacts),
    )

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


def _safe_trailer_text(settings: Settings) -> str:
    return "\n".join(
        [
            "; new-source-algorithm safe trailer",
            f"G0 Z{settings.z_up:.4f} F{settings.z_feed:.1f}",
            f"G0 X{settings.home_x:.3f} Y{settings.home_y:.3f} F{settings.home_feed:.1f}",
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
        z_up=settings.z_up,
        z_feed=settings.z_feed,
        home_x=settings.home_x,
        home_y=settings.home_y,
        home_feed=settings.home_feed,
        legacy_z_reference=settings.legacy_z_reference,
    )
    payload = path.read_text(encoding="utf-8")
    payload = (
        "; new-algorithm-v2: source PDF -> geometry_without_pdf_text -> OpenGOST_LFF_singleline_text -> pass transform\n"
        "; old page_01/pass_*.nc are not used as source\n"
        f"; text_font={LFF_FONT_PATH}\n"
        f"; x_compensation_mm={settings.x_compensation_mm:.3f}\n"
        + payload.rstrip()
        + "\n"
        + _safe_trailer_text(settings)
    )
    path.write_text(payload, encoding="utf-8", newline="\n")
    path.with_suffix(".gcode").write_text(payload, encoding="utf-8", newline="\n")


def _load_report(pack: Path) -> dict[str, Any]:
    for report_path in (pack / "report.json", _metadata_cache_path(pack)):
        if report_path.exists():
            return json.loads(report_path.read_text(encoding="utf-8"))
    return {}


def _metadata_cache_path(pack: Path) -> Path:
    try:
        rel = pack.resolve().relative_to(ROOT)
    except ValueError:
        rel = Path(pack.name)
    return METADATA_CACHE_ROOT / rel / "report.json"


def _cache_pack_metadata(pack: Path) -> None:
    report_path = pack / "report.json"
    if not report_path.exists():
        return
    cached = _metadata_cache_path(pack)
    cached.parent.mkdir(parents=True, exist_ok=True)
    _copy_if_different(report_path, cached)


def _source_pdf_for_pack(pack: Path, report: dict[str, Any]) -> Path | None:
    raw = str(report.get("source_pdf", "") or "").strip()
    if raw:
        path = Path(raw)
        if path.exists():
            return path
    for candidate_name in ("source.pdf", "source_kompas.pdf"):
        candidate = pack / candidate_name
        if candidate.exists():
            return candidate
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
    if "пїЅ" in repaired:
        return raw
    return repaired


def _repair_text_line(line: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(line)
    repaired["text"] = _repair_pdf_text_mojibake(repaired.get("text", ""))
    return repaired


def _broken_pdf_text_ratio(lines: list[dict[str, Any]]) -> float:
    total = 0
    broken = 0
    for line in lines:
        text = str(line.get("text", "") or "")
        total += len(text)
        broken += text.count("пїЅ")
    if total <= 0:
        return 0.0
    return broken / total


def _parse_float_attr(attrs: str, name: str) -> float | None:
    match = re.search(rf'{re.escape(name)}="([-0-9.]+)"', attrs)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _extract_poppler_bbox_text_lines(pdf_path: Path) -> list[dict[str, Any]]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return []
    with tempfile.TemporaryDirectory(prefix="plotter_poppler_text_") as tmp:
        out_path = Path(tmp) / "bbox.html"
        result = subprocess.run(
            [pdftotext, "-bbox-layout", "-enc", "UTF-8", str(pdf_path), str(out_path)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0 or not out_path.exists():
            return []
        payload = out_path.read_text(encoding="utf-8", errors="replace")
    pt_to_mm = 25.4 / 72.0
    lines: list[dict[str, Any]] = []
    for match in re.finditer(r"<line\b([^>]*)>(.*?)</line>", payload, flags=re.DOTALL | re.IGNORECASE):
        attrs, body = match.groups()
        x0 = _parse_float_attr(attrs, "xMin")
        y0 = _parse_float_attr(attrs, "yMin")
        x1 = _parse_float_attr(attrs, "xMax")
        y1 = _parse_float_attr(attrs, "yMax")
        if None in (x0, y0, x1, y1):
            continue
        words = [
            _repair_pdf_text_mojibake(html.unescape(word_match.group(1)))
            for word_match in re.finditer(r"<word\b[^>]*>(.*?)</word>", body, flags=re.DOTALL | re.IGNORECASE)
        ]
        text = " ".join(word.strip() for word in words if word.strip())
        text = " ".join(text.split())
        if not text:
            continue
        bbox_pt = [float(x0), float(y0), float(x1), float(y1)]
        bbox_mm = [round(value * pt_to_mm, 4) for value in bbox_pt]
        width = abs(float(x1) - float(x0))
        height = abs(float(y1) - float(y0))
        direction = [0.0, -1.0] if height > max(width * 1.4, 1.0) else [1.0, 0.0]
        lines.append(
            {
                "text": text,
                "confidence": 1.0,
                "source": "pdftotext_bbox_layout",
                "bbox_pt": bbox_pt,
                "bbox_mm": bbox_mm,
                "dir": direction,
                "font_names": ["GOSTTypeA"],
                "font_size_pt_median": max(1.0, min(width, height) if direction == [0.0, -1.0] else height),
            }
        )
    return lines


def _is_service_text(line: dict[str, Any], service_regions: list[tuple[float, float, float, float]]) -> bool:
    text = " ".join(str(line.get("text", "") or "").strip().split())
    if not text:
        return True
    folded = text.casefold()
    bbox = [float(v) for v in line.get("bbox_mm", (0, 0, 0, 0))[:4]]
    # "Формат" is both a removable KOMPAS footer label and the required first
    # column header of a specification table. Preserve only the latter, which
    # is located in the narrow upper-left table header cell.
    if (
        folded.rstrip(".:") == "формат".casefold()
        and len(bbox) == 4
        and 18.0 <= min(bbox[0], bbox[2]) <= 28.5
        and max(bbox[1], bbox[3]) <= 22.5
    ):
        return False
    if any(part.casefold() in folded for part in SERVICE_TEXT_PARTS):
        return True
    if len(bbox) != 4:
        return False
    cx = (bbox[0] + bbox[2]) * 0.5
    cy = (bbox[1] + bbox[3]) * 0.5
    return any(_point_in_box((cx, cy), region, pad=0.5) for region in service_regions)


def _text_lines_for_source(source_pdf: Path) -> tuple[list[dict[str, Any]], int, int]:
    raw_lines = gost._extract_pdf_text_lines(source_pdf)
    if _broken_pdf_text_ratio(raw_lines) > 0.12:
        poppler_lines = _extract_poppler_bbox_text_lines(source_pdf)
        if poppler_lines:
            raw_lines = poppler_lines
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
            "Р Р°Р·СЂР°Р±.": [20.45, 262.38, 37.40, 267.76],
            "РџСЂРѕРІ.": [20.45, 267.38, 37.40, 272.76],
            "Рў.РєРѕРЅС‚СЂ.": [20.45, 272.38, 37.40, 277.76],
            "Рќ.РєРѕРЅС‚СЂ.": [20.45, 282.38, 37.40, 287.76],
            "РЈС‚РІ.": [20.45, 287.38, 37.40, 292.30],
        }
    )
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
    "РёР·Рј.",
    "Р»РёСЃС‚",
    "Р»РёСЃС‚РѕРІ",
    "в„–РґРѕРєСѓРј.",
    "РїРѕРґРї.",
    "РґР°С‚Р°",
    "Р»РёС‚.",
    "РјР°СЃСЃР°",
    "РјР°СЃС€С‚Р°Р±",
    "СЂР°Р·СЂР°Р±.",
    "РїСЂРѕРІ.",
    "С‚.РєРѕРЅС‚СЂ.",
    "РЅ.РєРѕРЅС‚СЂ.",
    "СѓС‚РІ.",
}


def _lff_line_text(line: dict[str, Any]) -> str:
    text = str(line.get("text", "") or "").strip()
    return re.sub(r"^[в–Ўв–Їв—»в–«\s]+(?=\d)", "", text)


DIMENSION_TEXT_ALLOWED_WORDS = {
    "r",
    "СЂ",
    "m",
    "x",
    "С…",
    "С„",
    "lh",
    "rh",
    "РѕС‚РІ",
    "РѕС‚РІ.",
    "С„Р°СЃРєР°",
    "С„Р°СЃРєРё",
}

TITLE_BLOCK_TEXT_MARKERS = (
    "РёР·Рј",
    "Р»РёСЃС‚",
    "Р»РёСЃС‚РѕРІ",
    "РґРѕРєСѓРј",
    "РїРѕРґРї",
    "РґР°С‚Р°",
    "Р»РёС‚",
    "РјР°СЃСЃР°",
    "РјР°СЃС€С‚Р°Р±",
    "СЂР°Р·СЂР°Р±",
    "РїСЂРѕРІ",
    "РєРѕРЅС‚СЂ",
    "СѓС‚РІ",
    "РїРіСѓРїСЃ",
    "СЃС‚Р°Р»СЊ",
    "РіРѕСЃС‚",
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
    words = re.findall(r"[a-zР°-СЏС‘]+", compact, flags=re.IGNORECASE)
    for word in words:
        if word.casefold() not in DIMENSION_TEXT_ALLOWED_WORDS:
            return False
    allowed = set("0123456789.,+-В°'\"/()[]")
    allowed.update("rRСЂР mMxXhHlLРЅРќРѕРћС‚РўРІР’С„Р¤ГГёвЊЂП†О¦Г—С…РҐ")
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


def _is_title_block_label_text(line: dict[str, Any]) -> bool:
    text = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
    if not text:
        return False
    labels_utf = {
        "\u0438\u0437\u043c",
        "\u043b\u0438\u0441\u0442",
        "n\u0434\u043e\u043a\u0443\u043c",
        "n\u0434\u043e\u043a",
        "\u2116\u0434\u043e\u043a\u0443\u043c",
        "\u2116\u0434\u043e\u043a",
        "\u043f\u043e\u0434\u043f",
        "\u0434\u0430\u0442\u0430",
        "\u0440\u0430\u0437\u0440\u0430\u0431",
        "\u043f\u0440\u043e\u0432",
        "\u0442\u043a\u043e\u043d\u0442\u0440",
        "\u043d\u043a\u043e\u043d\u0442\u0440",
        "\u0443\u0442\u0432",
        "\u043b\u0438\u0442",
        "\u043c\u0430\u0441\u0441\u0430",
        "\u043c\u0430\u0441\u0448\u0442\u0430\u0431",
        "\u043b\u0438\u0441\u0442\u043e\u0432",
    }
    if text in labels_utf:
        return True
    labels = {
        "РёР·Рј",
        "Р»РёСЃС‚",
        "nРґРѕРєСѓРј",
        "nРґРѕРє",
        "в„–РґРѕРєСѓРј",
        "в„–РґРѕРє",
        "РїРѕРґРї",
        "РґР°С‚Р°",
        "СЂР°Р·СЂР°Р±",
        "РїСЂРѕРІ",
        "С‚РєРѕРЅС‚СЂ",
        "РЅРєРѕРЅС‚СЂ",
        "СѓС‚РІ",
        "Р»РёС‚",
        "РјР°СЃСЃР°",
        "РјР°СЃС€С‚Р°Р±",
        "Р»РёСЃС‚РѕРІ",
    }
    return text in labels


def _is_specification_left_title_body_text(line: dict[str, Any]) -> bool:
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return False
    x0, y0, _x1, _y1 = bbox
    if not (x0 < 90.0 and y0 >= 266.5):
        return False
    text = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
    return text in {
        "\u0440\u0430\u0437\u0440\u0430\u0431",
        "\u043f\u0440\u043e\u0432",
        "\u0442\u043a\u043e\u043d\u0442\u0440",
        "\u043d\u043a\u043e\u043d\u0442\u0440",
        "\u0443\u0442\u0432",
    }


def _specification_left_title_header_override_lines(line: dict[str, Any]) -> list[dict[str, Any]] | None:
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return None
    x0, y0, _x1, _y1 = bbox
    if not (x0 < 90.0 and 252.0 <= y0 <= 270.5):
        return None
    text_key = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
    cells: dict[str, tuple[str, list[float]]] = {
        "\u0438\u0437\u043c": ("\u0418\u0437\u043c.", [21.35, 257.38, 25.70, 262.93]),
        "\u043b\u0438\u0441\u0442": ("\u041b\u0438\u0441\u0442", [27.05, 257.38, 36.95, 262.93]),
        "\u2116\u0434\u043e\u043a\u0443\u043c": ("\u2116 \u0434\u043e\u043a\u0443\u043c.", [38.00, 257.38, 61.20, 262.93]),
        "n\u0434\u043e\u043a\u0443\u043c": ("\u2116 \u0434\u043e\u043a\u0443\u043c.", [38.00, 257.38, 61.20, 262.93]),
        "\u043f\u043e\u0434\u043f": ("\u041f\u043e\u0434\u043f.", [62.35, 257.38, 74.90, 262.93]),
        "\u0434\u0430\u0442\u0430": ("\u0414\u0430\u0442\u0430", [75.95, 257.38, 84.90, 262.93]),
    }
    combined: dict[str, list[str]] = {
        "\u0438\u0437\u043c\u043b\u0438\u0441\u0442": ["\u0438\u0437\u043c", "\u043b\u0438\u0441\u0442"],
        "\u0438\u0437\u043c\u043b\u0438\u0441\u0442\u2116\u0434\u043e\u043a\u0443\u043c": [
            "\u0438\u0437\u043c",
            "\u043b\u0438\u0441\u0442",
            "\u2116\u0434\u043e\u043a\u0443\u043c",
        ],
        "\u043f\u043e\u0434\u043f\u0434\u0430\u0442\u0430": ["\u043f\u043e\u0434\u043f", "\u0434\u0430\u0442\u0430"],
    }
    keys = combined.get(text_key, [text_key])
    out: list[dict[str, Any]] = []
    for key in keys:
        cell = cells.get(key)
        if cell is None:
            return None
        cell_text, cell_bbox = cell
        patched = dict(line)
        patched["text"] = cell_text
        patched["bbox_mm"] = [round(float(v), 3) for v in cell_bbox]
        patched["stamp_cell_centered"] = True
        patched["spec_left_header_cell"] = True
        patched["text_box_fill"] = LFF_STAMP_FILL
        out.append(patched)
    return out


def _is_specification_right_title_label_text(line: dict[str, Any]) -> bool:
    text = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
    return text in {
        "\u043b\u0438\u0442",
        "\u043c\u0430\u0441\u0441\u0430",
        "\u043c\u0430\u0441\u0448\u0442\u0430\u0431",
        "\u043b\u0438\u0441\u0442",
        "\u043b\u0438\u0441\u0442\u043e\u0432",
    }


def _is_specification_underlined_heading_text(line: dict[str, Any]) -> bool:
    text = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
    return text in {
        "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044f",
        "\u0434\u0435\u0442\u0430\u043b\u0438",
        "\u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u044b",
    }


def _nearest_table_band_around_heading(
    bbox: tuple[float, float, float, float],
    underline_y: float,
    rules: list[HorizontalRule],
) -> tuple[float, float] | None:
    x0, y0, x1, _y1 = bbox
    center_x = (x0 + x1) * 0.5
    upper_candidates: list[float] = []
    lower_candidates: list[float] = []
    for y, rx0, rx1 in rules:
        if not (rx0 - 1.0 <= center_x <= rx1 + 1.0 or _horizontal_overlap(x0, x1, rx0, rx1) > 0.5):
            continue
        if y < y0 - 0.6:
            upper_candidates.append(float(y))
        elif y > underline_y + 0.8:
            lower_candidates.append(float(y))
    if not upper_candidates or not lower_candidates:
        return None
    upper = max(upper_candidates)
    lower = min(lower_candidates)
    if lower - upper < 5.0:
        return None
    return upper, lower


def _adjust_specification_underlined_heading_layout(
    geometry: list[Polyline],
    text_lines: list[dict[str, Any]],
    rules: list[HorizontalRule],
    logs: list[str],
) -> tuple[list[Polyline], list[dict[str, Any]]]:
    if not geometry or not text_lines:
        return geometry, text_lines

    underline_segments: list[tuple[int, float, float, float]] = []
    for index, polyline in enumerate(geometry):
        if len(polyline) != 2:
            continue
        ax, ay = float(polyline[0][0]), float(polyline[0][1])
        bx, by = float(polyline[1][0]), float(polyline[1][1])
        dx = abs(bx - ax)
        dy = abs(by - ay)
        if dy <= 0.12 and 5.0 <= dx <= 70.0:
            underline_segments.append((index, (ay + by) * 0.5, min(ax, bx), max(ax, bx)))

    if not underline_segments:
        return geometry, text_lines

    adjusted_geometry = [list(polyline) for polyline in geometry]
    adjusted_lines: list[dict[str, Any]] = []
    used_underlines: set[int] = set()
    adjusted_count = 0

    for line in text_lines:
        bbox = _line_bbox_mm(line)
        if bbox is None or not _is_specification_underlined_heading_text(line):
            adjusted_lines.append(line)
            continue
        x0, y0, x1, y1 = bbox
        width = max(0.1, x1 - x0)
        height = max(0.1, y1 - y0)
        center_x = (x0 + x1) * 0.5
        best: tuple[float, int, float, float, float] | None = None
        for index, uy, ux0, ux1 in underline_segments:
            if index in used_underlines:
                continue
            underline_width = ux1 - ux0
            if not (width * 0.65 <= underline_width <= max(width * 2.35, width + 24.0)):
                continue
            if not (y1 - 0.2 <= uy <= y1 + 9.0):
                continue
            underline_center_x = (ux0 + ux1) * 0.5
            if abs(underline_center_x - center_x) > max(8.0, width * 0.45):
                continue
            score = abs(uy - y1) + abs(underline_center_x - center_x) * 0.12
            if best is None or score < best[0]:
                best = (score, index, uy, ux0, ux1)
        if best is None:
            adjusted_lines.append(line)
            continue

        _score, underline_index, underline_y, _ux0, _ux1 = best
        band = _nearest_table_band_around_heading(bbox, underline_y, rules)
        if band is None:
            band = _table_row_band_for_line(line, rules)
        if band is None:
            adjusted_lines.append(line)
            continue
        upper, lower = band
        row_height = lower - upper
        if row_height <= height + 1.0:
            adjusted_lines.append(line)
            continue

        target_gap = min(1.15, max(0.65, height * 0.16))
        group_height = height + target_gap
        row_center = (upper + lower) * 0.5
        new_y0 = row_center - group_height * 0.5
        new_y1 = new_y0 + height
        new_underline_y = new_y1 + target_gap

        patched = dict(line)
        patched["bbox_mm"] = [round(float(x0), 4), round(float(new_y0), 4), round(float(x1), 4), round(float(new_y1), 4)]
        patched["skip_table_row_center"] = True
        patched["underlined_heading_centered"] = {
            "row_band_mm": [round(float(upper), 4), round(float(lower), 4)],
            "old_underline_y_mm": round(float(underline_y), 4),
            "new_underline_y_mm": round(float(new_underline_y), 4),
            "gap_mm": round(float(target_gap), 4),
        }
        adjusted_lines.append(patched)

        dy = new_underline_y - underline_y
        adjusted_geometry[underline_index] = [(float(px), float(py) + dy) for px, py in adjusted_geometry[underline_index]]
        used_underlines.add(underline_index)
        adjusted_count += 1

    if adjusted_count:
        logs.append(f"Specification underlined heading layout: adjusted {adjusted_count} heading/underline pair(s).")
    return adjusted_geometry, adjusted_lines


def _center_text_line_in_table_row(line: dict[str, Any], rules: list[HorizontalRule]) -> dict[str, Any]:
    if line.get("skip_table_row_center"):
        return line
    if _is_title_block_label_text(line):
        return line
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
    # Table text must remain geometrically centered.  An optical upward bias
    # made short labels and specification rows visibly hug the upper rule.
    visual_up_shift = 0.0
    new_y0 -= visual_up_shift
    new_y1 -= visual_up_shift
    if abs(new_y0 - y0) <= 0.05 and abs(new_y1 - y1) <= 0.05:
        return line
    patched = dict(line)
    patched["bbox_mm"] = [round(float(x0), 4), round(float(new_y0), 4), round(float(x1), 4), round(float(new_y1), 4)]
    patched["table_row_centered"] = {
        "row_band_mm": [round(float(upper), 4), round(float(lower), 4)],
        "dy_mm": round(float(((new_y0 + new_y1) - (y0 + y1)) * 0.5), 4),
        "visual_up_shift_mm": round(float(visual_up_shift), 4),
    }
    return patched


def _mark_multiline_table_cell_lines(lines: list[dict[str, Any]], rules: list[HorizontalRule]) -> list[dict[str, Any]]:
    """Do not collapse multi-line cells into one centered baseline.

    KOMPAS specification headers and title-block cells can contain two lines in
    one table cell (for example "РџСЂРёРјРµ-" / "С‡Р°РЅРёРµ").  Per-line row centering
    alone moves both lines to the same row center and makes them overlap.  Mark
    such neighboring lines so their original PDF vertical placement is kept.
    """

    if not rules or len(lines) < 2:
        return lines
    bands: list[tuple[int, tuple[float, float], tuple[float, float, float, float]]] = []
    for index, line in enumerate(lines):
        band = _table_row_band_for_line(line, rules)
        bbox = _line_bbox_mm(line)
        if band is None or bbox is None:
            continue
        bands.append((index, band, bbox))
    skip: set[int] = set()
    for pos, (idx_a, band_a, bbox_a) in enumerate(bands):
        ax0, ay0, ax1, ay1 = bbox_a
        aw = max(0.1, ax1 - ax0)
        acx = (ax0 + ax1) * 0.5
        for idx_b, band_b, bbox_b in bands[pos + 1 :]:
            if abs(float(band_a[0]) - float(band_b[0])) > 0.25 or abs(float(band_a[1]) - float(band_b[1])) > 0.25:
                continue
            bx0, by0, bx1, by1 = bbox_b
            bw = max(0.1, bx1 - bx0)
            bcx = (bx0 + bx1) * 0.5
            horizontal_overlap = _horizontal_overlap(ax0, ax1, bx0, bx1)
            same_cell_x = horizontal_overlap >= min(aw, bw) * 0.35 or abs(acx - bcx) <= max(aw, bw) * 0.45
            vertically_separate = min(abs(ay0 - by0), abs(ay1 - by1), abs(((ay0 + ay1) - (by0 + by1)) * 0.5)) > 1.0
            if same_cell_x and vertically_separate:
                skip.add(idx_a)
                skip.add(idx_b)
    if not skip:
        return lines
    marked: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if index in skip:
            patched = dict(line)
            patched["skip_table_row_center"] = True
            marked.append(patched)
        else:
            marked.append(line)
    return marked


def _split_specification_position_designation_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split KOMPAS specification rows merged as "1 MCH00..." into cells.

    Broken ToUnicode maps often make the PDF text extractor report the position
    number and designation as one text line spanning two table cells.  Rendering
    that full string into one bbox squeezes the designation badly.  Split only
    the narrow left-body specification rows where the pattern is unambiguous.
    """

    out: list[dict[str, Any]] = []
    for line in lines:
        text = _lff_line_text(line)
        bbox = _line_bbox_mm(line)
        match = re.match(r"^\s*(\d{1,2})\s+(\S.*\d)\s*$", text)
        if bbox is None or match is None:
            out.append(line)
            continue
        x0, y0, x1, y1 = bbox
        width = x1 - x0
        if not (28.0 <= x0 <= 42.0 and 18.0 <= width <= 58.0):
            out.append(line)
            continue
        pos_text, designation_text = match.groups()
        pos_width = min(6.8, max(4.2, width * 0.15))
        gap = min(2.8, max(1.4, width * 0.06))
        split_x = x0 + pos_width + gap
        if split_x >= x1 - 8.0:
            out.append(line)
            continue
        pos_line = dict(line)
        pos_line["text"] = pos_text
        pos_line["bbox_mm"] = [round(float(x0), 4), round(float(y0), 4), round(float(x0 + pos_width), 4), round(float(y1), 4)]
        pos_line["split_from_spec_line"] = text
        designation_line = dict(line)
        designation_line["text"] = designation_text
        designation_line["bbox_mm"] = [round(float(split_x), 4), round(float(y0), 4), round(float(x1), 4), round(float(y1), 4)]
        designation_line["split_from_spec_line"] = text
        out.extend([pos_line, designation_line])
    return out


def _split_specification_name_quantity_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split a name and trailing quantity merged across specification cells.

    Some KOMPAS PDFs expose ``"Втулка 1"`` or
    ``"Картон А1 ГОСТ 9774-74 1"`` as one text line whose bbox spans the
    ``Наименование`` and ``Кол.`` columns.  The final standalone integer is a
    quantity only when the bbox reaches the narrow quantity column; numbers
    contained inside a designation or product name are left untouched.
    """

    quantity_boxes = [
        bbox
        for line in lines
        if re.fullmatch(r"\s*\d{1,2}\s*", _lff_line_text(line))
        and (bbox := _line_bbox_mm(line)) is not None
        and 170.0 <= bbox[0] <= 181.5
        and bbox[2] <= 182.5
        and bbox[1] < 250.0
    ]
    if quantity_boxes:
        quantity_x0 = sum(box[0] for box in quantity_boxes) / len(quantity_boxes)
        quantity_x1 = sum(box[2] for box in quantity_boxes) / len(quantity_boxes)
    else:
        quantity_x0, quantity_x1 = 176.0, 180.6

    out: list[dict[str, Any]] = []
    for line in lines:
        text = _lff_line_text(line)
        bbox = _line_bbox_mm(line)
        match = re.match(r"^(.+\S)\s+(\d{1,2})\s*$", text)
        if bbox is None or match is None:
            out.append(line)
            continue
        x0, y0, x1, y1 = bbox
        if not (
            100.0 <= x0 <= 125.0
            and 174.0 <= x1 <= 182.5
            and x1 - x0 >= 35.0
            and re.search(r"[A-Za-zА-Яа-яЁё]", match.group(1))
        ):
            out.append(line)
            continue

        name_text, quantity_text = match.groups()
        name_line = dict(line)
        name_line["text"] = name_text
        name_line["bbox_mm"] = [
            round(float(x0), 4),
            round(float(y0), 4),
            round(float(min(169.5, quantity_x0 - 1.0)), 4),
            round(float(y1), 4),
        ]
        name_line["split_from_spec_name_quantity_line"] = text

        quantity_line = dict(line)
        quantity_line["text"] = quantity_text
        quantity_line["bbox_mm"] = [
            round(float(quantity_x0), 4),
            round(float(y0), 4),
            round(float(quantity_x1), 4),
            round(float(y1), 4),
        ]
        quantity_line["split_from_spec_name_quantity_line"] = text
        out.extend([name_line, quantity_line])
    return out




def _is_new_algorithm_specification_source(source_pdf: Path) -> bool:
    try:
        text = str(source_pdf.parent if source_pdf.name.casefold() == "source.pdf" else source_pdf).casefold()
    except Exception:
        return False
    normalized = re.sub(r"[\\/_.\-]+", " ", text)
    return bool(re.search(r"(^|\s)\u0441\u043f(\s|$)", normalized) or "\u0441\u043f\u0435\u0446\u0438\u0444\u0438\u043a" in normalized)


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


def _looks_like_specification_text_source(source_pdf: Path) -> bool:
    try:
        lines, _found, _skipped = _text_lines_for_source(source_pdf)
    except Exception:
        return False

    normalized_tokens: set[str] = set()
    joined_parts: list[str] = []
    for line in lines:
        text = _lff_line_text(line).casefold().replace("\u2116", "n")
        cleaned = re.sub(r"[^0-9a-z\u0430-\u044f\u0451]+", "", text)
        if cleaned:
            normalized_tokens.add(cleaned)
            joined_parts.append(cleaned)
    joined = " ".join(joined_parts)

    header_score = 0
    for token in (
        "\u0437\u043e\u043d\u0430",
        "\u043f\u043e\u0437",
        "\u043e\u0431\u043e\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435",
        "\u043d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435",
        "\u043a\u043e\u043b",
        "\u043f\u0440\u0438\u043c\u0435\u0447\u0430\u043d\u0438\u0435",
    ):
        if token in normalized_tokens:
            header_score += 1

    section_score = 0
    for token in (
        "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044f",
        "\u0434\u0435\u0442\u0430\u043b\u0438",
        "\u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u044b",
    ):
        if token in normalized_tokens or token in joined:
            section_score += 1

    return header_score >= 4 or (header_score >= 2 and section_score >= 1) or section_score >= 2


def _is_new_algorithm_specification(source_pdf: Path, polylines: list[Polyline]) -> bool:
    if _is_new_algorithm_specification_source(source_pdf):
        return True
    if not _looks_like_specification_table_geometry(polylines):
        return False
    return _looks_like_specification_text_source(source_pdf)


_SPECIFICATION_OCR_ENGINE: Any | None = None


def _normalize_specification_ocr_text(text: str, bbox_mm: tuple[float, float, float, float]) -> str:
    """Normalize only unambiguous Cyrillic OCR errors from GOST specification forms."""

    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = value.replace("№°", "№").replace("N°", "№").replace("No", "№")
    compact = value.casefold().replace(" ", "")
    aliases = {
        "одозначение": "Обозначение",
        "разрад.": "Разраб.",
        "доким.": "докум.",
        "лum.": "Лит.",
        "уm6.": "Утв.",
        "н.контр": "Н.контр.",
        "приме-чание": "Примечание",
    }
    value = aliases.get(value.casefold(), value)
    if compact == "dhoe" and bbox_mm[0] < 35.0 and bbox_mm[1] < 25.0:
        value = "Зона"

    value = re.sub(r"(?i)\b[мm][4ч]00", "МЧ00", value)
    value = re.sub(r"(МЧ00\.\d{2})(\d{2})(?=\.)", r"\1.\2", value)
    value = re.sub(r"(?i)\s+[cс][6б]\s*$", " СБ", value)
    value = re.sub(r"(?i)\bгост\b", "ГОСТ", value)
    value = re.sub(r"(?i)\bм(?=\d)", "М", value)
    value = value.replace("x", "×").replace("X", "×")
    return value


def _repair_specification_ocr_cells(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Repair table cells where the GOST numeral shape has one deterministic OCR ambiguity."""

    repaired = [dict(line) for line in lines]
    if not any(_lff_line_text(line).casefold().strip(" .:") == "\u0444\u043e\u0440\u043c\u0430\u0442" for line in repaired):
        repaired.append(
            {
                "text": "\u0424\u043e\u0440\u043c\u0430\u0442",
                "bbox_mm": [20.35, 7.0, 26.2, 19.0],
                "dir": [0.0, -1.0],
                "font": "OpenGOST LFF standard specification header",
                "ocr_confidence": 1.0,
                "text_box_fill": LFF_FILL,
                "skip_table_row_center": True,
            }
        )

    expanded: list[dict[str, Any]] = []
    for line in repaired:
        bbox = _line_bbox_mm(line)
        key = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
        labels: tuple[tuple[str, float, float], ...] = ()
        if bbox is not None and bbox[1] > 250.0 and bbox[0] < 90.0:
            if key.startswith(("\u0438\u0437\u043c\u043b\u0438\u0441\u0442\u2116\u0434\u043e\u043a", "\u04383\u043c\u043b\u0438\u0441\u0442\u2116\u0434\u043e\u043a")):
                labels = (
                    ("\u0418\u0437\u043c.", 21.35, 25.70),
                    ("\u041b\u0438\u0441\u0442", 27.05, 36.95),
                    ("\u2116 \u0434\u043e\u043a\u0443\u043c.", 38.00, 61.20),
                )
            elif key in {"\u0438\u0437\u043c\u043b\u0438\u0441\u0442", "\u04383\u043c\u043b\u0438\u0441\u0442"}:
                labels = (
                    ("\u0418\u0437\u043c.", 21.35, 25.70),
                    ("\u041b\u0438\u0441\u0442", 27.05, 36.95),
                )
            elif key.startswith("\u2116\u0434\u043e\u043a"):
                labels = (("\u2116 \u0434\u043e\u043a\u0443\u043c.", 38.00, 61.20),)
        if not labels or bbox is None:
            expanded.append(line)
            continue
        for label, x0, x1 in labels:
            split_line = dict(line)
            split_line["text"] = label
            split_line["bbox_mm"] = [x0, bbox[1], x1, bbox[3]]
            split_line["dir"] = [1.0, 0.0]
            split_line["text_box_fill"] = LFF_STAMP_FILL
            split_line["skip_table_row_center"] = True
            split_line["stamp_cell_centered"] = True
            expanded.append(split_line)
    repaired = expanded

    right_title_spans: list[tuple[float, float]] = []
    left_title_spans: list[tuple[float, float]] = []
    for line in repaired:
        bbox = _line_bbox_mm(line)
        if bbox is None or bbox[1] <= 250.0:
            continue
        key = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
        if bbox[0] > 150.0 and key in {"\u043b\u0438\u0442", "\u043b\u0438\u0441\u0442", "\u043b\u0438\u0441\u0442\u043e\u0432"}:
            right_title_spans.append((bbox[1], bbox[3]))
        if bbox[0] < 90.0 and (
            key in {"\u0438\u0437\u043c", "\u043b\u0438\u0441\u0442", "\u043f\u043e\u0434\u043f", "\u0434\u0430\u0442\u0430"}
            or key.startswith("\u2116\u0434\u043e\u043a")
        ):
            left_title_spans.append((bbox[1], bbox[3]))

    if right_title_spans:
        right_title_y0 = min(span[0] for span in right_title_spans)
        right_title_y1 = max(span[1] for span in right_title_spans)
    elif left_title_spans:
        right_title_y0 = max(span[1] for span in left_title_spans)
        right_title_y1 = right_title_y0 + 5.5
    else:
        right_title_y0, right_title_y1 = 267.0, 272.5

    normalized_title_lines: list[dict[str, Any]] = []
    for line in repaired:
        bbox = _line_bbox_mm(line)
        key = _lff_line_text(line).replace(" ", "").replace(".", "").replace(":", "").casefold()
        if bbox is not None and bbox[1] > 250.0 and bbox[0] < 90.0 and (
            key in {"\u0438\u0437\u043c", "\u043b\u0438\u0441\u0442", "\u043f\u043e\u0434\u043f", "\u0434\u0430\u0442\u0430"}
            or key.startswith("\u2116\u0434\u043e\u043a")
        ):
            fixed = {
                "\u0438\u0437\u043c": ("\u0418\u0437\u043c.", 21.35, 25.70),
                "\u043b\u0438\u0441\u0442": ("\u041b\u0438\u0441\u0442", 27.05, 36.95),
                "\u043f\u043e\u0434\u043f": ("\u041f\u043e\u0434\u043f.", 62.35, 74.90),
                "\u0434\u0430\u0442\u0430": ("\u0414\u0430\u0442\u0430", 75.95, 84.90),
            }.get(key, ("\u2116 \u0434\u043e\u043a\u0443\u043c.", 38.00, 61.20))
            patched = dict(line)
            patched["text"] = fixed[0]
            patched["bbox_mm"] = [fixed[1], bbox[1], fixed[2], bbox[3]]
            patched["dir"] = [1.0, 0.0]
            patched["text_box_fill"] = LFF_STAMP_FILL
            patched["skip_table_row_center"] = True
            patched["stamp_cell_centered"] = True
            normalized_title_lines.append(patched)
            continue
        if bbox is not None and bbox[1] > 250.0 and bbox[0] > 150.0 and key in {
            "\u043b\u0438\u0442",
            "\u043b\u0438\u0441\u0442",
            "\u043b\u0438\u0441\u0442\u043e\u0432",
        }:
            continue
        normalized_title_lines.append(line)
    for label, label_bbox in (
        ("\u041b\u0438\u0442.", [155.20, right_title_y0, 170.00, right_title_y1]),
        ("\u041b\u0438\u0441\u0442", [170.20, right_title_y0, 187.00, right_title_y1]),
        ("\u041b\u0438\u0441\u0442\u043e\u0432", [187.20, right_title_y0, 204.70, right_title_y1]),
    ):
        normalized_title_lines.append(
            {
                "text": label,
                "bbox_mm": label_bbox,
                "dir": [1.0, 0.0],
                "font": "OpenGOST LFF standard specification title header",
                "ocr_confidence": 1.0,
                "text_box_fill": LFF_STAMP_FILL,
                "skip_table_row_center": True,
                "stamp_cell_centered": True,
            }
        )
    repaired = normalized_title_lines

    details_y: float | None = None
    for line in repaired:
        if _lff_line_text(line).casefold().strip(" .:") == "\u0434\u0435\u0442\u0430\u043b\u0438":
            bbox = _line_bbox_mm(line)
            if bbox is not None:
                details_y = (bbox[1] + bbox[3]) * 0.5
                break

    for line in repaired:
        bbox = _line_bbox_mm(line)
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        cx = (x0 + x1) * 0.5
        cy = (y0 + y1) * 0.5
        text = _lff_line_text(line)
        if 19.0 <= cx <= 30.5 and re.fullmatch(r"[AА][234]", text):
            line["text"] = f"A{text[-1]}"
            line["text_box_fill"] = 0.50
        if 170.0 <= cx <= 182.5 and text == "7" and (x1 - x0) <= (y1 - y0) * 0.75:
            line["text"] = "1"

    if details_y is None:
        return repaired
    designations = []
    for line in repaired:
        bbox = _line_bbox_mm(line)
        if bbox is None:
            continue
        cy = (bbox[1] + bbox[3]) * 0.5
        if details_y < cy < 245.0 and re.match(r"^\s*\u041c\u0427\d", _lff_line_text(line)):
            designations.append((cy, line))
    designations.sort(key=lambda item: item[0])
    if len(designations) < 3:
        return repaired

    standard_heading_y: float | None = None
    for line in repaired:
        bbox = _line_bbox_mm(line)
        if bbox is None:
            continue
        if _lff_line_text(line).casefold().strip(" .:") == "\u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u043d\u044b\u0435 \u0438\u0437\u0434\u0435\u043b\u0438\u044f":
            standard_heading_y = (bbox[1] + bbox[3]) * 0.5
            break

    row_anchors = list(designations)
    if standard_heading_y is not None:
        for line in repaired:
            bbox = _line_bbox_mm(line)
            if bbox is None:
                continue
            x0, y0, x1, y1 = bbox
            cy = (y0 + y1) * 0.5
            text = _lff_line_text(line)
            if (
                cy > standard_heading_y
                and 105.0 <= x0 <= 135.0
                and x1 <= 175.0
                and re.match(r"^(\u0411\u043e\u043b\u0442|\u0413\u0430\u0439\u043a\u0430|\u0428\u0430\u0439\u0431\u0430|\u0428\u043f\u0438\u043b\u044c\u043a\u0430|\u0412\u0438\u043d\u0442)\b", text)
            ):
                row_anchors.append((cy, line))
    row_anchors.sort(key=lambda item: item[0])

    filtered: list[dict[str, Any]] = []
    for line in repaired:
        bbox = _line_bbox_mm(line)
        if bbox is None:
            filtered.append(line)
            continue
        cx = (bbox[0] + bbox[2]) * 0.5
        cy = (bbox[1] + bbox[3]) * 0.5
        if 30.0 <= cx <= 42.5 and cy > details_y and re.fullmatch(r"\d{1,2}|[-\u2014]", _lff_line_text(line)):
            continue
        filtered.append(line)
    repaired = filtered

    for expected, (_anchor_y, anchor) in enumerate(row_anchors, start=1):
        anchor_bbox = _line_bbox_mm(anchor)
        if anchor_bbox is None:
            continue
        repaired.append(
            {
                "text": str(expected),
                "bbox_mm": [32.5, anchor_bbox[1], 40.5, anchor_bbox[3]],
                "dir": [1.0, 0.0],
                "font": "OpenGOST LFF reconstructed specification position",
                "ocr_confidence": 1.0,
                "text_box_fill": LFF_STAMP_FILL,
            }
        )
    return repaired


def _specification_ocr_text_lines(source_pdf: Path, logs: list[str]) -> list[dict[str, Any]]:
    """Read a vector-only specification with Cyrillic OCR for later LFF rendering."""

    global _SPECIFICATION_OCR_ENGINE
    try:
        import numpy as np
        from rapidocr import EngineType, LangRec, ModelType, OCRVersion, RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            'Vector-only specifications require the photo extra: pip install -e ".[photo]"'
        ) from exc

    if _SPECIFICATION_OCR_ENGINE is None:
        _SPECIFICATION_OCR_ENGINE = RapidOCR(
            params={
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.CYRILLIC,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
            }
        )

    with fitz.open(source_pdf) as document:
        page = document[0]
        page_w_mm = float(page.rect.width) * lff_text.PT_TO_MM
        page_h_mm = float(page.rect.height) * lff_text.PT_TO_MM
        pixmap = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), alpha=False, colorspace=fitz.csGRAY)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)

    result = _SPECIFICATION_OCR_ENGINE(image)
    boxes = list(result.boxes) if result is not None and result.boxes is not None else []
    texts = list(result.txts) if result is not None and result.txts is not None else []
    scores = list(result.scores) if result is not None and result.scores is not None else []
    x_scale = page_w_mm / max(1, pixmap.width)
    y_scale = page_h_mm / max(1, pixmap.height)
    lines: list[dict[str, Any]] = []
    rejected = 0
    for box, raw_text, score in zip(boxes, texts, scores):
        xs = [float(point[0]) * x_scale for point in box]
        ys = [float(point[1]) * y_scale for point in box]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        if float(score) < 0.58 or bbox[2] < 19.5 or bbox[0] > 205.5:
            rejected += 1
            continue
        text = _normalize_specification_ocr_text(str(raw_text), bbox)
        if not text:
            rejected += 1
            continue
        is_vertical_header = (
            bbox[1] < 25.0
            and bbox[0] < 42.5
            and (bbox[3] - bbox[1]) > (bbox[2] - bbox[0]) * 1.35
        )
        direction = [0.0, -1.0] if is_vertical_header else [1.0, 0.0]
        line = {
            "text": text,
            "bbox_mm": [round(float(value), 4) for value in bbox],
            "dir": direction,
            "font": "RapidOCR PP-OCRv5 Cyrillic -> OpenGOST LFF",
            "ocr_confidence": round(float(score), 4),
        }
        if bbox[1] < page_h_mm - 45.0:
            line["text_box_fill"] = LFF_FILL
        if _is_service_text(line, []):
            rejected += 1
            continue
        lines.append(line)
    lines = _repair_specification_ocr_cells(lines)
    lines.sort(key=lambda line: ((_line_bbox_mm(line) or (0.0, 0.0, 0.0, 0.0))[1], (_line_bbox_mm(line) or (0.0, 0.0, 0.0, 0.0))[0]))
    if len(lines) < 8:
        raise RuntimeError(f"Cyrillic specification OCR produced only {len(lines)} reliable lines: {source_pdf}")
    logs.append(
        "Specification Cyrillic OCR fallback: "
        f"accepted={len(lines)}; rejected={rejected}; model=PP-OCRv5 cyrillic; "
        "OCR supplies text and coordinates only; all glyphs are rendered with OpenGOST LFF."
    )
    return lines


def _specification_structural_geometry_only(polylines: list[Polyline], logs: list[str]) -> list[Polyline]:
    """Keep specification rules/underlines and discard all old vector glyph contours."""

    kept: list[Polyline] = []
    removed = 0
    for polyline in polylines:
        for first, second in zip(polyline, polyline[1:]):
            x0, y0 = float(first[0]), float(first[1])
            x1, y1 = float(second[0]), float(second[1])
            dx = abs(x1 - x0)
            dy = abs(y1 - y0)
            if (dy <= 0.18 and dx >= 4.0) or (dx <= 0.18 and dy >= 4.0):
                kept.append([(x0, y0), (x1, y1)])
            else:
                removed += 1
    logs.append(
        "Vector-only specification structure filter: "
        f"kept_rules={len(kept)}; removed_old_glyph_segments={removed}."
    )
    return kept


def _clean_specification_form_geometry(
    polylines: list[Polyline],
    page_w_mm: float,
    page_h_mm: float,
    logs: list[str],
) -> list[Polyline]:
    """Remove the PDF page frame and KOMPAS service tables outside x=20..205 mm."""

    main_x0 = 20.0
    main_x1 = min(205.0, float(page_w_mm) - 5.0)
    cleaned: list[Polyline] = []
    removed = 0
    for polyline in polylines:
        for first, second in zip(polyline, polyline[1:]):
            ax, ay = float(first[0]), float(first[1])
            bx, by = float(second[0]), float(second[1])
            span_x = abs(bx - ax)
            span_y = abs(by - ay)
            page_perimeter = (
                (span_x >= 100.0 and (max(ay, by) <= 1.5 or min(ay, by) >= float(page_h_mm) - 1.5))
                or (span_y >= 150.0 and (max(ax, bx) <= 1.5 or min(ax, bx) >= float(page_w_mm) - 1.5))
            )
            if page_perimeter or max(ax, bx) < main_x0 - 0.15 or min(ax, bx) > main_x1 + 0.15:
                if span_y >= 4.0 and span_x <= 0.25 and abs(((ax + bx) * 0.5) - main_x1) <= 1.0:
                    cleaned.append([(main_x1, ay), (main_x1, by)])
                    continue
                removed += 1
                continue
            dx = bx - ax
            if abs(dx) <= 1e-9:
                if abs(ax - main_x0) <= 1.0:
                    ax = bx = main_x0
                elif abs(ax - main_x1) <= 1.0:
                    ax = bx = main_x1
                elif not (main_x0 - 0.15 <= ax <= main_x1 + 0.15):
                    removed += 1
                    continue
                cleaned.append([(ax, ay), (bx, by)])
                continue
            t0 = max(0.0, min(1.0, (main_x0 - ax) / dx))
            t1 = max(0.0, min(1.0, (main_x1 - ax) / dx))
            enter, leave = sorted((t0, t1))
            if max(ax, bx) <= main_x1 and min(ax, bx) >= main_x0:
                enter, leave = 0.0, 1.0
            if leave - enter <= 1e-8:
                removed += 1
                continue
            start = (ax + dx * enter, ay + (by - ay) * enter)
            end = (ax + dx * leave, ay + (by - ay) * leave)
            cleaned.append([start, end])
    logs.append(
        "Specification form crop: kept main GOST table x=20..205 mm; "
        f"removed page-frame/service segments={removed}."
    )
    return cleaned

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
        gap_eps=18.0,
        horizontal=False,
    )
    snapped = [*kept, *snapped_horizontal, *snapped_vertical]
    snapped = _restore_specification_left_title_block_rows(snapped, logs)
    snapped = _restore_specification_position_column_grid_breaks(snapped, logs)
    logs.append(
        "Specification grid snap: "
        f"classified_segments={classified}; "
        f"horizontal={len(horizontal_segments)}->{len(snapped_horizontal)}; "
        f"vertical={len(vertical_segments)}->{len(snapped_vertical)}; "
        f"kept_non_axis={len(kept)}; total={len(polylines)}->{len(snapped)}."
    )
    return snapped


def _restore_specification_position_column_grid_breaks(
    polylines: list[Polyline],
    logs: list[str],
) -> list[Polyline]:
    """Restore table rules cut out underneath specification position numbers.

    Text cleanup removes source glyph outlines before the form grid is snapped.
    In some KOMPAS exports a two-digit position (for example ``10`` or ``12``)
    touches the lower rule closely enough that the cleanup leaves a gap exactly
    across the narrow position column.  That missing rule then makes the row
    detector join two cells and vertically misplace the number.  Reconnect only
    gaps bounded by the standard position-column borders; no text geometry or
    other table cells are changed.
    """

    horizontal_rows: list[tuple[float, float, float]] = []
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        for a, b in zip(polyline, polyline[1:]):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            if abs(bx - ax) < 1.2 or abs(by - ay) > 0.12:
                continue
            horizontal_rows.append(((ay + by) * 0.5, min(ax, bx), max(ax, bx)))

    additions: list[Polyline] = []
    for row_y in _dedupe_rule_ys([row[0] for row in horizontal_rows], eps=0.24):
        intervals = [
            (x0, x1)
            for y, x0, x1 in horizontal_rows
            if abs(float(y) - float(row_y)) <= 0.24
        ]
        merged = _merge_grid_intervals(intervals, gap_eps=0.62)
        for left, right in zip(merged, merged[1:]):
            gap_x0 = float(left[1])
            gap_x1 = float(right[0])
            gap_width = gap_x1 - gap_x0
            if not (4.0 <= gap_width <= 12.0):
                continue
            if not (30.0 <= gap_x0 <= 35.5 and 38.0 <= gap_x1 <= 43.5):
                continue
            additions.append([(gap_x0, float(row_y)), (gap_x1, float(row_y))])

    if additions:
        logs.append(
            "Specification position-column grid repair: restored "
            f"{len(additions)} horizontal rule gap(s) below numeric cells."
        )
        return [*polylines, *additions]
    return polylines


def _restore_specification_left_title_block_rows(polylines: list[Polyline], logs: list[str]) -> list[Polyline]:
    if not polylines:
        return polylines
    try:
        min_x, _min_y, _max_x, max_y = _bounds(polylines)
    except Exception:
        return polylines

    bottom_y0 = float(max_y) - 46.0
    bottom_y1 = float(max_y) + 0.6
    left_x_limit = float(min_x) + 86.0
    vertical_xs: list[float] = []
    row_ys: list[float] = []
    horizontal_segments: list[tuple[float, float, float]] = []

    for polyline in polylines:
        if len(polyline) < 2:
            continue
        for a, b in zip(polyline, polyline[1:]):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            sx0, sx1 = sorted((ax, bx))
            sy0, sy1 = sorted((ay, by))
            dx = abs(bx - ax)
            dy = abs(by - ay)
            if dy <= 0.12 and dx >= 3.0 and bottom_y0 <= ((ay + by) * 0.5) <= bottom_y1:
                y = (ay + by) * 0.5
                row_ys.append(y)
                horizontal_segments.append((y, sx0, sx1))
            elif dx <= 0.12 and dy >= 8.0 and sx0 <= left_x_limit and sy1 >= bottom_y0 and sy0 <= bottom_y1:
                vertical_xs.append((ax + bx) * 0.5)

    xs = [x for x in _dedupe_rule_ys(vertical_xs, eps=0.35) if float(min_x) - 0.8 <= x <= left_x_limit]
    ys = [y for y in _dedupe_rule_ys(row_ys, eps=0.25) if bottom_y0 <= y <= bottom_y1]
    if len(xs) < 3 or len(ys) < 3:
        return polylines

    title_x0 = float(min(xs))
    title_x1 = float(max(xs))
    if title_x1 - title_x0 < 20.0:
        return polylines

    rebuilt: list[Polyline] = []
    removed_fragments = 0
    for polyline in polylines:
        if len(polyline) == 2:
            ax, ay = float(polyline[0][0]), float(polyline[0][1])
            bx, by = float(polyline[1][0]), float(polyline[1][1])
            sx0, sx1 = sorted((ax, bx))
            dx = abs(bx - ax)
            dy = abs(by - ay)
            mid_y = (ay + by) * 0.5
            inside_title_rows = bottom_y0 <= mid_y <= bottom_y1
            inside_title_x = sx0 >= title_x0 - 0.8 and sx1 <= title_x1 + 0.8
            if dy <= 0.12 and dx >= 1.0 and inside_title_rows and inside_title_x:
                removed_fragments += 1
                continue
        rebuilt.append(polyline)

    additions = [[(title_x0, float(y)), (title_x1, float(y))] for y in ys]
    logs.append(
        "Specification title-block row restore: "
        f"rebuilt {len(additions)} full left-stamp horizontal row(s); "
        f"removed_fragments={removed_fragments}."
    )
    return [*rebuilt, *additions]


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

    default_fill = LFF_STAMP_FILL if _looks_like_lff_stamp_cell(line, page_w_mm, page_h_mm) else LFF_FILL
    try:
        fill = float(line.get("text_box_fill", default_fill) or default_fill)
    except (TypeError, ValueError):
        fill = default_fill
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
    free_x = max(0.0, box_width - rendered_width)
    text_align = str(line.get("text_align", "center") or "center").casefold()
    if text_align == "left":
        try:
            left_pad = float(line.get("text_left_pad_mm", 0.65) or 0.65)
        except (TypeError, ValueError):
            left_pad = 0.65
        local_x0 = min(max(0.0, left_pad), free_x)
    elif text_align == "right":
        try:
            right_pad = float(line.get("text_right_pad_mm", 0.65) or 0.65)
        except (TypeError, ValueError):
            right_pad = 0.65
        local_x0 = max(0.0, free_x - max(0.0, right_pad))
    else:
        local_x0 = free_x * 0.5
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


def _is_top_service_designation_line(line: dict[str, Any]) -> bool:
    text = _lff_line_text(line)
    key = re.sub(r"\s+", "", str(text or "")).casefold().replace(",", ".")
    if not re.search(r"\d", key):
        return False
    if not (
        "\u043c\u0447" in key
        or "\u043a\u043d\u0433" in key
        or "mch" in key
        or "kng" in key
    ):
        return False
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return False
    x0, y0, x1, y1 = bbox
    if not (18.0 <= x0 <= 105.0 and x1 <= 110.0 and y0 <= 18.0 and y1 <= 30.0):
        return False
    return True


def _is_top_service_designation_fitz_line(line: dict[str, object]) -> bool:
    try:
        rect = fitz.Rect(line["bbox"])  # type: ignore[arg-type]
    except Exception:
        return False
    line_mm = {
        "text": _repair_pdf_text_mojibake(str(line.get("text", ""))),
        "bbox_mm": [
            float(rect.x0) * lff_text.PT_TO_MM,
            float(rect.y0) * lff_text.PT_TO_MM,
            float(rect.x1) * lff_text.PT_TO_MM,
            float(rect.y1) * lff_text.PT_TO_MM,
        ],
        "dir": line.get("dir", (1.0, 0.0)),
    }
    return _is_top_service_designation_line(line_mm)


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


def _center_top_service_designation_line(line: dict[str, Any]) -> dict[str, Any]:
    if not _is_top_service_designation_line(line):
        return line
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return line
    frame_x0, frame_y0, frame_x1, frame_y1 = 24.0, 5.5033, 90.5090, 19.4730
    pad_x = 1.25
    pad_y = 1.10
    patched = dict(line)
    patched["bbox_mm"] = [
        round(frame_x0 + pad_x, 3),
        round(frame_y0 + pad_y, 3),
        round(frame_x1 - pad_x, 3),
        round(frame_y1 - pad_y, 3),
    ]
    patched["text_align"] = "center"
    patched["top_service_designation_centered"] = {
        "source_bbox_mm": [round(float(v), 3) for v in bbox],
        "frame_bbox_mm": [round(frame_x0, 3), round(frame_y0, 3), round(frame_x1, 3), round(frame_y1, 3)],
    }
    return patched


def _should_preserve_specification_title_stamp_line(line: dict[str, Any]) -> bool:
    return bool(
        _is_specification_right_title_label_text(line)
        or _is_specification_left_title_body_text(line)
        or _is_top_service_designation_line(line)
    )


def _is_a4_left_stamp_person_line(line: dict[str, Any]) -> bool:
    bbox = _line_bbox_mm(line)
    if bbox is None:
        return False
    x0, y0, x1, y1 = bbox
    if not (35.0 <= x0 <= 86.0 and 258.0 <= y0 <= 278.5 and x1 <= 92.0):
        return False
    text = _lff_line_text(line).strip()
    if not text or not re.search(r"[A-Za-zА-Яа-яЁё]", text):
        return False
    key = gost._stamp_lookup_key(text)
    if key in {gost._stamp_lookup_key(label) for label in gost.STAMP_ROLE_LABELS}:
        return False
    if key in {
        "изм",
        "лист",
        "nдокум",
        "nдок",
        "№докум",
        "№док",
        "подп",
        "дата",
        "лит",
        "масса",
        "масштаб",
        "листов",
    }:
        return False
    return True


def _apply_a4_left_stamp_person_alignment(line: dict[str, Any]) -> dict[str, Any]:
    if not _is_a4_left_stamp_person_line(line):
        return line
    patched = dict(line)
    patched["text_align"] = "left"
    patched["text_left_pad_mm"] = 0.75
    patched["text_box_fill"] = min(float(patched.get("text_box_fill", LFF_STAMP_FILL) or LFF_STAMP_FILL), LFF_STAMP_FILL)
    patched["a4_left_stamp_person_left_aligned"] = True
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
    prepared_text_lines = list(text_lines)
    if table_rules:
        prepared_text_lines = _split_specification_position_designation_lines(prepared_text_lines)
        prepared_text_lines = _split_specification_name_quantity_lines(prepared_text_lines)
        prepared_text_lines = _mark_multiline_table_cell_lines(prepared_text_lines, table_rules)
    for source_line in prepared_text_lines:
        if _is_top_service_designation_line(source_line):
            logger(
                "Top service designation rerouted through centered LFF overlay: "
                f"'{lff_text._line_display_text(source_line)}'."
            )
            source_line = _center_top_service_designation_line(source_line)
        if center_a3_top_left_title:
            source_line = _center_a3_top_left_title_line(source_line)
        source_line = _apply_a4_left_stamp_person_alignment(source_line)
        if table_rules and not _should_preserve_specification_title_stamp_line(source_line):
            centered_line = _center_text_line_in_table_row(source_line, table_rules)
            if centered_line is not source_line:
                table_centered += 1
            source_line = centered_line
        if use_stamp_overrides and table_rules:
            left_header_lines = _specification_left_title_header_override_lines(source_line)
            if left_header_lines is not None:
                routed_lines = left_header_lines
            elif _is_specification_right_title_label_text(source_line) or _is_specification_left_title_body_text(source_line):
                routed_lines = [source_line]
            else:
                routed_lines = gost._stamp_centered_lines(source_line)
        else:
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


def _strip_top_service_designation_geometry(polylines: list[Polyline], logs: list[str]) -> list[Polyline]:
    kept: list[Polyline] = []
    removed = 0
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        xs = [float(point[0]) for point in polyline]
        ys = [float(point[1]) for point in polyline]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        width = x1 - x0
        height = y1 - y0
        axis_aligned_frame_line = (height <= 0.12 and width >= 8.0) or (width <= 0.12 and height >= 8.0)
        inside_top_service_box = (
            -1.0 <= x0 <= 112.0
            and x1 <= 112.0
            and -1.0 <= y0 <= 32.0
            and y1 <= 32.0
            and width <= 105.0
            and height <= 31.0
        )
        if inside_top_service_box and not axis_aligned_frame_line:
            removed += 1
            continue
        kept.append(polyline)
    if removed:
        logs.append(f"Top service designation geometry stripped: removed {removed} polyline(s).")
    return kept


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
    if _is_new_algorithm_specification_source(source_pdf):
        # A saved clean-source file can contain remnants produced by an older
        # specification text/grid pass. Reusing it makes those remnants part
        # of the next generation and overlays fresh LFF text on top. Always
        # rebuild specifications from the current source PDF instead.
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


def _specification_clean_background_from_source(
    source_pdf: Path,
    text_lines: list[dict[str, Any]],
    logs: list[str],
) -> tuple[list[Polyline], dict[str, int], float, float] | None:
    """Return a text-free specification grid when a reliable text layer exists.

    KOMPAS specification PDFs can contain both an extractable text layer and
    vector strokes for the same glyphs.  Removing whole SVG paths by bounding
    box leaves small glyph fragments behind because a path may contain strokes
    from several characters.  Reading drawing segments directly from the PDF
    lets the existing clean-background filter remove those fragments before the
    single-line LFF text is overlaid.

    A specification without an extractable text layer must keep its original
    vector glyphs.  In that case this function deliberately returns ``None``;
    snapping its near-axis strokes would turn letters and digits into grid
    fragments.
    """

    if not text_lines:
        logs.append(
            "Specification text-layer background route skipped: no reliable "
            "extractable text; preserve original vector glyph geometry."
        )
        return None

    text_doc = fitz.open(source_pdf)
    try:
        geometry, meta, page_w_mm, page_h_mm = _clean_background_polylines_from_pdf(
            source_pdf,
            text_doc,
            logs,
        )
    finally:
        text_doc.close()
    if not geometry:
        logs.append(
            "Specification text-layer background route produced no geometry; "
            "fall back to bounded SVG text cleanup."
        )
        return None
    logs.append(
        "Specification text-layer background route: clean PDF drawing segments "
        "will be combined with one LFF text layer."
    )
    return geometry, meta, page_w_mm, page_h_mm


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
        prepared_lines: list[dict[str, Any]] = []
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
            prepared_lines.append(line_mm)
        if table_rules:
            prepared_lines = _split_specification_position_designation_lines(prepared_lines)
            prepared_lines = _split_specification_name_quantity_lines(prepared_lines)
            prepared_lines = _mark_multiline_table_cell_lines(prepared_lines, table_rules)
        for line_mm in prepared_lines:
            if _is_top_service_designation_line(line_mm):
                logs.append(
                    "Top service designation rerouted through centered LFF overlay: "
                    f"'{lff_text._line_display_text(line_mm)}'."
                )
                line_mm = _center_top_service_designation_line(line_mm)
            line_mm = _apply_a4_left_stamp_person_alignment(line_mm)
            text = str(line_mm["text"])
            rect = fitz.Rect(line_mm.get("bbox", (0, 0, 0, 0)))  # type: ignore[arg-type]
            if table_rules and not _should_preserve_specification_title_stamp_line(line_mm):
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
                    "dir": line_mm.get("dir"),
                    "font": str(LFF_FONT_PATH),
                    "fill": line_fill,
                }
            )
            logs.append(
                f"OpenGOST LFF experiment text: '{lff_text._line_display_text(line_mm)}' -> "
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
        if _is_top_service_designation_line(line):
            logger(f"Top service designation source geometry removed before centered LFF overlay: '{lff_text._line_display_text(line)}'.")
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
    if not is_specification:
        geometry = _strip_top_service_designation_geometry(geometry, logs)
    if is_specification and text_lines_for_cleanup:
        geometry = _snap_specification_table_grid_polylines(geometry, logs)
    elif is_specification:
        logs.append(
            "Specification grid snap skipped: no reliable text layer, so vector "
            "glyph strokes must not be classified as table rules."
        )
    table_rules = _horizontal_table_rules_from_polylines(geometry)
    text_lines_for_render = text_lines_for_cleanup
    if is_specification:
        geometry, text_lines_for_render = _adjust_specification_underlined_heading_layout(
            geometry,
            text_lines_for_render,
            table_rules,
            logs,
        )
        table_rules = _horizontal_table_rules_from_polylines(geometry)
    text_polys, accepted_text, missing_chars = _make_lff_opengost_text_strokes(
        text_lines_for_render,
        page_w_mm,
        page_h_mm,
        logs.append,
        normalize_dimension_text=(_is_computer_graphics_mode(settings) and not is_specification),
        table_rules=table_rules,
    )
    text_lines_found = _cleanup_lines_found
    text_lines_skipped = _cleanup_lines_skipped
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
    is_specification = _is_new_algorithm_specification(source_pdf, geometry)
    if is_specification:
        clean_specification = _specification_clean_background_from_source(source_pdf, text_lines, logs)
        if clean_specification is not None:
            geometry, specification_background_meta, page_w_mm, page_h_mm = clean_specification
            cleanup_meta = dict(cleanup_meta)
            cleanup_meta["specification_text_layer_background"] = specification_background_meta
        else:
            text_lines = _specification_ocr_text_lines(source_pdf, logs)
            geometry = _remove_existing_text_geometry(geometry, text_lines, logs.append)
            geometry = _specification_structural_geometry_only(geometry, logs)
        geometry = _clean_specification_form_geometry(geometry, page_w_mm, page_h_mm, logs)
        geometry = _snap_specification_table_grid_polylines(geometry, logs)
    else:
        geometry = _remove_existing_text_geometry(geometry, text_lines, logs.append)
    if not is_specification:
        geometry = _strip_top_service_designation_geometry(geometry, logs)
    table_rules = _horizontal_table_rules_from_polylines(geometry)
    if is_specification:
        geometry, text_lines = _adjust_specification_underlined_heading_layout(geometry, text_lines, table_rules, logs)
        table_rules = _horizontal_table_rules_from_polylines(geometry)
    text_polys, accepted_text, missing_chars = _make_lff_opengost_text_strokes(
        text_lines,
        page_w_mm,
        page_h_mm,
        logs.append,
        use_stamp_overrides=not dense_onepass_source,
        center_a3_top_left_title=bool(dense_onepass_source and _is_computer_graphics_mode(settings)),
        normalize_dimension_text=(_is_computer_graphics_mode(settings) and not is_specification),
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
    elif is_specification:
        source_segments = sum(max(0, len(poly) - 1) for poly in source_polys)
        logs.append(
            "OpenGOST specification source: "
            f"polylines={len(source_polys)}; dense_segments={source_segments}; "
            "generic backend dedup disabled after text to preserve LFF digits, dots and loops."
        )
    else:
        source_polys = _dedup_segments(source_polys, precision=3)
        source_segments = sum(max(0, len(poly) - 1) for poly in source_polys)
        logs.append(
            "OpenGOST A4 source: "
            f"polylines={len(source_polys)}; dense_segments={source_segments}; "
            "collinear-overlap simplifier disabled after text to preserve LFF arcs/digits."
        )
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


def _map_single_large_plotter_sheet(
    source_build: SourceBuild,
    settings: Settings,
    logs: list[str],
) -> tuple[list[Polyline], dict[str, Any]]:
    """Fit one PDF sheet onto the A2 CoreXY once, without A3 pass splitting."""
    work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
    src_x0, src_y0, src_x1, src_y1 = _source_frame_bbox(source_build.polylines)
    src_w = max(1e-9, float(src_x1) - float(src_x0))
    src_h = max(1e-9, float(src_y1) - float(src_y0))
    work_w = max(1e-9, float(work_x1) - float(work_x0))
    work_h = max(1e-9, float(work_y1) - float(work_y0))
    target_scale = _large_plotter_target_scale(source_build)
    direct_scale = min(target_scale, work_w / src_w, work_h / src_h)
    rotated_scale = min(target_scale, work_w / src_h, work_h / src_w)
    # The A2 CoreXY useful width is 390 mm.  A landscape A3 is 420 mm wide,
    # but fits at true size when the sheet is placed portrait and the drawing
    # is rotated on the machine.  Prefer that complete 1:1 placement over an
    # invisible downscale or an A3 two-pass split.
    rotate_cw = rotated_scale > direct_scale + 1e-9
    mapped_w = src_h if rotate_cw else src_w
    mapped_h = src_w if rotate_cw else src_h
    scale = rotated_scale if rotate_cw else direct_scale
    tx = ((float(work_x0) + float(work_x1)) * 0.5) - (mapped_w * scale * 0.5)
    ty = ((float(work_y0) + float(work_y1)) * 0.5) - (mapped_h * scale * 0.5)
    mirror_y = bool(getattr(backend, "MACHINE_SOURCE_MIRROR_Y", False))

    mapped: list[Polyline] = []
    for poly in source_build.polylines:
        if len(poly) < 2:
            continue
        mapped_poly: Polyline = []
        for x, y in poly:
            if rotate_cw:
                # Clockwise rotation in source coordinates, normalized to
                # the source frame so its complete border remains intact.
                rx = float(y) - float(src_y0)
                ry = float(src_x1) - float(x)
            else:
                rx = float(x) - float(src_x0)
                ry = float(y) - float(src_y0)
            mx = rx * scale + tx
            my = ry * scale + ty
            if mirror_y:
                my = float(work_y0) + float(work_y1) - my
            mapped_poly.append((mx, my))
        mapped.append(mapped_poly)

    mapped = _translate(mapped, settings.x_compensation_mm, 0.0)
    clipped = backend.clip_polylines_to_work_area(mapped, logger=logs.append)
    deduped = _dedup_segments(clipped, precision=3)
    final = _stitch_touching_polylines(
        deduped,
        settings,
        logs,
        label="A2 single-sheet OpenGOST LFF continuity",
    )
    logs.append(
        "A2 single-sheet route: "
        f"scale={scale:.6f}; target_scale={target_scale:.6f}; "
        f"rotate_cw={rotate_cw}; mirror_y={mirror_y}; "
        f"source_frame_bbox={[round(float(v), 4) for v in (src_x0, src_y0, src_x1, src_y1)]}; "
        "A3 is emitted as one complete plotter file without a paper split."
    )
    return _dedup_segments(final, precision=3), {
        "applied": True,
        "mode": "a2_single_sheet_uniform_fit",
        "content_scale": round(float(scale), 6),
        "target_sheet_scale": round(float(target_scale), 6),
        "translate_x_mm": round(float(tx), 6),
        "translate_y_mm": round(float(ty), 6),
        "rotate_cw": rotate_cw,
        "mirror_y": mirror_y,
        "source_bbox": [round(float(v), 4) for v in (src_x0, src_y0, src_x1, src_y1)],
        "work_area_bounds": [round(float(v), 4) for v in (work_x0, work_x1, work_y0, work_y1)],
    }


def _source_sheet_format(source_build: SourceBuild) -> str:
    short_side, long_side = sorted((float(source_build.page_w_mm), float(source_build.page_h_mm)))
    if abs(short_side - 210.0) <= 15.0 and abs(long_side - 297.0) <= 15.0:
        return "a4"
    if abs(short_side - 297.0) <= 18.0 and abs(long_side - 420.0) <= 18.0:
        return "a3"
    if abs(short_side - 420.0) <= 20.0 and abs(long_side - 594.0) <= 20.0:
        return "a2"
    return "other"


def _large_plotter_target_scale(source_build: SourceBuild) -> float:
    """Return the requested sheet reduction: A2 -> A3, A3 stays 1:1."""
    return math.sqrt(0.5) if _source_sheet_format(source_build) == "a2" else 1.0


def _settings_for_source_sheet(source_build: SourceBuild, requested: Settings) -> Settings:
    """Select the target profile without overriding an explicit desktop request."""
    source_format = _source_sheet_format(source_build)
    # The Computer Graphics batch explicitly requests ``a4_desktop`` when an
    # A3/A2 sheet must be prepared as two A3 passes for the small plotter.
    # Do not silently reroute that job to the large A2 machine: that turns the
    # two-pass output into one file and removes the stitched-preview divider.
    if str(requested.machine_profile).casefold() == "a4_desktop":
        profile = "a4_desktop"
    else:
        profile = "a4_desktop" if source_format == "a4" else "a2_corexy"
    selected = settings_for_machine_profile(
        profile,
        drawing_mode=requested.drawing_mode,
        keep_debug_artifacts=requested.keep_debug_artifacts,
    )
    return replace(
        selected,
        x_compensation_mm=requested.x_compensation_mm,
        a3_pass_01_x_offset_mm=requested.a3_pass_01_x_offset_mm,
        a3_pass_01_y_offset_mm=requested.a3_pass_01_y_offset_mm,
        a3_pass_02_x_offset_mm=requested.a3_pass_02_x_offset_mm,
        a3_pass_02_y_offset_mm=requested.a3_pass_02_y_offset_mm,
    )


def _large_plotter_logical_preview(source_build: SourceBuild) -> tuple[list[Polyline], float, float]:
    """Render the target paper, not the rotated physical A2-bed coordinates."""
    scale = _large_plotter_target_scale(source_build)
    polylines = [
        [(float(x) * scale, float(y) * scale) for x, y in poly]
        for poly in source_build.polylines
        if len(poly) >= 2
    ]
    return polylines, float(source_build.page_w_mm) * scale, float(source_build.page_h_mm) * scale


def _large_plotter_preview_from_final_gcode(
    out_nc: Path,
    source_build: SourceBuild,
    settings: Settings,
) -> tuple[list[Polyline], float, float] | None:
    """Undo only the known A2-bed placement so preview is made from final NC."""
    raw_polylines = stitch_gcode_polylines.read_draw_polylines(
        out_nc,
        z_up=settings.z_up,
        z_down=settings.z_down,
    )
    if not raw_polylines:
        return None

    work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
    src_x0, src_y0, src_x1, src_y1 = _source_frame_bbox(source_build.polylines)
    src_w = max(1e-9, float(src_x1) - float(src_x0))
    src_h = max(1e-9, float(src_y1) - float(src_y0))
    work_w = max(1e-9, float(work_x1) - float(work_x0))
    work_h = max(1e-9, float(work_y1) - float(work_y0))
    target_scale = _large_plotter_target_scale(source_build)
    direct_scale = min(target_scale, work_w / src_w, work_h / src_h)
    rotated_scale = min(target_scale, work_w / src_h, work_h / src_w)
    rotate_cw = rotated_scale > direct_scale + 1e-9
    mapped_w = src_h if rotate_cw else src_w
    mapped_h = src_w if rotate_cw else src_h
    scale = rotated_scale if rotate_cw else direct_scale
    tx = ((float(work_x0) + float(work_x1)) * 0.5) - (mapped_w * scale * 0.5)
    ty = ((float(work_y0) + float(work_y1)) * 0.5) - (mapped_h * scale * 0.5)
    mirror_y = bool(getattr(backend, "MACHINE_SOURCE_MIRROR_Y", False))

    logical: list[Polyline] = []
    for poly in raw_polylines:
        restored: Polyline = []
        for x, y in poly:
            my = float(work_y0) + float(work_y1) - float(y) if mirror_y else float(y)
            rx = (float(x) - tx) / scale
            ry = (my - ty) / scale
            if rotate_cw:
                sx = float(src_x1) - ry
                sy = float(src_y0) + rx
            else:
                sx = float(src_x0) + rx
                sy = float(src_y0) + ry
            restored.append((sx * target_scale, sy * target_scale))
        if len(restored) >= 2:
            logical.append(restored)
    if not logical:
        return None
    return logical, float(source_build.page_w_mm) * target_scale, float(source_build.page_h_mm) * target_scale


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


def _nudge_a4_top_title_text_inside_frame(source_polys: list[Polyline], logs: list[str]) -> list[Polyline]:
    if not source_polys:
        return source_polys
    try:
        src_x0, src_y0, _src_x1, _src_y1 = _source_frame_bbox(source_polys)
    except Exception:
        return source_polys

    candidate_indexes: list[int] = []
    candidate_min_y: float | None = None
    for index, poly in enumerate(source_polys):
        if len(poly) < 2:
            continue
        px0, py0, px1, py1 = _bounds([poly])
        if not (float(py0) < float(src_y0) - 0.05 and float(py1) <= float(src_y0) + 13.0):
            continue
        if not (float(src_x0) - 2.0 <= float(px0) <= float(src_x0) + 88.0 and float(px1) <= float(src_x0) + 92.0):
            continue
        candidate_indexes.append(index)
        candidate_min_y = float(py0) if candidate_min_y is None else min(candidate_min_y, float(py0))

    if candidate_min_y is None or not candidate_indexes:
        return source_polys
    target_min_y = float(src_y0) + 1.20
    dy = target_min_y - float(candidate_min_y)
    if dy <= 0.05 or dy > 10.0:
        return source_polys

    shifted: list[Polyline] = []
    selected = set(candidate_indexes)
    for index, poly in enumerate(source_polys):
        if index in selected:
            shifted.append([(float(x), float(y) + dy) for x, y in poly])
        else:
            shifted.append(poly)
    logs.append(
        "A4 top title text nudge: "
        f"moved {len(candidate_indexes)} polyline(s) down by {dy:.3f} mm "
        f"to keep the service title inside the fitted frame."
    )
    return shifted


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


def _prepare_a4_lff_safe_clean_bbox_fit_polylines(
    source_polys: list[Polyline],
    *,
    logs: list[str],
) -> tuple[list[Polyline], dict[str, Any]]:
    stripped, frame_meta = prep._strip_outer_bbox_frame_segments(source_polys)
    if not bool(frame_meta.get("applied")):
        return [], {
            "applied": False,
            "reason": "source_outer_frame_not_found",
            **frame_meta,
        }

    work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
    src_x0, src_y0, src_x1, src_y1 = [float(v) for v in frame_meta["source_bbox"]]
    source_w = max(1e-9, src_x1 - src_x0)
    source_h = max(1e-9, src_y1 - src_y0)
    work_w = max(1e-9, work_x1 - work_x0)
    work_h = max(1e-9, work_y1 - work_y0)
    content_scale = min(1.0, work_w / source_w, work_h / source_h)
    dx = ((work_x0 + work_x1) * 0.5) - (((src_x0 + src_x1) * 0.5) * content_scale)
    dy = ((work_y0 + work_y1) * 0.5) - (((src_y0 + src_y1) * 0.5) * content_scale)

    mapped_inner = [
        [(float(x) * content_scale + dx, float(y) * content_scale + dy) for x, y in poly]
        for poly in stripped
        if len(poly) >= 2
    ]
    pre_clip_segments = sum(max(0, len(poly) - 1) for poly in mapped_inner)
    pre_clip_bbox = _bounds(mapped_inner) if mapped_inner else (0.0, 0.0, 0.0, 0.0)
    clip_logs: list[str] = []
    clipped_inner = backend.clip_polylines_to_work_area(mapped_inner, logger=clip_logs.append)
    post_clip_segments = sum(max(0, len(poly) - 1) for poly in clipped_inner)
    clipped_segments = max(0, int(pre_clip_segments) - int(post_clip_segments))
    if clip_logs:
        logs.extend(f"KOMPAS A4 LFF-safe 1:1 clip: {line}" for line in clip_logs)

    final_polys: list[Polyline] = [
        [(work_x0, work_y0), (work_x1, work_y0), (work_x1, work_y1), (work_x0, work_y1), (work_x0, work_y0)],
        *clipped_inner,
    ]
    final_polys = _dedup_segments(final_polys, precision=3)
    logs.append(
        "KOMPAS A4 LFF-safe clean-bbox route: source-page fit disabled; "
        f"source_frame_bbox={[round(float(v), 4) for v in frame_meta['source_bbox']]}; "
        f"content_scale={content_scale:.6f}; "
        f"translate=({dx:.4f},{dy:.4f}) mm; "
        f"pre_clip_bbox={[round(float(v), 4) for v in pre_clip_bbox]}; "
        f"clipped_segments={clipped_segments}; "
        "work_area_frame=full; collinear simplifier disabled to preserve OpenGOST LFF glyphs."
    )
    return final_polys, {
        "applied": True,
        "mode": "kompas_a4_lff_safe_clean_bbox_fit",
        "source_bbox": frame_meta["source_bbox"],
        "removed_segments": int(frame_meta.get("removed_segments", 0)),
        "content_scale": round(float(content_scale), 6),
        "translate_x_mm": round(float(dx), 6),
        "translate_y_mm": round(float(dy), 6),
        "pre_clip_bbox": [round(float(v), 4) for v in pre_clip_bbox],
        "clipped_segments": int(clipped_segments),
        "work_area_bounds": [round(float(v), 4) for v in (work_x0, work_x1, work_y0, work_y1)],
    }


def _prepare_a4_page(source_build: SourceBuild, settings: Settings, logs: list[str]) -> tuple[list[Polyline], dict[str, Any]]:
    if source_build.preserve_source_frame:
        return _map_a4_preserving_source_frame(source_build, settings, logs)
    is_specification = _is_new_algorithm_specification(source_build.source_pdf, source_build.polylines)
    a4_source_polys = _nudge_a4_top_title_text_inside_frame(source_build.polylines, logs)
    final_polys, fit_meta = _prepare_a4_lff_safe_clean_bbox_fit_polylines(a4_source_polys, logs=logs)
    if is_specification:
        fit_meta["mode"] = "a4_specification_lff_safe_clean_bbox_fit"
        logs.append("A4 specification: using the shared full-work-area KOMPAS mapping; source-page shrink is disabled.")
    if not final_polys:
        work_x0, work_x1, work_y0, work_y1 = prep._machine_work_area_bounds_mm()
        sx0, sy0, sx1, sy1 = _bounds(a4_source_polys)
        src_w = max(1e-9, sx1 - sx0)
        src_h = max(1e-9, sy1 - sy0)
        scale = min((work_x1 - work_x0) / src_w, (work_y1 - work_y0) / src_h)
        tx = ((work_x0 + work_x1) * 0.5) - (((sx0 + sx1) * 0.5) * scale)
        ty = ((work_y0 + work_y1) * 0.5) - (((sy0 + sy1) * 0.5) * scale)
        mapped = [[(float(x) * scale + tx, float(y) * scale + ty) for x, y in poly] for poly in a4_source_polys]
        final_polys = backend.clip_polylines_to_work_area(mapped, logger=logs.append)
        fit_meta = {
            "applied": True,
            "fallback_generic_fit": True,
            "content_scale": round(float(scale), 6),
            "translate_x_mm": round(float(tx), 6),
            "translate_y_mm": round(float(ty), 6),
        }
    final_polys = _translate(final_polys, settings.x_compensation_mm, 0.0)
    if is_specification:
        stitched = stitch_gcode_polylines.stitch_polylines(final_polys, eps=settings.stitch_eps_mm)
        ordered = stitch_gcode_polylines.nearest_order(stitched)
        logs.append(
            "A4 specification LFF route: final generic dedup/collinear simplifiers disabled "
            "to preserve digits, dots and closed text loops."
        )
        return ordered, fit_meta
    final_polys = _dedup_segments(final_polys, precision=3)
    final = _stitch_touching_polylines(
        final_polys,
        settings,
        logs,
        label="A4 OpenGOST LFF-safe continuity",
    )
    return _dedup_segments(final, precision=3), fit_meta

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
    polylines = stitch_gcode_polylines.read_draw_polylines(
        out_nc,
        z_up=settings.z_up,
        z_down=settings.z_down,
    )
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


def _write_specification_preview_from_final_gcode(
    out_nc: Path,
    out_pdf: Path,
    settings: Settings,
) -> Path:
    """Render a clean specification preview from the exact final NC segments."""

    segments, _points = render_gcode_preview.parse_draw_segments(
        out_nc,
        transform=settings.paper_transform,
        work_min_x=0.0,
        work_min_y=settings.work_min_y,
        work_width=settings.work_width,
        work_height=settings.work_height,
        z_up=settings.z_up,
        z_down=settings.z_down,
    )
    work_x0, work_y0, work_x1, work_y1 = render_gcode_preview._transformed_work_bounds(
        transform=settings.paper_transform,
        work_min_x=0.0,
        work_min_y=settings.work_min_y,
        work_width=settings.work_width,
        work_height=settings.work_height,
    )
    polylines = [
        [
            (x0 - work_x0, work_y1 - y0),
            (x1 - work_x0, work_y1 - y1),
        ]
        for x0, y0, x1, y1 in segments
    ]
    prep._render_polylines_pdf(
        polylines=polylines,
        out_pdf=out_pdf,
        canvas_bounds_mm=(
            0.0,
            work_x1 - work_x0,
            0.0,
            work_y1 - work_y0,
        ),
    )
    return out_pdf


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
        z_up=settings.z_up,
        z_down=settings.z_down,
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
    if str(settings.machine_profile).casefold() == "a2_corexy":
        # The physical A2 route can rotate a landscape A3 onto the tall work
        # area.  Present the finished sheet in its normal reading orientation:
        # it is exactly the same 1:1 geometry that reaches the plotter, only
        # shown after the operator turns the paper back to landscape.
        final_nc = _row_path(ok_rows[0], "output_nc") if ok_rows else None
        final_preview = (
            _large_plotter_preview_from_final_gcode(final_nc, source_build, settings)
            if final_nc and final_nc.exists()
            else None
        )
        preview_polylines, page_w_mm, page_h_mm = final_preview or _large_plotter_logical_preview(source_build)
        prep._render_polylines_pdf(
            polylines=preview_polylines,
            out_pdf=out_pdf,
            canvas_bounds_mm=(0.0, page_w_mm, 0.0, page_h_mm),
        )
        return out_pdf
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
        if _is_new_algorithm_specification(source_build.source_pdf, source_build.polylines):
            final_nc = _row_path(ok_rows[0], "output_nc")
            if final_nc and final_nc.exists():
                return _write_specification_preview_from_final_gcode(final_nc, out_pdf, settings)
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
    try:
        _copy_if_different(source_pdf, source_out)
    except PermissionError:
        pass
    if source_out.exists():
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
    active_settings = _settings_for_source_sheet(source_build, settings)
    rows: list[dict[str, Any]] = []
    item_names = ["page_01"] if str(active_settings.machine_profile).casefold() == "a2_corexy" else _output_items(report)
    for item_name in item_names:
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
                final_polys = _map_to_item_dense_onepass(source_build.polylines, transform, active_settings, logs)
                mode = "a3_dense_onepass_opengost_lff_from_report_logs"
            else:
                final_polys = _map_to_item(source_build.polylines, transform, active_settings, logs)
                mode = "a3_pass_transform_from_report_logs"
            fit_meta: dict[str, Any] = {
                "transform": transform.__dict__,
                "mode": mode,
            }
        elif str(active_settings.machine_profile).casefold() == "a2_corexy":
            final_polys, fit_meta = _map_single_large_plotter_sheet(source_build, active_settings, logs)
        else:
            final_polys, fit_meta = _prepare_a4_page(source_build, active_settings, logs)
        if item_name.startswith("pass_"):
            final_polys, a3_offset_meta = _apply_a3_pass_plotter_offset(final_polys, item_name, active_settings, logs)
            fit_meta["a3_plotter_offset_mm"] = a3_offset_meta
        outputs = _write_item_outputs(pack, item_name, final_polys, active_settings)
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
    _publish_clean_pack_outputs(pack, source_pdf, source_build, rows, active_settings)
    return rows


def _rebuild_packages(variant_root: Path, machine_profile: str) -> None:
    rel = variant_root
    try:
        rel = variant_root.relative_to(ROOT)
    except ValueError:
        pass
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_folder1_packages.py"),
            "--folder",
            str(rel),
            "--machine-profile",
            str(machine_profile),
        ],
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


def _cache_variant_pack_metadata(variant_root: Path) -> None:
    for pack in sorted(variant_root.glob("*_pack"), key=lambda path: path.name.casefold()):
        _cache_pack_metadata(pack)


def _remove_pack_build_artifacts(variant_root: Path) -> None:
    for pack in sorted(variant_root.glob("*_pack"), key=lambda path: path.name.casefold()):
        if not pack.exists() or not pack.is_dir():
            continue
        for child in list(pack.iterdir()):
            _safe_remove_pack_child(pack, child)


def prepare_variant(
    variant_root: Path,
    *,
    rebuild: bool,
    rebuild_metadata: bool,
    settings: Settings,
) -> list[dict[str, Any]]:
    variant_root = variant_root.resolve()
    packs = sorted(variant_root.glob("*_pack"), key=lambda path: path.name.casefold())
    _cache_variant_pack_metadata(variant_root)
    needs_metadata = rebuild_metadata or not packs or any(not _load_report(pack) for pack in packs)
    if needs_metadata:
        _remove_variant_root_artifacts(variant_root)
        try:
            _rebuild_packages(variant_root, settings.machine_profile)
        finally:
            _cache_variant_pack_metadata(variant_root)
            _remove_variant_root_artifacts(variant_root)
            if not settings.keep_debug_artifacts:
                _remove_pack_build_artifacts(variant_root)
        packs = sorted(variant_root.glob("*_pack"), key=lambda path: path.name.casefold())
    elif rebuild and not settings.keep_debug_artifacts:
        _remove_variant_root_artifacts(variant_root)
        _remove_pack_build_artifacts(variant_root)
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
    parser.add_argument("--machine-profile", default="a4_desktop", help="Target profile: a4_desktop or a2_corexy.")
    parser.add_argument("--drawing-mode", choices=["auto", "computer_graphics", "descriptive_geometry"], default="auto", help="Frame/layout profile: computer_graphics for KOMPAS drawing sheets, descriptive_geometry for РќР°С‡РµСЂС‚ tasks.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild clean new-algorithm outputs from existing package metadata.")
    parser.add_argument("--rebuild-metadata", action="store_true", help="Run the legacy package splitter first when report.json metadata is missing or stale.")
    parser.add_argument("--x-compensation-mm", type=float, default=0.0)
    parser.add_argument("--a3-pass-01-x-offset-mm", type=float, default=0.0, help="Extra plotter-only X offset for A3 pass_01; default keeps current output unchanged.")
    parser.add_argument("--a3-pass-01-y-offset-mm", type=float, default=3.0, help="Plotter-only Y correction for A3 pass_01; default raises the first pass 6 mm relative to the previous -3 mm correction.")
    parser.add_argument("--a3-pass-02-x-offset-mm", type=float, default=0.0, help="Extra plotter-only X offset for A3 pass_02; default keeps current output unchanged.")
    parser.add_argument("--a3-pass-02-y-offset-mm", type=float, default=0.0, help="Extra plotter-only Y offset for A3 pass_02; default keeps current output unchanged.")
    parser.add_argument(
        "--keep-debug-artifacts",
        action="store_true",
        help="Keep reports, source SVG/PDF/PNG previews and summary CSV instead of publishing only clean pack files.",
    )
    args = parser.parse_args()
    settings = replace(
        settings_for_machine_profile(
            args.machine_profile,
            drawing_mode=_normalize_drawing_mode(args.drawing_mode, args.variant_root),
            keep_debug_artifacts=bool(args.keep_debug_artifacts),
        ),
        x_compensation_mm=float(args.x_compensation_mm),
        a3_pass_01_x_offset_mm=float(args.a3_pass_01_x_offset_mm),
        a3_pass_01_y_offset_mm=float(args.a3_pass_01_y_offset_mm),
        a3_pass_02_x_offset_mm=float(args.a3_pass_02_x_offset_mm),
        a3_pass_02_y_offset_mm=float(args.a3_pass_02_y_offset_mm),
    )
    rows = prepare_variant(
        args.variant_root,
        rebuild=bool(args.rebuild),
        rebuild_metadata=bool(args.rebuild_metadata),
        settings=settings,
    )
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

