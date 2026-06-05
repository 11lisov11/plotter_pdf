from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from functools import lru_cache
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import cv2  # type: ignore
import fitz  # type: ignore
import numpy as np  # type: ignore
from PIL import Image, ImageDraw, ImageFont  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plotter_studio.core.protocol import (
    BackendBridge,
    SheetConfig,
    _gcode_to_polylines,
    _is_detail_polyline_mm,
    _write_pdf_preview,
    _write_svg_preview,
)
from plotter_studio.core.serial_worker import OperationContext
from src.plotter_backend import text_content_routing, toe_font_policy
from src.plotter_backend.geometry.sheet_tiling import plan_tiled_passes_for_sheet
from src import plotter_pdf_drawer as backend


TOE_FALLBACK_LAYOUT_THRESHOLD = 0.93
_A3_FIT_RE = re.compile(r"Fit to work area: scale=([0-9.]+), translate=\(([-0-9.]+),([-0-9.]+)\)")
_A3_PASS_RE = re.compile(r"Pass window: .* shift=\(([-0-9.]+),([-0-9.]+)\)")
_A3_AREA_RE = re.compile(r"bounds x\(([-0-9.]+),([-0-9.]+)\) y\(([-0-9.]+),([-0-9.]+)\)")
_A3_POST_TRANSLATE_RE = re.compile(r"translating geometry by \(([-0-9.]+),([-0-9.]+)\) mm")
_CONDITION_IMAGE_MIN_W_MM = 8.0
_CONDITION_IMAGE_MIN_H_MM = 8.0
_CONDITION_IMAGE_MAX_W_MM = 70.0
_CONDITION_IMAGE_MAX_H_MM = 60.0
_CONDITION_IMAGE_MAX_AREA_MM2 = 3200.0
_A3_HEADER_IMAGE_MAX_X0_MM = 20.0
_A3_HEADER_IMAGE_MAX_Y0_MM = 70.0
_A3_HEADER_IMAGE_MIN_W_MM = 100.0
_A3_HEADER_IMAGE_MAX_W_MM = 260.0
_A3_HEADER_IMAGE_MIN_H_MM = 20.0
_A3_HEADER_IMAGE_MAX_H_MM = 70.0
_TECH_POINT_BOX_MIN_MM = 0.75
_TECH_POINT_BOX_MAX_MM = 2.40
_TECH_POINT_BOX_EXTENDED_MAX_MM = 4.20
_TECH_POINT_BOX_MAX_ASPECT = 1.35
_TECH_POINT_BOX_CLOSURE_EPS_MM = 0.20
_TECH_POINT_BOX_AXIS_EPS_MM = 0.18
_TECH_POINT_BOX_DOT_MIN_R_MM = 0.20
_TECH_POINT_BOX_DOT_MAX_R_MM = 0.34
_TECH_POINT_BOX_DOT_SEGMENTS = 10
_TECH_POINT_BOX_DUPLICATE_CENTER_EPS_MM = 0.90
_TECH_ARROWHEAD_MAX_BBOX_MM = 4.20
_TECH_ARROWHEAD_MAX_VERTICES = 12
_TECH_ARROWHEAD_MAX_FILL_RATIO = 0.90
_TECH_ARROWHEAD_MIN_AREA_MM2 = 0.05
_TECH_ARROWHEAD_MAX_AREA_MM2 = 8.00
_TECH_ARROW_BBOX_ARTIFACT_MAX_MM = 4.40
_TECH_ARROW_BBOX_ARTIFACT_MIN_MM = 1.00
_TECH_ARROW_BBOX_ARTIFACT_MIN_ASPECT = 1.40
_TECH_ARROW_BBOX_ARTIFACT_SUPPORTS_MIN = 2
_TECH_POINT_MARKER_MIN_MM = 0.70
_TECH_POINT_MARKER_MAX_W_MM = 3.80
_TECH_POINT_MARKER_MAX_H_MM = 4.40
_TECH_POINT_MARKER_MAX_ASPECT = 1.95
_TECH_POINT_MARKER_MAX_PERIM_MM = 14.5
_TECH_POINT_MARKER_SUPPORT_DIST_MM = 0.85
_TECH_POINT_MARKER_SUPPORT_LINE_MIN_MM = 1.10
_TECH_POINT_MARKER_REPEAT_MIN = 4
_A4_HEADER_CONTENT_MAX_Y_MM = 48.0
_A4_HEADER_CONTENT_MAX_W_MM = 120.0
_A4_HEADER_CONTENT_MAX_H_MM = 28.0
_A4_HEADER_CONTENT_MAX_PERIM_MM = 180.0
_A4_HEADER_THUMB_DIVIDER_MAX_X_MM = 70.0
_A4_HEADER_THUMB_DIVIDER_MAX_W_MM = 2.2
_A4_HEADER_THUMB_DIVIDER_MIN_H_MM = 10.0
_A4_HEADER_THUMB_TARGET_MIN_W_MM = 60.0
_A4_HEADER_TEXT_SRC_MIN_X_MM = 34.0
_A4_HEADER_TEXT_SRC_PAD_MM = 4.0
_A4_HEADER_TEXT_GAP_MM = 4.0
_A4_HEADER_TEXT_SCALE = 0.92
_A4_HEADER_VARIANT1_TEXT_SRC_MIN_X_MM = 0.0
_A4_HEADER_VARIANT1_TEXT_SRC_PAD_MM = 1.0
_A4_HEADER_VARIANT1_THUMB_TARGET_MIN_W_MM = 64.0
_A4_HEADER_VARIANT1_TEXT_GAP_MM = 5.0
_A4_HEADER_VARIANT1_TEXT_SCALE = 0.90


class _DummySignal:
    def emit(self, *_args, **_kwargs) -> None:
        return


class _DummyWorker:
    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.log_line = _DummySignal()
        self.progress = _DummySignal()

    def set_active_process(self, _proc) -> None:
        return


@dataclass
class ArtifactRow:
    source_pdf: str
    package_dir: str
    kind: str
    item: str
    ok: bool
    layout_similarity: float | None
    selected_variant: str
    source_fidelity_score: float | None
    fragmentation_score: float | None
    draw_length_m: float | None
    segments_total: int | None
    pen_down_strokes: int | None
    tiny_strokes_lt_08_mm: int | None
    point_like_strokes: int | None
    bounds: str
    nc: str
    gcode: str
    preview_pdf: str
    preview_svg: str
    notes: str


def _ctx(op_id: str) -> OperationContext:
    return OperationContext(_DummyWorker(), op_id)


@contextmanager
def _technical_drawing_backend_precision() -> Any:
    prev = {
        "STITCH_ENABLED": bool(getattr(backend, "STITCH_ENABLED", True)),
        "DRAW_ORDER_MODE": str(getattr(backend, "DRAW_ORDER_MODE", "auto")),
        "RDP_SIMPLIFY_EPS_MM": float(getattr(backend, "RDP_SIMPLIFY_EPS_MM", 0.0)),
        "LINE_FIT_TOL_MM": float(getattr(backend, "LINE_FIT_TOL_MM", 0.0)),
    }
    try:
        # Technical drawings suffer more from synthetic joins than from extra travel.
        # Preserve literal segment topology and source ordering while building packages.
        setattr(backend, "STITCH_ENABLED", False)
        setattr(backend, "DRAW_ORDER_MODE", "source")
        setattr(backend, "RDP_SIMPLIFY_EPS_MM", 0.0)
        setattr(backend, "LINE_FIT_TOL_MM", 0.0)
        yield
    finally:
        for key, value in prev.items():
            setattr(backend, key, value)


@contextmanager
def _preserve_nachert_variant1_header_context(bridge: BackendBridge, enabled: bool) -> Any:
    if not enabled:
        yield
        return
    overrides = {
        "_filter_left_upper_column_text_polylines_px": lambda polys, **_kwargs: (list(polys), 0),
        "_filter_left_upper_column_polylines_mm": lambda polys, **_kwargs: (list(polys), 0),
        "_drop_left_of_main_frame_mm": lambda polys, **_kwargs: (list(polys), 0),
        "_clip_all_left_of_x_mm": lambda polys, min_x: (list(polys), 0),
    }
    saved: dict[str, Any] = {}
    try:
        for name, replacement in overrides.items():
            if hasattr(bridge, name):
                saved[name] = getattr(bridge, name)
                setattr(bridge, name, replacement)
        yield
    finally:
        for name, value in saved.items():
            setattr(bridge, name, value)


def _ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: list[ArtifactRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(rows[0]).keys()) if rows else list(ArtifactRow.__annotations__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _read_rows_from_csv(path: Path) -> list[ArtifactRow]:
    if not path.exists():
        return []
    rows: list[ArtifactRow] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            rows.append(
                ArtifactRow(
                    source_pdf=str(raw.get("source_pdf", "")),
                    package_dir=str(raw.get("package_dir", "")),
                    kind=str(raw.get("kind", "")),
                    item=str(raw.get("item", "")),
                    ok=str(raw.get("ok", "")).strip().lower() == "true",
                    layout_similarity=None
                    if str(raw.get("layout_similarity", "")).strip() in {"", "None"}
                    else float(str(raw.get("layout_similarity", "0"))),
                    selected_variant=str(raw.get("selected_variant", "")),
                    source_fidelity_score=None
                    if str(raw.get("source_fidelity_score", "")).strip() in {"", "None"}
                    else float(str(raw.get("source_fidelity_score", "0"))),
                    fragmentation_score=None
                    if str(raw.get("fragmentation_score", "")).strip() in {"", "None"}
                    else float(str(raw.get("fragmentation_score", "0"))),
                    draw_length_m=None
                    if str(raw.get("draw_length_m", "")).strip() in {"", "None"}
                    else float(str(raw.get("draw_length_m", "0"))),
                    segments_total=None
                    if str(raw.get("segments_total", "")).strip() in {"", "None"}
                    else int(str(raw.get("segments_total", "0"))),
                    pen_down_strokes=None
                    if str(raw.get("pen_down_strokes", "")).strip() in {"", "None"}
                    else int(str(raw.get("pen_down_strokes", "0"))),
                    tiny_strokes_lt_08_mm=None
                    if str(raw.get("tiny_strokes_lt_08_mm", "")).strip() in {"", "None"}
                    else int(str(raw.get("tiny_strokes_lt_08_mm", "0"))),
                    point_like_strokes=None
                    if str(raw.get("point_like_strokes", "")).strip() in {"", "None"}
                    else int(str(raw.get("point_like_strokes", "0"))),
                    bounds=str(raw.get("bounds", "")),
                    nc=str(raw.get("nc", "")),
                    gcode=str(raw.get("gcode", "")),
                    preview_pdf=str(raw.get("preview_pdf", "")),
                    preview_svg=str(raw.get("preview_svg", "")),
                    notes=str(raw.get("notes", "")),
                )
            )
    return rows


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_nc_and_gcode(src_nc: Path, dst_nc: Path, dst_gcode: Path) -> None:
    _copy_file(src_nc, dst_nc)
    _copy_file(src_nc, dst_gcode)


def _force_a3_two_pass_for_large_sheet(source_pdf: Path) -> bool:
    stem = str(source_pdf.stem).strip().lower()
    if "компьютерная графика" not in str(source_pdf.parent).lower():
        return False
    return stem == "мч00.01.00.01 корпус"


def _force_a4_single_page_for_drawing(source_pdf: Path) -> bool:
    stem = str(source_pdf.stem).strip().lower()
    parent = str(source_pdf.parent).lower()
    if "компьютерная графика" not in parent:
        return False
    return stem == "мч00.01.00.02 крышка"


def _force_variant_a3_two_pass_for_large_sheet(source_pdf: Path, page_w_mm: float, page_h_mm: float) -> bool:
    if max(float(page_w_mm), float(page_h_mm)) <= 300.0:
        return False
    parent = str(source_pdf.parent).casefold()
    return "компьютерная графика" in parent


def _is_computer_graphics_variant20_or22_source(source_pdf: Path) -> bool:
    parent = str(source_pdf.parent).casefold()
    return "компьютерная графика" in parent and ("20 вариант" in parent or "22 вариант" in parent)


def _path_casefold_text(path: Path) -> str:
    try:
        return str(path).casefold()
    except Exception:
        return ""


def _is_nachert_source(source_pdf: Path) -> bool:
    return "начерт" in _path_casefold_text(source_pdf)


def _drawing_frame_class(source_pdf: Path) -> str:
    if _is_nachert_source(source_pdf):
        return "standard_frame"
    if _is_computer_graphics_source(source_pdf):
        return "kompas_full_frame"
    return "neutral_frame"


def _kompas_text_join_backend_overrides(source_pdf: Path | None) -> dict[str, Any]:
    if source_pdf is None or _drawing_frame_class(source_pdf) != "kompas_full_frame":
        return {}
    return {
        "TECH_TEXT_JOIN_ENABLE": False,
    }


def _kompas_source_to_drawing_polylines(
    page_items: list[Any],
    *,
    source_pdf: Path | None = None,
    page_index: int = 0,
    logger=None,
) -> list[list[tuple[float, float]]]:
    # KOMPAS technical text must be plotted as averaged single-stroke text, not
    # as double glyph contours. Keep the existing text-element centerline route:
    # cluster text fill glyphs, average them to centerlines, then refine/merge
    # technical strokes. Do not enable outline preservation here.
    with _backend_override_context(
        {
            "HANDWRITING_TEXT_ENABLED": False,
            "HANDWRITING_STROKE_ACTIVE": False,
            "HANDWRITING_PRESERVE_FILL_OUTLINES": False,
            "FILL_CENTERLINE_PX_PER_MM": 44.0,
            "FILL_CENTERLINE_MIN_COMPONENT_PX": 2,
            "FILL_CENTERLINE_MIN_PATH_MM": 0.055,
            "FILL_CENTERLINE_MAX_PATHS_PER_GLYPH": 18,
            "FILL_CENTERLINE_LEN_RATIO_MIN": 0.07,
            "FILL_CENTERLINE_LEN_RATIO_MAX": 1.35,
            "FILL_CENTERLINE_SPUR_PRUNE_PX": 1,
            "FILL_CENTERLINE_LOCAL_STITCH_EPS_MM": 0.20,
            "FILL_CENTERLINE_LOCAL_GAP_EPS_MM": 0.38,
            "FILL_CENTERLINE_LOCAL_ANGLE_DEG": 44.0,
            "SINGLE_STROKE_TEXT_ENABLED": True,
            "SINGLE_STROKE_TEXT_CLUSTER_MAX_BBOX_MM": 16.0,
            "SINGLE_STROKE_TEXT_CLUSTER_GAP_MM": 0.34,
            "SINGLE_STROKE_OUTLINE_TEXT_ENABLED": False,
            "HANDWRITING_OUTLINE_CENTERLINE_ENABLED": False,
            "TECH_TEXT_JOIN_ENABLE": True,
            "TECH_TEXT_JOIN_GAP_MM": 1.25,
            "TECH_TEXT_JOIN_MAX_DY_MM": 1.60,
            "TECH_TEXT_JOIN_MAX_BACKTRACK_MM": 0.90,
            "TECH_TEXT_JOIN_MAX_STROKE_LEN_MM": 18.0,
            "TECH_TEXT_JOIN_MAX_SPAN_MM": 18.0,
            "TECH_TEXT_JOIN_MAX_AREA_MM2": 180.0,
            "TECH_TEXT_JOIN_MAX_COMBINED_SPAN_X_MM": 12.0,
            "TECH_TEXT_JOIN_MAX_COMBINED_SPAN_Y_MM": 18.0,
            "TECH_TEXT_JOIN_MAX_COMBINED_AREA_MM2": 190.0,
            "TECH_TEXT_SINGLELINE_ENABLED": True,
        }
    ):
        polys = backend.to_drawing_polylines(page_items)
    if source_pdf is not None:
        polys = _stitch_kompas_text_centerline_fragments(
            polys,
            source_pdf=source_pdf,
            page_index=page_index,
            logger=logger,
        )
    return polys


def _project_point_to_segment_mm(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    px, py = float(point[0]), float(point[1])
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    if denom <= 1e-12:
        qx, qy = ax, ay
    else:
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
        qx, qy = ax + t * vx, ay + t * vy
    return (qx, qy), math.hypot(px - qx, py - qy)


def _snap_kompas_text_endpoints_to_strokes(
    polys_mm: list[list[tuple[float, float]]],
    *,
    max_dist_mm: float,
) -> list[list[tuple[float, float]]]:
    src = [[(float(x), float(y)) for x, y in poly] for poly in polys_mm if len(poly) >= 2]
    if len(src) < 2:
        return src
    max_dist = max(0.0, float(max_dist_mm))
    if max_dist <= 1e-9:
        return src

    out: list[list[tuple[float, float]]] = []
    for idx, poly in enumerate(src):
        cur = list(poly)
        endpoint_specs = ((0, True), (-1, False))
        inserts: list[tuple[bool, tuple[float, float]]] = []
        for endpoint_idx, at_start in endpoint_specs:
            point = cur[endpoint_idx]
            best_point: tuple[float, float] | None = None
            best_dist = float("inf")
            for other_idx, other in enumerate(src):
                if other_idx == idx or len(other) < 2:
                    continue
                for a, b in zip(other, other[1:]):
                    q, dist = _project_point_to_segment_mm(point, a, b)
                    if dist < best_dist:
                        best_dist = dist
                        best_point = q
            if best_point is not None and 1e-5 < best_dist <= max_dist:
                inserts.append((at_start, best_point))
        for at_start, q in inserts:
            if at_start:
                if math.hypot(cur[0][0] - q[0], cur[0][1] - q[1]) > 1e-5:
                    cur.insert(0, q)
            else:
                if math.hypot(cur[-1][0] - q[0], cur[-1][1] - q[1]) > 1e-5:
                    cur.append(q)
        out.append(cur)
    return out


def _reinforce_kompas_text_centerlines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    offset_mm: float,
    max_len_mm: float,
    max_span_mm: float,
) -> list[list[tuple[float, float]]]:
    src = [[(float(x), float(y)) for x, y in poly] for poly in polys_mm if len(poly) >= 2]
    if not src:
        return []
    offset = max(0.0, float(offset_mm))
    if offset <= 1e-9:
        return src

    out: list[list[tuple[float, float]]] = []
    for poly in src:
        out.append(poly)
        length = 0.0
        vx = 0.0
        vy = 0.0
        for a, b in zip(poly, poly[1:]):
            sx = float(b[0]) - float(a[0])
            sy = float(b[1]) - float(a[1])
            seg_len = math.hypot(sx, sy)
            length += seg_len
            vx += sx
            vy += sy
        xs = [float(x) for x, _y in poly]
        ys = [float(y) for _x, y in poly]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        if length <= 1e-6 or length > float(max_len_mm) or span > float(max_span_mm):
            continue
        axis_len = math.hypot(vx, vy)
        if axis_len <= 1e-6:
            nx, ny = 1.0, 0.0
        else:
            nx, ny = -vy / axis_len, vx / axis_len
        out.append([(float(x) + nx * offset, float(y) + ny * offset) for x, y in poly])
    return out


def _stitch_kompas_text_centerline_fragments(
    polys_mm: list[list[tuple[float, float]]],
    *,
    source_pdf: Path,
    page_index: int,
    logger=None,
) -> list[list[tuple[float, float]]]:
    if _drawing_frame_class(source_pdf) != "kompas_full_frame" or not polys_mm:
        return list(polys_mm)

    text_lines = [
        *_extract_kompas_plot_text_lines_from_pdf(source_pdf, page_index=page_index),
        *_extract_kompas_stamp_title_text_lines_from_pdf(source_pdf, page_index=page_index),
    ]
    regions: list[tuple[float, float, float, float]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for line in text_lines:
        bbox = tuple(line.get("bbox_mm", ()) or ())
        if len(bbox) < 4:
            continue
        x0, y0, x1, y1 = (float(v) for v in bbox[:4])
        if (x1 - x0) < 0.30 or (y1 - y0) < 0.30:
            continue
        key = (round(x0 * 100), round(y0 * 100), round(x1 * 100), round(y1 * 100))
        if key in seen:
            continue
        seen.add(key)
        regions.append((x0, y0, x1, y1))
    if not regions:
        return list(polys_mm)

    kept: list[list[tuple[float, float]]] = []
    buckets: dict[int, list[list[tuple[float, float]]]] = {}
    for poly in polys_mm:
        region_idx = _kompas_text_region_index_for_poly_mm(poly, text_regions=regions, pad_mm=1.65)
        if region_idx is None:
            kept.append(poly)
            continue
        buckets.setdefault(region_idx, []).append(poly)

    before = sum(len(group) for group in buckets.values())
    after = 0
    changed_regions = 0
    with _backend_override_context(
        {
            "TECH_TEXT_JOIN_ENABLE": True,
            "TECH_TEXT_JOIN_MAX_STROKE_LEN_MM": 22.0,
            "TECH_TEXT_JOIN_MAX_SPAN_MM": 18.0,
            "TECH_TEXT_JOIN_MAX_AREA_MM2": 180.0,
            "TECH_TEXT_JOIN_MAX_COMBINED_SPAN_X_MM": 10.5,
            "TECH_TEXT_JOIN_MAX_COMBINED_SPAN_Y_MM": 18.0,
            "TECH_TEXT_JOIN_MAX_COMBINED_AREA_MM2": 190.0,
        }
    ):
        for idx in sorted(buckets):
            group = buckets[idx]
            if len(group) < 2:
                kept.extend(group)
                after += len(group)
                continue
            merged = backend.merge_technical_text_strokes(
                group,
                logger=None,
                join_gap_mm=3.15,
                join_max_dy_mm=4.40,
                join_max_backtrack_mm=4.00,
                simplify_collinear_eps=0.008,
            )
            if not merged:
                merged = group
            merged = _snap_kompas_text_endpoints_to_strokes(merged, max_dist_mm=1.70)
            merged = _reinforce_kompas_text_centerlines(
                merged,
                offset_mm=0.075,
                max_len_mm=34.0,
                max_span_mm=24.0,
            )
            if len(merged) < len(group):
                changed_regions += 1
            kept.extend(merged)
            after += len(merged)

    if logger and before > 0:
        logger(
            "KOMPAS text centerline stitch: "
            f"regions={len(regions)}, touched={len(buckets)}, changed={changed_regions}, "
            f"strokes={before}->{after}."
        )
    return kept


def _export_pdf_page_to_svg_for_kompas_text_centerline(
    source_pdf: Path,
    page_index: int,
    out_svg: Path,
    *,
    logger,
    frame_source_pdf: Path | None = None,
) -> tuple[float, float, int, bool]:
    frame_pdf = frame_source_pdf or source_pdf
    if _drawing_frame_class(frame_pdf) != "kompas_full_frame":
        page_w_mm, page_h_mm = _export_pdf_page_to_mupdf_svg(
            source_pdf,
            page_index,
            out_svg,
            text_as_path=True,
        )
        return float(page_w_mm), float(page_h_mm), 0, False

    page_w_mm, page_h_mm = _export_pdf_page_to_mupdf_svg(
        source_pdf,
        page_index,
        out_svg,
        text_as_path=True,
    )
    logger("KOMPAS text centerline averaging: using source glyph paths and text-element centerline route.")
    return float(page_w_mm), float(page_h_mm), 0, True


@lru_cache(maxsize=256)
def _pdf_page0_text_casefold(path_text: str) -> str:
    try:
        with fitz.open(path_text) as doc:
            if doc.page_count <= 0:
                return ""
            return str(doc[0].get_text("text") or "").casefold()
    except Exception:
        return ""


def _is_kompas_specification_table_source(source_pdf: Path) -> bool:
    if _drawing_frame_class(source_pdf) != "kompas_full_frame":
        return False
    text = _pdf_page0_text_casefold(str(source_pdf))
    if not text:
        return False
    markers = (
        "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044f",
        "\u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u043d\u044b\u0435 \u0438\u0437\u0434\u0435\u043b\u0438\u044f",
        "\u0444\u043e\u0440\u043c\u0430\u0442",
        "\u043f\u043e\u0437.",
        "\u043d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435",
    )
    return all(marker in text for marker in markers)


def _kompas_service_regions_from_pdf(source_pdf: Path, *, page_index: int = 0) -> list[tuple[float, float, float, float]]:
    if _drawing_frame_class(source_pdf) != "kompas_full_frame":
        return []
    try:
        with fitz.open(str(source_pdf)) as doc:
            if doc.page_count <= page_index:
                return []
            page = doc[page_index]
            page_w_mm = float(page.rect.width) * 25.4 / 72.0
            page_h_mm = float(page.rect.height) * 25.4 / 72.0
            text_dict = page.get_text("dict")
    except Exception:
        return []

    left_markers = (
        "\u0438\u043d\u0432.",
        "\u043f\u043e\u0434\u043f. \u0438 \u0434\u0430\u0442\u0430",
        "\u0432\u0437\u0430\u043c.",
        "\u0441\u043f\u0440\u0430\u0432.",
        "\u043f\u0435\u0440\u0432. \u043f\u0440\u0438\u043c\u0435\u043d.",
        "\u043a\u043e\u043c\u043f\u0430\u0441-3d",
    )
    bottom_y = float(page_h_mm) - _kompas_under_frame_strip_mm(float(page_h_mm)) - 1.0
    regions: list[tuple[float, float, float, float]] = []
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(str(span.get("text", "") or "") for span in line.get("spans", [])).strip().casefold()
            if not text:
                continue
            bbox = tuple(float(v) * 25.4 / 72.0 for v in line.get("bbox", ()))
            if len(bbox) < 4:
                continue
            x0, y0, x1, y1 = bbox[:4]
            if (x0 <= 16.0 and any(marker in text for marker in left_markers)) or "\u043a\u043e\u043c\u043f\u0430\u0441-3d" in text:
                regions.append((0.0, max(0.0, y0 - 2.0), min(float(page_w_mm), max(20.0, x1 + 2.0)), min(float(page_h_mm), y1 + 2.0)))
            elif y0 >= bottom_y:
                regions.append((max(0.0, x0 - 2.0), max(0.0, y0 - 2.0), min(float(page_w_mm), x1 + 2.0), float(page_h_mm)))
    return regions


def _needs_variant20_22_a4_titleblock_direct_candidate(source_pdf: Path) -> bool:
    return False
    if not _is_computer_graphics_variant20_or22_source(source_pdf):
        return False
    stem = str(source_pdf.stem).casefold()
    return stem in {
        "мч00.52.00.00 клапан",
        "мч00.60.00.00 вентиль",
    }


def _prefer_direct_fit_full_for_nachert_a4(source_pdf: Path) -> bool:
    return _is_nachert_source(source_pdf)
    parts = [str(part).lower() for part in source_pdf.parts]
    return "РЅР°С‡РµСЂС‚" in parts and "4 РІР°СЂРёРЅС‚" in parts


def _preserve_nachert_header_source_for_variant(source_pdf: Path) -> bool:
    parts = {str(part).casefold() for part in source_pdf.parts}
    return "начерт" in parts and ("1 вариант" in parts or "4 варинт" in parts)


def _is_nachert_variant4_source(source_pdf: Path) -> bool:
    parts = {str(part).casefold() for part in source_pdf.parts}
    return "начерт" in parts and "4 варинт" in parts


def _render_pdf_page_gray(pdf_path: Path, page_index: int = 0, dpi: int = 140) -> np.ndarray:
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    zoom = float(dpi) / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def _prefer_direct_fit_full_for_nachert_variant4_a4(source_pdf: Path) -> bool:
    return False


def _select_best_direct_vector_candidate(successful: list[dict[str, Any]]) -> dict[str, Any] | None:
    direct_candidates = [
        row
        for row in successful
        if str(row.get("variant", "") or "") in {"fit_full", "mupdf_svg_paths", "clean_source_direct"}
        and bool(row.get("ok"))
    ]
    if not direct_candidates:
        return None
    clean_bbox_candidates = [
        row
        for row in direct_candidates
        if "kompas_source_page_fit_disabled=True" in str(row.get("notes", "") or "")
    ]
    if clean_bbox_candidates:
        return max(
            clean_bbox_candidates,
            key=lambda row: (
                -int(((row.get("clean_bbox_fit_meta", {}) or {}).get("clipped_segments", 0) or 0)),
                not bool(row.get("clipping_warning")),
                float((row.get("clean_bbox_fit_meta", {}) or {}).get("content_scale", 0.0) or 0.0),
                _candidate_kompas_full_frame_quality_score(row),
                _candidate_source_fidelity_score(row),
                _candidate_fragmentation_score(dict(row.get("metrics", {}) or {})),
            ),
        )
    return max(
        direct_candidates,
        key=lambda row: (
            float(row.get("layout_similarity", 0.0) or 0.0) - 0.0005 * float(((row.get("metrics", {}) or {}).get("tiny_strokes_lt_08_mm", 0.0) or 0.0)),
            -float(((row.get("metrics", {}) or {}).get("point_like_strokes", 0.0) or 0.0)),
            -float(((row.get("metrics", {}) or {}).get("tiny_strokes_lt_08_mm", 0.0) or 0.0)),
            -float(((row.get("metrics", {}) or {}).get("pen_down_strokes", 0.0) or 0.0)),
        ),
    )


def _select_best_kompas_full_frame_a4_candidate(successful: list[dict[str, Any]]) -> dict[str, Any] | None:
    direct_candidates = [
        row
        for row in successful
        if str(row.get("variant", "") or "") in {"mupdf_svg_paths", "clean_source_direct"}
        and bool(row.get("ok"))
    ]
    if not direct_candidates:
        return None
    return max(
        direct_candidates,
        key=lambda row: (
            _candidate_kompas_full_frame_quality_score(row),
            _candidate_source_fidelity_score(row),
            _candidate_fragmentation_score(dict(row.get("metrics", {}) or {})),
            float(row.get("layout_similarity", 0.0) or 0.0),
            -float(((row.get("metrics", {}) or {}).get("point_like_strokes", 0.0) or 0.0)),
            -float(((row.get("metrics", {}) or {}).get("tiny_strokes_lt_08_mm", 0.0) or 0.0)),
            -float(((row.get("metrics", {}) or {}).get("pen_down_strokes", 0.0) or 0.0)),
        ),
    )


def _candidate_source_fidelity_score(row: dict[str, Any]) -> float:
    sim = float(row.get("layout_similarity", 0.0) or 0.0)
    iou = float(row.get("source_crop_iou", 0.0) or 0.0)
    corr = float(row.get("source_crop_corr", 0.0) or 0.0)
    corr_norm = max(0.0, min(1.0, (corr + 1.0) / 2.0))
    blended = (0.55 * sim) + (0.25 * iou) + (0.20 * corr_norm)
    return round(max(blended, sim * 0.96), 6)


def _candidate_fragmentation_score(metrics: dict[str, Any]) -> float:
    segments_total = max(1.0, float(metrics.get("segments_total", 0.0) or 0.0))
    tiny_ratio = min(1.0, float(metrics.get("tiny_strokes_lt_08_mm", 0.0) or 0.0) / segments_total)
    point_ratio = min(1.0, float(metrics.get("point_like_strokes", 0.0) or 0.0) / segments_total)
    pen_norm = min(1.0, float(metrics.get("pen_down_strokes", 0.0) or 0.0) / 4000.0)
    penalty = (0.55 * tiny_ratio) + (0.35 * point_ratio) + (0.10 * pen_norm)
    return round(max(0.0, 1.0 - penalty), 6)


def _candidate_kompas_full_frame_quality_score(row: dict[str, Any]) -> float:
    layout = float(row.get("layout_similarity", 0.0) or 0.0)
    fidelity = _candidate_source_fidelity_score(row)
    fragmentation = _candidate_fragmentation_score(dict(row.get("metrics", {}) or {}))
    # KOMPAS A4 candidates often differ by ~0.001 in layout/fidelity while producing
    # drastically different tiny-stroke and pen-lift counts. Favor the cleaner route.
    score = (0.55 * layout) + (0.20 * fidelity) + (0.25 * fragmentation)
    return round(score, 6)


def _candidate_title_block_strategy(source_pdf: Path, row: dict[str, Any]) -> str:
    frame_class = _drawing_frame_class(source_pdf)
    variant = str(row.get("variant", "") or "")
    if frame_class == "standard_frame":
        return "source_vector_preserved"
    if frame_class == "kompas_full_frame":
        if "kompas_text_reroute=True" in str(row.get("notes", "") or ""):
            return "source_vector_with_single_line_text"
        if "kompas_stamp_text_repair=True" in str(row.get("notes", "") or ""):
            return "source_vector_with_stamp_title_text_repair"
        return "source_vector_as_path"
    if variant in {"forced_a4_single_page"}:
        return "single_line_reroute"
    if variant == "a4_hybrid_frame" or _is_specification_like_drawing(source_pdf):
        return "source_vector_preserved"
    return "source_vector_as_path"


def _candidate_route_class(
    source_pdf: Path,
    row: dict[str, Any],
    *,
    is_a3: bool = False,
    forced_a3_two_pass: bool = False,
) -> str:
    frame_class = _drawing_frame_class(source_pdf)
    if is_a3:
        doc = fitz.open(source_pdf)
        try:
            page = doc[0]
            page_w_mm = float(page.rect.width) * 25.4 / 72.0
            page_h_mm = float(page.rect.height) * 25.4 / 72.0
        finally:
            doc.close()
        if frame_class == "kompas_full_frame":
            return "A3/A2 -> A3 scaled two-pass"
        if forced_a3_two_pass or max(page_w_mm, page_h_mm) > 430.0:
            return "A3/A2 -> A3 scaled two-pass"
        return "A3 two-pass drawing"

    if frame_class == "standard_frame":
        return "drawing with miniature/header overlay"
    if frame_class == "kompas_full_frame":
        return "A4 drawing with full KOMPAS frame"

    notes = str(row.get("notes", "") or "")
    variant = str(row.get("variant", "") or "")
    if "compact_miniature_overlay" in notes or "condition_images_recovered=" in notes:
        return "drawing with miniature/header overlay"
    if variant in {"a4_hybrid_frame", "clean_source_direct", "forced_a4_single_page"}:
        return "A4 drawing with title block"
    if _is_computer_graphics_source(source_pdf) or _is_specification_like_drawing(source_pdf):
        return "A4 drawing with title block"
    return "A4 drawing without sensitive title block"


def _build_a4_selection_decision(
    source_pdf: Path,
    best: dict[str, Any],
    *,
    selection_reason: str,
) -> dict[str, Any]:
    metrics = dict(best.get("metrics", {}) or {})
    return {
        "frame_class": _drawing_frame_class(source_pdf),
        "selected_variant": str(best.get("variant", "") or ""),
        "selection_reason": str(selection_reason),
        "source_fidelity_score": _candidate_source_fidelity_score(best),
        "fragmentation_score": _candidate_fragmentation_score(metrics),
        "title_block_strategy": _candidate_title_block_strategy(source_pdf, best),
        "route_class": _candidate_route_class(source_pdf, best),
    }


def _select_best_a4_drawing_candidate(
    source_pdf: Path,
    successful: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    frame_class = _drawing_frame_class(source_pdf)
    preferred_successful = [row for row in successful if str(row.get("variant", "") or "") != "strict_1to1_clip"]
    if frame_class == "standard_frame":
        if _prefer_direct_fit_full_for_nachert_a4(source_pdf):
            standard_candidates = [
                row
                for row in preferred_successful
                if str(row.get("variant", "") or "") in {"fit_full", "mupdf_svg_paths", "clean_source_direct"}
            ]
        else:
            standard_candidates = [
                row
                for row in preferred_successful
                if str(row.get("variant", "") or "") == "a4_hybrid_frame"
                or "compact_miniature_overlay" in str(row.get("notes", "") or "")
                or "condition_images_recovered=" in str(row.get("notes", "") or "")
            ]
        if standard_candidates:
            best = max(standard_candidates, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
            selection_reason = "standard_frame_route"
        elif preferred_successful:
            best = max(preferred_successful, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
            selection_reason = "standard_frame_fallback"
        else:
            best = max(successful, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
            selection_reason = "strict_1to1_clip_last_resort"
    elif frame_class == "kompas_full_frame":
        best = _select_best_kompas_full_frame_a4_candidate(preferred_successful or successful)
        if best is None:
            best = max(successful, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
            selection_reason = "kompas_full_frame_fallback"
        elif "kompas_source_page_fit_disabled=True" in str(best.get("notes", "") or ""):
            selection_reason = "kompas_full_frame_clean_bbox_fit"
        else:
            selection_reason = "kompas_full_frame_direct_best"
    else:
        if preferred_successful:
            best = max(preferred_successful, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
            selection_reason = "highest_layout_similarity"
        else:
            best = max(successful, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
            selection_reason = "strict_1to1_clip_last_resort"
        hybrid = next((row for row in successful if str(row.get("variant", "")) == "a4_hybrid_frame"), None)
        if hybrid is not None:
            best_sim = float(best.get("layout_similarity", 0.0) or 0.0)
            hybrid_sim = float(hybrid.get("layout_similarity", 0.0) or 0.0)
            hybrid_notes = str(hybrid.get("notes", "") or "")
            hybrid_preserves_detail = "detail_scale=1.0" in hybrid_notes
            if hybrid_preserves_detail and (best_sim - hybrid_sim) <= 0.01:
                best = hybrid
                selection_reason = "hybrid_detail_preservation"

    if not bool(best.get("ok")):
        mupdf_svg_paths = next((row for row in successful if str(row.get("variant", "")) == "mupdf_svg_paths"), None)
        if mupdf_svg_paths is not None:
            best = mupdf_svg_paths
            selection_reason = "fallback_mupdf_svg_paths"

    if _is_specification_like_drawing(source_pdf):
        clean_source_direct = next((row for row in successful if str(row.get("variant", "")) == "clean_source_direct"), None)
        if clean_source_direct is not None:
            best = clean_source_direct
            selection_reason = "specification_clean_source_direct"

    return best, _build_a4_selection_decision(source_pdf, best, selection_reason=selection_reason)


def _crop_content(gray: np.ndarray) -> np.ndarray:
    mask = gray < 245
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return gray
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    pad = 8
    y0 = max(0, y0 - pad)
    y1 = min(gray.shape[0], y1 + pad)
    x0 = max(0, x0 - pad)
    x1 = min(gray.shape[1], x1 + pad)
    return gray[y0:y1, x0:x1]


def _kompas_archive_strip_mm(page_w_mm: float, *, specification_table: bool = False) -> float:
    return max(18.0, min(24.0, float(page_w_mm) * 0.08))


def _kompas_under_frame_strip_mm(page_h_mm: float) -> float:
    return max(4.8, min(6.0, float(page_h_mm) * 0.018))


def _mask_kompas_service_gray(
    gray: np.ndarray,
    *,
    page_w_mm: float,
    page_h_mm: float | None = None,
    strip_mm: float,
    bottom_mm: float | None = None,
) -> np.ndarray:
    if gray.size == 0 or page_w_mm <= 1e-6:
        return gray
    out = gray.copy()
    strip_px = max(0, min(out.shape[1], int(round(float(out.shape[1]) * float(strip_mm) / float(page_w_mm)))))
    if strip_px > 0:
        out[:, :strip_px] = 255
    if page_h_mm is not None and page_h_mm > 1e-6 and bottom_mm is not None and bottom_mm > 0:
        bottom_px = max(0, min(out.shape[0], int(round(float(out.shape[0]) * float(bottom_mm) / float(page_h_mm)))))
        if bottom_px > 0:
            out[-bottom_px:, :] = 255
    return out


def _apply_kompas_metric_mask(
    gray: np.ndarray,
    *,
    page_w_mm: float,
    page_h_mm: float | None = None,
    specification_table: bool = False,
) -> np.ndarray:
    return _mask_kompas_service_gray(
        gray,
        page_w_mm=page_w_mm,
        page_h_mm=page_h_mm,
        strip_mm=_kompas_archive_strip_mm(page_w_mm, specification_table=specification_table),
        bottom_mm=_kompas_under_frame_strip_mm(page_h_mm) if page_h_mm is not None else None,
    )


def _cleanup_kompas_archive_strip_polylines(
    polylines: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float | None = None,
    specification_table: bool = False,
    service_regions_mm: list[tuple[float, float, float, float]] | None = None,
) -> tuple[list[list[tuple[float, float]]], dict[str, int]]:
    if not polylines:
        return [], {
            "archive_strip_removed": 0,
            "archive_strip_clipped": 0,
            "service_region_removed": 0,
            "under_frame_removed": 0,
            "top_outer_frame_removed": 0,
        }
    cutoff_x = _kompas_archive_strip_mm(page_w_mm, specification_table=specification_table)
    loose_cutoff_x = cutoff_x * 1.35
    bottom_y = None
    if page_h_mm is not None and page_h_mm > 1e-6:
        bottom_y = float(page_h_mm) - _kompas_under_frame_strip_mm(float(page_h_mm))
    kept: list[list[tuple[float, float]]] = []
    archive_removed = 0
    archive_clipped = 0
    service_region_removed = 0
    under_frame_removed = 0
    top_outer_frame_removed = 0
    service_regions = list(service_regions_mm or [])

    def _clip_left(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if specification_table:
            return poly
        clipped: list[tuple[float, float]] = []
        for idx in range(1, len(poly)):
            x0, y0 = float(poly[idx - 1][0]), float(poly[idx - 1][1])
            x1, y1 = float(poly[idx][0]), float(poly[idx][1])
            p0_in = x0 >= cutoff_x
            p1_in = x1 >= cutoff_x
            if p0_in and not clipped:
                clipped.append((x0, y0))
            if p0_in and p1_in:
                clipped.append((x1, y1))
                continue
            if p0_in != p1_in:
                if abs(x1 - x0) <= 1e-9:
                    y_cut = y1
                else:
                    t = (cutoff_x - x0) / (x1 - x0)
                    y_cut = y0 + (y1 - y0) * t
                cut_point = (float(cutoff_x), float(y_cut))
                if not clipped or clipped[-1] != cut_point:
                    clipped.append(cut_point)
                if p1_in:
                    clipped.append((x1, y1))
        deduped: list[tuple[float, float]] = []
        for point in clipped:
            if not deduped or point != deduped[-1]:
                deduped.append(point)
        return deduped

    def _center_in_service_region(x0: float, y0: float, x1: float, y1: float) -> bool:
        if not service_regions:
            return False
        cx = (float(x0) + float(x1)) * 0.5
        cy = (float(y0) + float(y1)) * 0.5
        for rx0, ry0, rx1, ry1 in service_regions:
            if float(rx0) <= cx <= float(rx1) and float(ry0) <= cy <= float(ry1):
                return True
        return False

    for poly in polylines:
        if len(poly) < 2:
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1) - float(x0)
        bh = float(y1) - float(y0)
        axis_aligned = _poly_is_axis_aligned_mm(poly, eps=0.18)
        thin_axis_line = axis_aligned and min(bw, bh) <= 0.35
        structural_axis_line = thin_axis_line and max(bw, bh) >= 18.0
        if (
            thin_axis_line
            and bh <= 0.35
            and bw >= float(page_w_mm) * 0.72
            and float(y0) <= 1.5
        ):
            top_outer_frame_removed += 1
            continue
        if (
            thin_axis_line
            and bw <= 0.35
            and bh >= float(page_h_mm or 0.0) * 0.72
            and float(x0) >= float(page_w_mm) - 1.5
        ):
            top_outer_frame_removed += 1
            continue
        if _center_in_service_region(float(x0), float(y0), float(x1), float(y1)) and not structural_axis_line:
            service_region_removed += 1
            continue
        near_main_bottom_frame = (
            bottom_y is not None
            and thin_axis_line
            and bh <= 0.35
            and bw >= float(page_w_mm) * 0.45
            and float(y0) <= float(bottom_y) + 0.8
            and float(x0) >= float(cutoff_x) - 1.0
        )
        if bottom_y is not None and float(y0) >= float(bottom_y) and not near_main_bottom_frame:
            under_frame_removed += 1
            continue
        center_x = (float(x0) + float(x1)) * 0.5
        if float(x1) <= float(cutoff_x):
            archive_removed += 1
            continue
        if float(x0) <= float(cutoff_x) and center_x <= float(loose_cutoff_x):
            archive_removed += 1
            continue
        if float(x0) < float(cutoff_x):
            clipped = _clip_left(poly)
            if len(clipped) < 2:
                archive_removed += 1
                continue
            poly = clipped
            archive_clipped += 1
        kept.append(poly)
    if not kept:
        return list(polylines), {
            "archive_strip_removed": 0,
            "archive_strip_clipped": 0,
            "service_region_removed": 0,
            "under_frame_removed": 0,
            "top_outer_frame_removed": 0,
        }
    return kept, {
        "archive_strip_removed": int(archive_removed),
        "archive_strip_clipped": int(archive_clipped),
        "service_region_removed": int(service_region_removed),
        "under_frame_removed": int(under_frame_removed),
        "top_outer_frame_removed": int(top_outer_frame_removed),
    }


def _clip_axis_segment_to_rect(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    rect_mm: tuple[float, float, float, float],
    eps_mm: float = 0.25,
) -> list[tuple[float, float]] | None:
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    rx0, ry0, rx1, ry1 = [float(v) for v in rect_mm]
    if abs(ay - by) <= float(eps_mm):
        y = (ay + by) * 0.5
        if y < ry0 - eps_mm or y > ry1 + eps_mm:
            return None
        sx0, sx1 = sorted((ax, bx))
        ix0 = max(sx0, rx0)
        ix1 = min(sx1, rx1)
        if ix1 - ix0 <= eps_mm:
            return None
        if ax <= bx:
            return [(ix0, y), (ix1, y)]
        return [(ix1, y), (ix0, y)]
    if abs(ax - bx) <= float(eps_mm):
        x = (ax + bx) * 0.5
        if x < rx0 - eps_mm or x > rx1 + eps_mm:
            return None
        sy0, sy1 = sorted((ay, by))
        iy0 = max(sy0, ry0)
        iy1 = min(sy1, ry1)
        if iy1 - iy0 <= eps_mm:
            return None
        if ay <= by:
            return [(x, iy0), (x, iy1)]
        return [(x, iy1), (x, iy0)]
    return None


def _strip_kompas_a3_outer_sheet_frame_polylines(
    polylines: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
    stamp_keep_w_mm: float = 190.0,
    stamp_keep_h_mm: float = 62.0,
) -> tuple[list[list[tuple[float, float]]], dict[str, Any]]:
    """Remove only the large KOMPAS sheet border on A3/A2 drawing packs.

    The title block often uses the bottom/right sheet border as its own border,
    so edge segments are clipped instead of blindly removed when they overlap
    the stamp area.
    """
    source_polys = [list(poly) for poly in polylines if len(poly) >= 2]
    if not source_polys:
        return [], {"applied": False, "removed_segments": 0, "kept_stamp_segments": 0}

    def _fallback_outer_frame_bbox() -> tuple[float, float, float, float] | None:
        horizontal_edges: list[tuple[float, float, float]] = []
        vertical_edges: list[tuple[float, float, float]] = []
        for candidate_poly in source_polys:
            for idx in range(1, len(candidate_poly)):
                ax, ay = candidate_poly[idx - 1]
                bx, by = candidate_poly[idx]
                x0, x1 = sorted((float(ax), float(bx)))
                y0, y1 = sorted((float(ay), float(by)))
                bw = x1 - x0
                bh = y1 - y0
                if bh <= 0.40 and bw >= max(100.0, float(page_w_mm) * 0.45):
                    horizontal_edges.append((x0, (y0 + y1) * 0.5, x1))
                if bw <= 0.40 and bh >= max(80.0, float(page_h_mm) * 0.45):
                    vertical_edges.append(((x0 + x1) * 0.5, y0, y1))
        if len(horizontal_edges) < 2:
            return None
        fx0 = min(row[0] for row in horizontal_edges)
        fx1 = max(row[2] for row in horizontal_edges)
        fy0 = min(row[1] for row in horizontal_edges)
        fy1 = max(row[1] for row in horizontal_edges)
        if vertical_edges:
            fx0 = min(fx0, min(row[0] for row in vertical_edges))
            fx1 = max(fx1, max(row[0] for row in vertical_edges))
            fy0 = min(fy0, min(row[1] for row in vertical_edges))
            fy1 = max(fy1, max(row[2] for row in vertical_edges))
        return fx0, fy0, fx1, fy1

    frame_bbox = _structural_outer_frame_bbox_mm(source_polys)
    fx0, fy0, fx1, fy1 = [float(v) for v in frame_bbox]
    fw = max(1e-9, fx1 - fx0)
    fh = max(1e-9, fy1 - fy0)
    if fw < 250.0 or fh < 180.0:
        fallback_bbox = _fallback_outer_frame_bbox()
        if fallback_bbox is None:
            return source_polys, {
                "applied": False,
                "removed_segments": 0,
                "kept_stamp_segments": 0,
                "source_bbox": [round(float(v), 4) for v in frame_bbox],
                "reason": "outer_frame_too_small_for_a3",
            }
        frame_bbox = fallback_bbox
        fx0, fy0, fx1, fy1 = [float(v) for v in frame_bbox]
        fw = max(1e-9, fx1 - fx0)
        fh = max(1e-9, fy1 - fy0)

    stamp_x0 = max(fx0, fx1 - float(stamp_keep_w_mm))
    stamp_y0 = max(fy0, fy1 - float(stamp_keep_h_mm))
    stamp_rect = (stamp_x0, stamp_y0, fx1, fy1)
    edge_eps = 0.45
    removed_segments = 0
    kept_stamp_segments = 0
    kept: list[list[tuple[float, float]]] = []

    for poly in source_polys:
        current: list[tuple[float, float]] = []
        for idx in range(1, len(poly)):
            a = (float(poly[idx - 1][0]), float(poly[idx - 1][1]))
            b = (float(poly[idx][0]), float(poly[idx][1]))
            ax, ay = a
            bx, by = b
            dx = abs(bx - ax)
            dy = abs(by - ay)
            horizontal_edge = dy <= edge_eps and dx >= max(40.0, fw * 0.35) and (
                abs(((ay + by) * 0.5) - fy0) <= edge_eps
                or abs(((ay + by) * 0.5) - fy1) <= edge_eps
            )
            vertical_edge = dx <= edge_eps and dy >= max(40.0, fh * 0.35) and (
                abs(((ax + bx) * 0.5) - fx0) <= edge_eps
                or abs(((ax + bx) * 0.5) - fx1) <= edge_eps
            )
            if horizontal_edge or vertical_edge:
                clipped = _clip_axis_segment_to_rect(a, b, rect_mm=stamp_rect, eps_mm=edge_eps)
                if len(current) >= 2:
                    kept.append(current)
                current = []
                removed_segments += 1
                if clipped is not None and len(clipped) >= 2:
                    kept.append(clipped)
                    kept_stamp_segments += 1
                continue
            if not current:
                current = [a]
            current.append(b)
        if len(current) >= 2:
            kept.append(current)

    if removed_segments <= 0:
        return source_polys, {
            "applied": False,
            "removed_segments": 0,
            "kept_stamp_segments": 0,
            "source_bbox": [round(float(v), 4) for v in frame_bbox],
        }
    if not kept:
        return source_polys, {
            "applied": False,
            "removed_segments": int(removed_segments),
            "kept_stamp_segments": int(kept_stamp_segments),
            "source_bbox": [round(float(v), 4) for v in frame_bbox],
            "reason": "would_remove_all_geometry",
        }
    return kept, {
        "applied": True,
        "removed_segments": int(removed_segments),
        "kept_stamp_segments": int(kept_stamp_segments),
        "source_bbox": [round(float(v), 4) for v in frame_bbox],
        "stamp_keep_rect": [round(float(v), 4) for v in stamp_rect],
    }


def _layout_similarity_pdf(source_pdf: Path, preview_pdf: Path, source_page_index: int = 0) -> float:
    src = _render_pdf_page_gray(source_pdf, page_index=source_page_index)
    cur = _render_pdf_page_gray(preview_pdf, page_index=0)
    if _drawing_frame_class(source_pdf) == "kompas_full_frame":
        specification_table = _is_kompas_specification_table_source(source_pdf)
        with fitz.open(str(source_pdf)) as src_doc:
            src_page_w_mm = float(src_doc[source_page_index].rect.width) * 25.4 / 72.0
            src_page_h_mm = float(src_doc[source_page_index].rect.height) * 25.4 / 72.0
        with fitz.open(str(preview_pdf)) as cur_doc:
            cur_page_w_mm = float(cur_doc[0].rect.width) * 25.4 / 72.0
            cur_page_h_mm = float(cur_doc[0].rect.height) * 25.4 / 72.0
        src = _apply_kompas_metric_mask(
            src,
            page_w_mm=src_page_w_mm,
            page_h_mm=src_page_h_mm,
            specification_table=specification_table,
        )
        cur = _apply_kompas_metric_mask(
            cur,
            page_w_mm=cur_page_w_mm,
            page_h_mm=cur_page_h_mm,
            specification_table=specification_table,
        )
    src = _crop_content(src)
    cur = _crop_content(cur)
    size = (512, 512)
    src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
    cur = cv2.resize(cur, size, interpolation=cv2.INTER_AREA)
    src = cv2.GaussianBlur(src, (0, 0), 1.2)
    cur = cv2.GaussianBlur(cur, (0, 0), 1.2)
    score = 1.0 - float(np.mean(np.abs(src.astype(np.float32) - cur.astype(np.float32))) / 255.0)
    return round(score, 6)


def _normalized_gray_alignment_metrics(src: np.ndarray, cur: np.ndarray) -> tuple[float, float]:
    if src.size == 0 or cur.size == 0:
        return 0.0, 0.0
    size = (512, 512)
    src_resized = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
    cur_resized = cv2.resize(cur, size, interpolation=cv2.INTER_AREA)
    src_resized = cv2.GaussianBlur(src_resized, (0, 0), 1.0)
    cur_resized = cv2.GaussianBlur(cur_resized, (0, 0), 1.0)
    src_mask = src_resized < 245
    cur_mask = cur_resized < 245
    union = float(np.logical_or(src_mask, cur_mask).sum())
    iou = float(np.logical_and(src_mask, cur_mask).sum()) / union if union else 1.0
    src_inv = (255 - src_resized).astype(np.float32).ravel()
    cur_inv = (255 - cur_resized).astype(np.float32).ravel()
    if src_inv.size == 0 or cur_inv.size == 0:
        return float(iou), 0.0
    src_std = float(src_inv.std())
    cur_std = float(cur_inv.std())
    if src_std <= 1e-6 or cur_std <= 1e-6:
        corr = 0.0
    else:
        corr = float(np.corrcoef(src_inv, cur_inv)[0, 1])
        if not np.isfinite(corr):
            corr = 0.0
    return float(iou), float(corr)


def _bottom_right_region(gray: np.ndarray, *, width_ratio: float = 0.42, height_ratio: float = 0.34) -> np.ndarray:
    if gray.size == 0:
        return gray
    h, w = gray.shape[:2]
    crop_w = max(1, int(round(float(w) * float(width_ratio))))
    crop_h = max(1, int(round(float(h) * float(height_ratio))))
    return gray[max(0, h - crop_h) : h, max(0, w - crop_w) : w]


def _source_crop_alignment_metrics(source_pdf: Path, preview_pdf: Path, source_page_index: int = 0) -> dict[str, float]:
    try:
        src = _render_pdf_page_gray(source_pdf, page_index=source_page_index, dpi=120)
        cur = _render_pdf_page_gray(preview_pdf, page_index=0, dpi=120)
        with fitz.open(str(source_pdf)) as src_doc:
            src_page_w_mm = float(src_doc[source_page_index].rect.width) * 25.4 / 72.0
            src_page_h_mm = float(src_doc[source_page_index].rect.height) * 25.4 / 72.0
        with fitz.open(str(preview_pdf)) as cur_doc:
            cur_page_w_mm = float(cur_doc[0].rect.width) * 25.4 / 72.0
            cur_page_h_mm = float(cur_doc[0].rect.height) * 25.4 / 72.0
    except Exception:
        return {
            "source_crop_corr": 0.0,
            "source_crop_iou": 0.0,
            "source_crop_x_px": 0.0,
            "source_crop_y_px": 0.0,
        }

    if src.size == 0 or cur.size == 0:
        return {
            "source_crop_corr": 0.0,
            "source_crop_iou": 0.0,
            "source_crop_x_px": 0.0,
            "source_crop_y_px": 0.0,
        }

    if _drawing_frame_class(source_pdf) == "kompas_full_frame":
        specification_table = _is_kompas_specification_table_source(source_pdf)
        src = _apply_kompas_metric_mask(
            src,
            page_w_mm=src_page_w_mm,
            page_h_mm=src_page_h_mm,
            specification_table=specification_table,
        )
        cur = _apply_kompas_metric_mask(
            cur,
            page_w_mm=cur_page_w_mm,
            page_h_mm=cur_page_h_mm,
            specification_table=specification_table,
        )

    if src.shape[0] < cur.shape[0] or src.shape[1] < cur.shape[1]:
        h = min(int(src.shape[0]), int(cur.shape[0]))
        w = min(int(src.shape[1]), int(cur.shape[1]))
        src_crop = src[:h, :w]
        cur_crop = cur[:h, :w]
        src_mask = src_crop < 245
        cur_mask = cur_crop < 245
        union = float(np.logical_or(src_mask, cur_mask).sum())
        iou = float(np.logical_and(src_mask, cur_mask).sum()) / union if union else 1.0
        return {
            "source_crop_corr": 0.0,
            "source_crop_iou": round(float(iou), 6),
            "source_crop_x_px": 0.0,
            "source_crop_y_px": 0.0,
        }

    src_inv = 255 - src
    cur_inv = 255 - cur
    result = cv2.matchTemplate(src_inv, cur_inv, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    x0, y0 = int(max_loc[0]), int(max_loc[1])
    src_crop = src[y0 : y0 + cur.shape[0], x0 : x0 + cur.shape[1]]
    if src_crop.shape != cur.shape:
        h = min(int(src_crop.shape[0]), int(cur.shape[0]))
        w = min(int(src_crop.shape[1]), int(cur.shape[1]))
        src_crop = src_crop[:h, :w]
        cur = cur[:h, :w]
    src_mask = src_crop < 245
    cur_mask = cur < 245
    union = float(np.logical_or(src_mask, cur_mask).sum())
    iou = float(np.logical_and(src_mask, cur_mask).sum()) / union if union else 1.0

    cropped_src = _crop_content(src)
    cropped_cur = _crop_content(cur)
    cropped_iou, cropped_corr = _normalized_gray_alignment_metrics(cropped_src, cropped_cur)
    title_iou, title_corr = _normalized_gray_alignment_metrics(
        _bottom_right_region(cropped_src),
        _bottom_right_region(cropped_cur),
    )
    blended_iou = max(
        float(iou),
        (0.60 * float(cropped_iou)) + (0.40 * float(title_iou)),
    )
    blended_corr = max(
        float(max_val),
        (0.65 * float(cropped_corr)) + (0.35 * float(title_corr)),
    )
    return {
        "source_crop_corr": round(float(blended_corr), 6),
        "source_crop_iou": round(float(blended_iou), 6),
        "source_crop_x_px": float(x0),
        "source_crop_y_px": float(y0),
    }


def _render_compare_pdf(pdf_path: Path, zoom: float = 1.25) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    finally:
        doc.close()


def _fit_compare_image(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    out = img.copy()
    out.thumbnail((max_w, max_h))
    return out


def _make_compare_panel(images: list[tuple[str, Image.Image]], title: str) -> Image.Image:
    cell_w = 320
    cell_h = 260
    label_h = 36
    cols = max(1, len(images))
    panel = Image.new("RGB", (cell_w * cols, cell_h + label_h + 26), "white")
    draw = ImageDraw.Draw(panel)
    draw.text((8, 6), title, fill="black")
    for idx, (label, img) in enumerate(images):
        thumb = _fit_compare_image(img, cell_w - 12, cell_h - 12)
        x0 = idx * cell_w
        x = x0 + (cell_w - thumb.width) // 2
        y = 24 + (cell_h - thumb.height) // 2
        panel.paste(thumb, (x, y))
        draw.text((x0 + 8, cell_h + 26), label, fill="black")
    return panel


def _save_package_compare_artifacts(package_dir: Path, panel: Image.Image) -> tuple[Path, Path]:
    png_path = package_dir / "source_vs_gcode_compare.png"
    pdf_path = package_dir / "source_vs_gcode_compare.pdf"
    panel.save(png_path)
    panel.convert("RGB").save(pdf_path, "PDF", resolution=150.0)
    return png_path, pdf_path


def _generate_package_compare_artifacts(
    package_dir: Path,
    report: dict[str, Any],
    package_rows: list[ArtifactRow],
) -> dict[str, Any]:
    if str(report.get("kind", "") or "") != "drawing":
        return {"compare_generated": False}
    title = package_dir.name
    source_pdf_raw = str(report.get("source_pdf", "") or "").strip()
    source_pdf = Path(source_pdf_raw) if source_pdf_raw else None
    try:
        if len(package_rows) == 1 and package_rows[0].item == "page_01":
            row = package_rows[0]
            preview_pdf = Path(str(row.preview_pdf))
            reference_pdf = source_pdf
            clean_meta = dict(report.get("a4_clean_source", {}) or {})
            clean_pdf_raw = str(clean_meta.get("pdf", "") or "").strip()
            if clean_pdf_raw:
                clean_pdf = Path(clean_pdf_raw)
                if clean_pdf.exists() and clean_pdf.is_file():
                    reference_pdf = clean_pdf
            if reference_pdf is None or not reference_pdf.exists() or not preview_pdf.exists():
                return {"compare_generated": False}
            panel = _make_compare_panel(
                [
                    ("source", _render_compare_pdf(reference_pdf, 1.0)),
                    ("preview", _render_compare_pdf(preview_pdf, 1.0)),
                ],
                title,
            )
            compare_png, compare_pdf = _save_package_compare_artifacts(package_dir, panel)
            return {
                "compare_generated": True,
                "compare": {
                    "png": str(compare_png),
                    "pdf": str(compare_pdf),
                    "reference_pdf": str(reference_pdf),
                    "preview_pdf": str(preview_pdf),
                },
            }

        pass1 = next((row for row in package_rows if row.item == "pass_01" and row.ok), None)
        pass2 = next((row for row in package_rows if row.item == "pass_02" and row.ok), None)
        if pass1 is None or pass2 is None:
            return {"compare_generated": False}
        combined_meta = dict(report.get("combined_preview", {}) or {})
        combined_pdf_raw = str(combined_meta.get("pdf", "") or "").strip()
        reference_pdf_raw = str(combined_meta.get("reference_pdf", "") or "").strip()
        combined_pdf = Path(combined_pdf_raw) if combined_pdf_raw else Path(str(pass1.preview_pdf))
        reference_pdf = Path(reference_pdf_raw) if reference_pdf_raw else source_pdf
        if reference_pdf is None or not reference_pdf.exists():
            reference_pdf = source_pdf
        if combined_pdf is None or not combined_pdf.exists() or reference_pdf is None or not reference_pdf.exists():
            return {"compare_generated": False}
        panel = _make_compare_panel(
            [
                ("source", _render_compare_pdf(reference_pdf, 0.75)),
                ("combined", _render_compare_pdf(combined_pdf, 0.75)),
                ("pass_01", _render_compare_pdf(Path(str(pass1.preview_pdf)), 1.0)),
                ("pass_02", _render_compare_pdf(Path(str(pass2.preview_pdf)), 1.0)),
            ],
            title,
        )
        compare_png, compare_pdf = _save_package_compare_artifacts(package_dir, panel)
        return {
            "compare_generated": True,
            "compare": {
                "png": str(compare_png),
                "pdf": str(compare_pdf),
                "reference_pdf": str(reference_pdf),
                "combined_pdf": str(combined_pdf),
                "pass_01_pdf": str(pass1.preview_pdf),
                "pass_02_pdf": str(pass2.preview_pdf),
            },
        }
    except Exception as exc:
        return {
            "compare_generated": False,
            "compare_error": str(exc),
        }


def _drawing_quality_score(
    *,
    layout_similarity: float | None,
    source_fidelity_score: float | None,
    fragmentation_score: float | None,
) -> float | None:
    parts: list[tuple[float, float]] = []
    if layout_similarity is not None:
        parts.append((0.75, float(layout_similarity)))
    if source_fidelity_score is not None:
        parts.append((0.15, float(source_fidelity_score)))
    if fragmentation_score is not None:
        parts.append((0.10, float(fragmentation_score)))
    if not parts:
        return None
    total_weight = sum(weight for weight, _value in parts)
    if total_weight <= 1e-9:
        return None
    return round(sum(weight * value for weight, value in parts) / total_weight, 6)


def _write_root_drawing_audit(folder: Path, rows: list[ArtifactRow], reports: list[dict[str, Any]]) -> None:
    drawing_rows = [row for row in rows if str(row.kind) == "drawing"]
    if not drawing_rows:
        return
    reports_by_package: dict[str, dict[str, Any]] = {}
    for report in reports:
        if str(report.get("kind", "") or "") != "drawing":
            continue
        package_dir_text = str(report.get("package_dir", "") or "").strip()
        if package_dir_text:
            reports_by_package[package_dir_text] = report

    rows_by_package: dict[str, list[ArtifactRow]] = {}
    for row in drawing_rows:
        rows_by_package.setdefault(str(row.package_dir), []).append(row)

    audit_rows: list[dict[str, Any]] = []
    contact_panels: list[Image.Image] = []
    for package_dir_text, package_rows in sorted(rows_by_package.items()):
        package_dir = Path(package_dir_text)
        report = reports_by_package.get(package_dir_text, {})
        compare_meta = dict(report.get("compare", {}) or {})
        compare_png_raw = str(compare_meta.get("png", "") or "").strip()
        if not compare_png_raw or not Path(compare_png_raw).exists():
            compare_result = _generate_package_compare_artifacts(package_dir, report, package_rows)
            report["compare_generated"] = bool(compare_result.get("compare_generated"))
            if "compare" in compare_result:
                report["compare"] = dict(compare_result.get("compare", {}) or {})
                compare_meta = dict(report.get("compare", {}) or {})
                compare_png_raw = str(compare_meta.get("png", "") or "").strip()
        compare_pdf_raw = str(compare_meta.get("pdf", "") or "").strip()

        layout_similarity = None
        if len(package_rows) == 1 and package_rows[0].item == "page_01":
            layout_similarity = package_rows[0].layout_similarity
        else:
            combined_meta = dict(report.get("combined_preview", {}) or {})
            if str(combined_meta.get("layout_similarity", "")).strip() not in {"", "None"}:
                layout_similarity = float(combined_meta.get("layout_similarity", 0.0) or 0.0)
        source_fidelity_score = report.get("source_fidelity_score")
        fragmentation_score = report.get("fragmentation_score")
        try:
            source_fidelity_score = None if source_fidelity_score in (None, "") else float(source_fidelity_score)
        except (TypeError, ValueError):
            source_fidelity_score = None
        try:
            fragmentation_score = None if fragmentation_score in (None, "") else float(fragmentation_score)
        except (TypeError, ValueError):
            fragmentation_score = None
        quality_score = _drawing_quality_score(
            layout_similarity=layout_similarity,
            source_fidelity_score=source_fidelity_score,
            fragmentation_score=fragmentation_score,
        )

        audit_rows.append(
            {
                "task": package_dir.name,
                "package_dir": str(package_dir),
                "kind": "a4" if len(package_rows) == 1 and package_rows[0].item == "page_01" else "a3_two_pass",
                "layout_similarity": layout_similarity,
                "selected_variant": str(report.get("selected_variant", "") or ""),
                "selection_reason": str(report.get("selection_reason", "") or ""),
                "source_fidelity_score": source_fidelity_score,
                "fragmentation_score": fragmentation_score,
                "quality_score": quality_score,
                "compare_png": compare_png_raw,
                "compare_pdf": compare_pdf_raw,
            }
        )

        if compare_png_raw:
            try:
                with Image.open(compare_png_raw) as img:
                    contact_panels.append(img.convert("RGB"))
            except Exception:
                pass

    if contact_panels:
        width = max(panel.width for panel in contact_panels)
        height = sum(panel.height for panel in contact_panels)
        contact = Image.new("RGB", (width, height), "#dddddd")
        y = 0
        for panel in contact_panels:
            contact.paste(panel, (0, y))
            y += panel.height
        contact.save(folder / "_audit_contact.png")

    (folder / "_audit.json").write_text(
        json.dumps({"variant_dir": str(folder), "items": audit_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ranked_rows: list[tuple[float, float | None, float | None, str]] = []
    for row in audit_rows:
        quality = row.get("quality_score")
        if quality in (None, ""):
            continue
        try:
            ranked_rows.append(
                (
                    float(quality),
                    row.get("layout_similarity"),
                    row.get("source_fidelity_score"),
                    str(row.get("task", "")),
                )
            )
        except (TypeError, ValueError):
            continue
    ranked_rows.sort(key=lambda item: item[0])
    summary_lines = [folder.name]
    for score, layout_similarity, source_fidelity_score, task in ranked_rows:
        layout_text = "n/a" if layout_similarity in (None, "") else f"{float(layout_similarity):.6f}"
        fidelity_text = "n/a" if source_fidelity_score in (None, "") else f"{float(source_fidelity_score):.6f}"
        summary_lines.append(f"{task}: quality={score:.6f}; layout={layout_text}; fidelity={fidelity_text}")
    (folder / "_audit.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


def _parse_segment_counts(logs: list[str]) -> tuple[int, int, int] | None:
    rx = re.compile(r"Segment counts: source=(\d+), fitted=(\d+), clipped=(\d+)")
    for line in logs:
        match = rx.search(str(line))
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None


def _segment_key(a: tuple[float, float], b: tuple[float, float], ndigits: int = 3) -> tuple[tuple[float, float], tuple[float, float]]:
    p0 = (round(float(a[0]), ndigits), round(float(a[1]), ndigits))
    p1 = (round(float(b[0]), ndigits), round(float(b[1]), ndigits))
    return (p0, p1) if p0 <= p1 else (p1, p0)


def _polyline_length(poly: list[tuple[float, float]]) -> float:
    total = 0.0
    for idx in range(1, len(poly)):
        x0, y0 = poly[idx - 1]
        x1, y1 = poly[idx]
        total += float(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    return total


def _clip_polyline_max_x_mm(
    poly: list[tuple[float, float]],
    max_x_mm: float,
    *,
    eps: float = 1e-6,
) -> list[list[tuple[float, float]]]:
    if len(poly) < 2:
        return []

    def _inside(pt: tuple[float, float]) -> bool:
        return float(pt[0]) <= float(max_x_mm) + float(eps)

    def _intersect(p0: tuple[float, float], p1: tuple[float, float]) -> tuple[float, float]:
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
        dx = x1 - x0
        if abs(dx) <= float(eps):
            return (float(max_x_mm), y0)
        t = (float(max_x_mm) - x0) / dx
        t = max(0.0, min(1.0, t))
        return (float(max_x_mm), y0 + ((y1 - y0) * t))

    clipped: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    prev = (float(poly[0][0]), float(poly[0][1]))
    prev_inside = _inside(prev)
    if prev_inside:
        current.append((min(float(prev[0]), float(max_x_mm)), float(prev[1])))

    for idx in range(1, len(poly)):
        cur = (float(poly[idx][0]), float(poly[idx][1]))
        cur_inside = _inside(cur)
        if prev_inside and cur_inside:
            if not current:
                current.append((min(float(prev[0]), float(max_x_mm)), float(prev[1])))
            current.append((min(float(cur[0]), float(max_x_mm)), float(cur[1])))
        elif prev_inside and not cur_inside:
            if not current:
                current.append((min(float(prev[0]), float(max_x_mm)), float(prev[1])))
            current.append(_intersect(prev, cur))
            if len(current) >= 2:
                clipped.append(current)
            current = []
        elif (not prev_inside) and cur_inside:
            current = [_intersect(prev, cur), (min(float(cur[0]), float(max_x_mm)), float(cur[1]))]
        prev = cur
        prev_inside = cur_inside

    if len(current) >= 2:
        clipped.append(current)
    return clipped


def _cleanup_a4_header_gutter_artifacts(
    polys_mm: list[list[tuple[float, float]]],
    *,
    header_thumb_x1_mm: float,
    header_text_x0_mm: float,
    top_band_y1_mm: float,
    gutter_pad_left_mm: float = 1.6,
    gutter_pad_right_mm: float = 1.8,
    max_len_mm: float = 2.0,
    max_w_mm: float = 2.0,
    max_h_mm: float = 2.0,
) -> tuple[list[list[tuple[float, float]]], int]:
    cleaned: list[list[tuple[float, float]]] = []
    removed = 0
    gutter_x0 = max(0.0, float(header_thumb_x1_mm) - float(gutter_pad_left_mm))
    gutter_x1 = max(gutter_x0, float(header_text_x0_mm) + float(gutter_pad_right_mm))
    for poly in polys_mm:
        if len(poly) < 2:
            continue
        px0, py0, px1, py1 = _poly_bbox_mm(poly)
        bw = float(px1 - px0)
        bh = float(py1 - py0)
        if (
            float(py1) <= float(top_band_y1_mm)
            and float(px0) >= float(gutter_x0)
            and float(px1) <= float(gutter_x1)
            and bw <= float(max_w_mm)
            and bh <= float(max_h_mm)
            and _polyline_length(poly) <= float(max_len_mm)
        ):
            removed += 1
            continue
        cleaned.append(poly)
    return cleaned, removed


def _ensure_a4_header_bottom_separator(
    polys_mm: list[list[tuple[float, float]]],
    *,
    header_lines: list[dict[str, Any]],
    src_y0: float,
    header_scale_y: float,
    target_w_mm: float,
) -> tuple[list[list[tuple[float, float]]], bool]:
    if not polys_mm or not header_lines:
        return list(polys_mm), False

    text_bottom_y = 0.0
    for line in header_lines:
        bbox_mm = tuple(line.get("bbox_mm", ()) or ())
        if len(bbox_mm) < 4:
            continue
        box_y1 = float(bbox_mm[3])
        text_bottom_y = max(text_bottom_y, (float(box_y1) - float(src_y0)) * float(header_scale_y))
    if text_bottom_y <= 0.0:
        return list(polys_mm), False

    separator_y = min(float(_A4_HEADER_CONTENT_MAX_Y_MM), float(text_bottom_y) + 4.0)
    right_x = 0.0
    for poly in polys_mm:
        if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly, eps=0.18):
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if bh <= 0.75 and bw >= 100.0 and float(y1) <= 8.0:
            right_x = max(right_x, float(x1))
    if right_x <= 0.0:
        right_x = float(target_w_mm)

    for poly in polys_mm:
        if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly, eps=0.18):
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if (
            bh <= 0.75
            and bw >= max(70.0, float(right_x) * 0.55)
            and abs(float(y0) - float(separator_y)) <= 1.25
            and abs(float(y1) - float(separator_y)) <= 1.25
        ):
            return list(polys_mm), False

    out = list(polys_mm)
    out.append([(0.0, float(separator_y)), (float(right_x), float(separator_y))])
    return out, True


def _remove_a4_header_thumb_full_width_duplicate(
    polys_mm: list[list[tuple[float, float]]],
    *,
    header_thumb_x1_mm: float,
    separator_y_mm: float,
) -> tuple[list[list[tuple[float, float]]], int]:
    cleaned: list[list[tuple[float, float]]] = []
    removed = 0
    for poly in polys_mm:
        if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly, eps=0.18):
            cleaned.append(poly)
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if (
            bh <= 0.75
            and abs(float(y0) - float(separator_y_mm)) <= 1.6
            and abs(float(y1) - float(separator_y_mm)) <= 1.6
            and float(x1) <= (float(header_thumb_x1_mm) + 0.5)
            and bw >= max(20.0, float(header_thumb_x1_mm) * 0.55)
            and (float(x0) <= 1.0 or float(x1) >= (float(header_thumb_x1_mm) - 1.0))
        ):
            removed += 1
            continue
        cleaned.append(poly)
    return cleaned, removed


def _dedupe_a4_header_band_axis_lines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    top_band_y1_mm: float,
    axis_eps_mm: float = 0.9,
    min_span_mm: float = 12.0,
    overlap_ratio: float = 0.9,
) -> tuple[list[list[tuple[float, float]]], int]:
    def _line_meta(poly: list[tuple[float, float]]) -> tuple[str, float, float, float] | None:
        if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly, eps=0.18):
            return None
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if float(y1) > float(top_band_y1_mm):
            return None
        if bh <= 0.75 and bw >= float(min_span_mm):
            return ("h", (float(y0) + float(y1)) * 0.5, float(x0), float(x1))
        if bw <= 0.75 and bh >= float(min_span_mm):
            return ("v", (float(x0) + float(x1)) * 0.5, float(y0), float(y1))
        return None

    def _overlap_ok(a0: float, a1: float, b0: float, b1: float) -> bool:
        overlap = min(float(a1), float(b1)) - max(float(a0), float(b0))
        if overlap <= 0.0:
            return False
        shorter = min(float(a1) - float(a0), float(b1) - float(b0))
        return overlap >= float(shorter) * float(overlap_ratio)

    cleaned: list[list[tuple[float, float]]] = []
    kept_meta: list[tuple[str, float, float, float, int]] = []
    removed = 0
    for poly in polys_mm:
        meta = _line_meta(poly)
        if meta is None:
            cleaned.append(poly)
            continue
        orient, pos, span0, span1 = meta
        duplicate_idx: int | None = None
        for idx, (k_orient, k_pos, k0, k1, clean_idx) in enumerate(kept_meta):
            if orient != k_orient:
                continue
            if abs(float(pos) - float(k_pos)) > float(axis_eps_mm):
                continue
            if not _overlap_ok(float(span0), float(span1), float(k0), float(k1)):
                continue
            duplicate_idx = idx
            break
        if duplicate_idx is None:
            cleaned.append(poly)
            kept_meta.append((orient, float(pos), float(span0), float(span1), len(cleaned) - 1))
            continue
        _k_orient, _k_pos, k0, k1, clean_idx = kept_meta[duplicate_idx]
        cur_len = float(span1) - float(span0)
        kept_len = float(k1) - float(k0)
        if cur_len > kept_len:
            cleaned[clean_idx] = poly
            kept_meta[duplicate_idx] = (orient, float(pos), float(span0), float(span1), clean_idx)
        removed += 1
    return cleaned, removed


def _ensure_a4_outer_top_right_frame_lines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    target_w_mm: float,
    target_h_mm: float,
    tol_mm: float = 1.2,
) -> tuple[list[list[tuple[float, float]]], int]:
    if not polys_mm:
        return polys_mm, 0

    has_top = False
    has_right = False
    min_h_span = float(target_w_mm) * 0.82
    min_v_span = float(target_h_mm) * 0.82

    for poly in polys_mm:
        if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly, eps=0.18):
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if bh <= 0.9 and bw >= min_h_span and min(float(y0), float(y1)) <= float(tol_mm):
            has_top = True
        if bw <= 0.9 and bh >= min_v_span and abs(float(x1) - float(target_w_mm)) <= float(tol_mm):
            has_right = True

    added = 0
    if not has_top:
        polys_mm.append([(0.0, 0.0), (float(target_w_mm), 0.0)])
        added += 1
    if not has_right:
        polys_mm.append([(float(target_w_mm), 0.0), (float(target_w_mm), float(target_h_mm))])
        added += 1
    return polys_mm, added


def _extract_a4_header_text_lines_from_pdf(
    source_pdf: Path,
    *,
    page_index: int,
) -> list[dict[str, Any]]:
    if fitz is None:
        return []
    doc = fitz.open(str(source_pdf))
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            return []
        page = doc[page_index]
        best: list[dict[str, Any]] = []
        best_width = 0.0
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            bbox = list(block.get("bbox", []) or [])
            if len(bbox) < 4:
                continue
            x0_mm, y0_mm, x1_mm, y1_mm = [float(v) * 25.4 / 72.0 for v in bbox]
            if y0_mm > 55.0 or y1_mm < 5.0 or x0_mm < 30.0:
                continue
            if (x1_mm - x0_mm) < 70.0:
                continue
            lines: list[dict[str, Any]] = []
            for line in block.get("lines", []):
                line_bbox = list(line.get("bbox", []) or [])
                if len(line_bbox) < 4:
                    continue
                text = "".join(str(span.get("text", "")) for span in line.get("spans", [])).strip()
                if not text:
                    continue
                if sum(1 for ch in text if ch.isalpha()) < 6:
                    continue
                lx0_mm, ly0_mm, lx1_mm, ly1_mm = [float(v) * 25.4 / 72.0 for v in line_bbox]
                lines.append(
                    {
                        "text": text,
                        "bbox_mm": (float(lx0_mm), float(ly0_mm), float(lx1_mm), float(ly1_mm)),
                    }
                )
            if len(lines) < 2:
                continue
            block_width = float(x1_mm - x0_mm)
            if block_width > best_width:
                best_width = block_width
                best = lines
        return best
    finally:
        doc.close()


def _extract_title_block_text_lines_from_pdf(
    source_pdf: Path,
    *,
    page_index: int,
) -> list[dict[str, Any]]:
    if fitz is None:
        return []
    doc = fitz.open(str(source_pdf))
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            return []
        page = doc[page_index]
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
        min_y_mm = max(float(page_h_mm) - max(82.0, float(page_h_mm) * 0.26), float(page_h_mm) * 0.66)
        min_x_mm = max(0.0, float(page_w_mm) * 0.14)
        lines: list[dict[str, Any]] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = list(line.get("bbox", []) or [])
                if len(line_bbox) < 4:
                    continue
                text = "".join(str(span.get("text", "")) for span in line.get("spans", [])).strip()
                if not text:
                    continue
                lx0_mm, ly0_mm, lx1_mm, ly1_mm = [float(v) * 25.4 / 72.0 for v in line_bbox]
                if float(ly0_mm) < float(min_y_mm):
                    continue
                if float(lx1_mm) < float(min_x_mm):
                    continue
                if (float(lx1_mm) - float(lx0_mm)) < 3.0 and (float(ly1_mm) - float(ly0_mm)) < 3.0:
                    continue
                lines.append(
                    {
                        "text": text,
                        "bbox_mm": (float(lx0_mm), float(ly0_mm), float(lx1_mm), float(ly1_mm)),
                    }
                )
        lines.sort(key=lambda row: (float(row["bbox_mm"][1]), float(row["bbox_mm"][0]), str(row["text"])))
        return lines
    finally:
        doc.close()


def _kompas_preserve_source_text_region_mm(
    bbox_mm: tuple[float, float, float, float],
    *,
    page_h_mm: float,
    archive_cutoff_x_mm: float,
) -> bool:
    x0, y0, _x1, y1 = [float(v) for v in bbox_mm]
    # The KOMPAS title block and the top designation cell are very sensitive:
    # their tiny italic text uses KOMPAS font metrics that do not match our
    # single-line TTF fallback closely enough. Keep the source vectors there
    # and reroute only drawing/dimension text.
    if y0 >= float(page_h_mm) - 60.5:
        return True
    if y1 <= 20.0 and x0 >= float(archive_cutoff_x_mm) - 1.0:
        return True
    return False


def _kompas_preserve_source_text_value(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    compact_key = re.sub(r"[^0-9A-Za-zА-Яа-яЁё№]+", "", compact).casefold()
    stamp_label_values = {
        "изм",
        "лист",
        "листов",
        "лит",
        "масса",
        "масштаб",
        "№докум",
        "подп",
        "дата",
        "разраб",
        "пров",
        "тконтр",
        "нконтр",
        "утв",
        "копировал",
        "формат",
        "недлякоммерческогоиспользования",
    }
    if compact_key in stamp_label_values:
        return False
    stamp_label_phrases = {
        "измлист",
        "изменлист",
        "листлистов",
        "подпдата",
    }
    if compact_key in stamp_label_phrases:
        return False
    # Dimension callouts and numeric labels are small and position-sensitive.
    # KOMPAS source vectors are more faithful there than our fallback TTF
    # skeleton, so do not replace them with generated single-line text.
    if len(compact) <= 20 and any(ch.isdigit() for ch in compact):
        return True
    dimension_marks = "RrMm\u041c\u043c\u00d8\u00f8\u2300\u03c6\u03a6\u0444\u00b0'\"\u2032\u2033+-/\u00b1"
    if len(compact) <= 12 and any(ch in dimension_marks for ch in compact):
        return True
    return False


def _extract_kompas_plot_text_lines_from_pdf(
    source_pdf: Path,
    *,
    page_index: int,
) -> list[dict[str, Any]]:
    """Return KOMPAS text lines that belong to the plotted drawing area.

    KOMPAS PDFs often export visible glyphs as vector outlines when converted
    with text_as_path=True. PyMuPDF still exposes the logical text and its
    bbox; use those bboxes to replace outline glyph fragments with single-line
    plotter text while keeping dimensions and frame vectors untouched.
    """

    if fitz is None or _drawing_frame_class(source_pdf) != "kompas_full_frame":
        return []
    doc = fitz.open(str(source_pdf))
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            return []
        page = doc[page_index]
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
        specification_table = _is_kompas_specification_table_source(source_pdf)
        archive_cutoff_x = _kompas_archive_strip_mm(page_w_mm, specification_table=specification_table)
        bottom_y = float(page_h_mm) - _kompas_under_frame_strip_mm(page_h_mm)
        service_regions = _kompas_service_regions_from_pdf(source_pdf, page_index=page_index)

        def _in_service_region(x0: float, y0: float, x1: float, y1: float) -> bool:
            cx = (float(x0) + float(x1)) * 0.5
            cy = (float(y0) + float(y1)) * 0.5
            for rx0, ry0, rx1, ry1 in service_regions:
                if float(rx0) <= cx <= float(rx1) and float(ry0) <= cy <= float(ry1):
                    return True
            return False

        lines: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int, int, int]] = set()
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = list(line.get("bbox", []) or [])
                if len(line_bbox) < 4:
                    continue
                spans = list(line.get("spans", []) or [])
                text = "".join(str(span.get("text", "") or "") for span in spans).strip()
                if not text:
                    continue
                lx0_mm, ly0_mm, lx1_mm, ly1_mm = [float(v) * 25.4 / 72.0 for v in line_bbox]
                line_w = float(lx1_mm) - float(lx0_mm)
                line_h = float(ly1_mm) - float(ly0_mm)
                if line_w < 0.45 or line_h < 0.45:
                    continue
                if not specification_table and float(lx1_mm) <= float(archive_cutoff_x) + 0.8:
                    continue
                if float(ly0_mm) >= float(bottom_y) - 0.5:
                    continue
                if _kompas_preserve_source_text_region_mm(
                    (float(lx0_mm), float(ly0_mm), float(lx1_mm), float(ly1_mm)),
                    page_h_mm=float(page_h_mm),
                    archive_cutoff_x_mm=float(archive_cutoff_x),
                ):
                    continue
                if _kompas_preserve_source_text_value(text):
                    continue
                if _in_service_region(float(lx0_mm), float(ly0_mm), float(lx1_mm), float(ly1_mm)):
                    continue
                key = (
                    text,
                    round(float(lx0_mm) * 100),
                    round(float(ly0_mm) * 100),
                    round(float(lx1_mm) * 100),
                    round(float(ly1_mm) * 100),
                )
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    {
                        "text": text,
                        "bbox_mm": (float(lx0_mm), float(ly0_mm), float(lx1_mm), float(ly1_mm)),
                        "font_names": [str(span.get("font", "") or "") for span in spans],
                    }
                )
        lines.sort(key=lambda row: (float(row["bbox_mm"][1]), float(row["bbox_mm"][0]), str(row["text"])))
        return lines
    finally:
        doc.close()


def _should_reroute_title_block_text(source_pdf: Path) -> bool:
    # KOMPAS title blocks are source-of-truth vectors. Earlier single-line
    # rerendering made the stamp less faithful and could move text baselines.
    return False


def _should_reroute_kompas_text(source_pdf: Path) -> bool:
    # Keep native KOMPAS text centerline fragments. Re-rendering text through
    # fonts changes glyph geometry too much for these drawings; the source
    # route below still uses centerline/averaging and stitch repair, not
    # outline contour tracing.
    return False


def _should_repair_kompas_stamp_title_text(source_pdf: Path) -> bool:
    return False


def _empty_kompas_text_meta() -> dict[str, float]:
    return {"kompas_text_lines": 0.0, "kompas_text_removed": 0.0, "kompas_text_rendered": 0.0}


def _empty_kompas_stamp_text_meta() -> dict[str, float]:
    return {
        "kompas_stamp_text_lines": 0.0,
        "kompas_stamp_text_removed": 0.0,
        "kompas_stamp_text_rendered": 0.0,
    }


def _logs_indicate_kompas_text_reroute(logs: Iterable[object] | None) -> bool:
    for line in logs or []:
        text = str(line)
        if "KOMPAS text reroute:" in text:
            return True
        match = re.search(r"kompas_text_rendered=(\d+)", text)
        if match and int(match.group(1)) > 0:
            return True
    return False


def _logs_indicate_kompas_stamp_text_repair(logs: Iterable[object] | None) -> bool:
    for line in logs or []:
        text = str(line)
        if "KOMPAS stamp/title text repair:" in text:
            return True
        match = re.search(r"kompas_stamp_text_rendered=(\d+)", text)
        if match and int(match.group(1)) > 0:
            return True
    return False


def _kompas_stamp_text_line_allowed(
    text: str,
    bbox_mm: tuple[float, float, float, float],
    *,
    page_w_mm: float,
    page_h_mm: float,
    archive_cutoff_x_mm: float,
    line_dir: tuple[float, float] | None = None,
) -> bool:
    """Select only KOMPAS title-block/top-designation text for repair.

    This is deliberately narrower than the old full KOMPAS text reroute: it
    targets the regions where real plotting showed broken `5`, `Г`, `Л`,
    `ЛТ-...` and drawing names, while leaving dimensions and geometry labels in
    the source vectors.
    """

    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    compact_key = re.sub(r"[^0-9A-Za-zА-Яа-яЁё№]+", "", compact).casefold()
    forbidden_service_values = {
        "копировал",
        "формат",
        "недлякоммерческогоиспользования",
    }
    if compact_key in forbidden_service_values:
        return False
    x0, y0, x1, y1 = [float(v) for v in bbox_mm]
    w = max(0.0, float(x1 - x0))
    h = max(0.0, float(y1 - y0))
    if w < 0.35 or h < 0.35:
        return False
    if line_dir is not None:
        dx, dy = [float(v) for v in line_dir]
        # Do not flatten rotated service notes into horizontal text.
        if abs(dy) > 0.20 and abs(dy) > abs(dx) * 0.28:
            return False

    bottom_cutoff = max(float(page_h_mm) - max(72.0, float(page_h_mm) * 0.23), float(page_h_mm) * 0.62)
    in_bottom_stamp = float(y0) >= float(bottom_cutoff) and float(x1) >= float(archive_cutoff_x_mm) - 1.0
    in_top_designation = (
        float(y1) <= min(34.0, float(page_h_mm) * 0.13)
        and float(x0) >= float(archive_cutoff_x_mm) - 1.0
        and float(x1) <= float(page_w_mm) - 2.0
    )
    if not (in_bottom_stamp or in_top_designation):
        return False

    # Single technical glyphs in stamp cells are valid (`Г`, `5`, `Л`).
    if len(compact) == 1:
        return compact in {"5", "Г", "г", "Л", "л"}
    if re.fullmatch(r"[А-Яа-яA-Za-z]{1,3}", compact):
        return False
    if re.search(r"\d", compact) and any(ch in compact for ch in ".-"):
        return True
    # Larger title/name fields are where source vector text most often turns
    # into point-like fragments on the physical plot.
    return len(compact) >= 4 and any(ch.isalpha() for ch in compact)


def _extract_kompas_stamp_title_text_lines_from_pdf(
    source_pdf: Path,
    *,
    page_index: int,
) -> list[dict[str, Any]]:
    if fitz is None or _drawing_frame_class(source_pdf) != "kompas_full_frame":
        return []
    doc = fitz.open(str(source_pdf))
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            return []
        page = doc[page_index]
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
        archive_cutoff_x = _kompas_archive_strip_mm(
            page_w_mm,
            specification_table=_is_kompas_specification_table_source(source_pdf),
        )
        lines: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int, int, int]] = set()
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = list(line.get("bbox", []) or [])
                if len(line_bbox) < 4:
                    continue
                spans = list(line.get("spans", []) or [])
                text = " ".join(
                    str(span.get("text", "") or "").strip()
                    for span in spans
                    if str(span.get("text", "") or "").strip()
                ).strip()
                text = re.sub(r"\s+", " ", text)
                if not text:
                    continue
                bbox_mm = tuple(float(v) * 25.4 / 72.0 for v in line_bbox[:4])
                line_dir_raw = line.get("dir")
                line_dir = None
                if isinstance(line_dir_raw, (list, tuple)) and len(line_dir_raw) >= 2:
                    line_dir = (float(line_dir_raw[0]), float(line_dir_raw[1]))
                if not _kompas_stamp_text_line_allowed(
                    text,
                    bbox_mm,  # type: ignore[arg-type]
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                    archive_cutoff_x_mm=float(archive_cutoff_x),
                    line_dir=line_dir,
                ):
                    continue
                key = (
                    text,
                    round(float(bbox_mm[0]) * 100),
                    round(float(bbox_mm[1]) * 100),
                    round(float(bbox_mm[2]) * 100),
                    round(float(bbox_mm[3]) * 100),
                )
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    {
                        "text": text,
                        "bbox_mm": tuple(float(v) for v in bbox_mm),
                        "font_names": [str(span.get("font", "") or "") for span in spans],
                    }
                )
        lines.sort(key=lambda row: (float(row["bbox_mm"][1]), float(row["bbox_mm"][0]), str(row["text"])))
        return lines
    finally:
        doc.close()


def _reroute_kompas_stamp_title_text_polylines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    source_pdf: Path,
    page_index: int,
    logger,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    text_lines = _extract_kompas_stamp_title_text_lines_from_pdf(source_pdf, page_index=page_index)
    if not text_lines:
        return list(polys_mm), _empty_kompas_stamp_text_meta()

    text_regions = [
        tuple(line.get("bbox_mm", ()) or ())
        for line in text_lines
        if len(tuple(line.get("bbox_mm", ()) or ())) >= 4
    ]
    text_regions = [(float(a), float(b), float(c), float(d)) for a, b, c, d in text_regions]
    if not text_regions:
        return list(polys_mm), _empty_kompas_stamp_text_meta()

    kept: list[list[tuple[float, float]]] = []
    removed = 0
    removed_bboxes_by_region: dict[int, list[tuple[float, float, float, float]]] = {}
    for poly in polys_mm:
        region_idx = _kompas_text_region_index_for_poly_mm(poly, text_regions=text_regions, pad_mm=0.90)
        if region_idx is not None:
            removed += 1
            removed_bboxes_by_region.setdefault(region_idx, []).append(_poly_bbox_mm(poly))
            continue
        kept.append(poly)

    render_lines: list[dict[str, Any]] = []
    for idx, line in enumerate(text_lines):
        visible_boxes = removed_bboxes_by_region.get(idx, [])
        if not visible_boxes:
            continue
        row = dict(line)
        vx0 = min(float(box[0]) for box in visible_boxes)
        vy0 = min(float(box[1]) for box in visible_boxes)
        vx1 = max(float(box[2]) for box in visible_boxes)
        vy1 = max(float(box[3]) for box in visible_boxes)
        if (vx1 - vx0) >= 0.35 and (vy1 - vy0) >= 0.35:
            # Use the actual visible vector bbox, not only PyMuPDF's logical
            # text bbox. This keeps baseline/height where KOMPAS really drew it.
            row["bbox_mm"] = (vx0, vy0, vx1, vy1)
        render_lines.append(row)

    rerendered: list[list[tuple[float, float]]] = []
    if render_lines:
        rerendered = _render_pdf_text_lines_polylines_in_place(
            render_lines,
            tight_layout=False,
            ttf_backend="skeleton",
            logger=logger,
        )
    if removed > 0 and not rerendered:
        logger(
            "KOMPAS stamp/title text repair skipped: renderer produced no replacement "
            "strokes; source vectors kept."
        )
        return list(polys_mm), {
            "kompas_stamp_text_lines": float(len(text_lines)),
            "kompas_stamp_text_removed": 0.0,
            "kompas_stamp_text_rendered": 0.0,
        }
    if rerendered:
        kept.extend(rerendered)
        logger(
            "KOMPAS stamp/title text repair: removed "
            f"{removed} outline polyline(s), rendered {len(rerendered)} single-line polyline(s) "
            f"from {len(text_lines)} PDF text line(s)."
        )
    return kept, {
        "kompas_stamp_text_lines": float(len(text_lines)),
        "kompas_stamp_text_removed": float(removed),
        "kompas_stamp_text_rendered": float(len(rerendered)),
    }


def _header_text_poly_candidate_mm(
    poly: list[tuple[float, float]],
    *,
    src_x0: float,
    src_y0: float,
    header_text_src_x0: float,
) -> bool:
    if not _is_a4_header_content_poly_mm(poly, src_x0=src_x0, src_y0=src_y0):
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    bw = float(x1 - x0)
    bh = float(y1 - y0)
    if (float(x1) - float(src_x0)) < (float(header_text_src_x0) + 1.5):
        return False
    if _poly_is_axis_aligned_mm(poly, eps=0.18) and min(bw, bh) <= 0.60:
        return False
    return True


def _render_a4_header_text_polylines(
    header_lines: list[dict[str, Any]],
    *,
    src_x0: float,
    src_y0: float,
    header_scale_y: float,
    header_text_src_x0: float,
    header_text_dst_x0: float,
    header_text_scale_x: float,
    tight_layout: bool,
    logger,
) -> list[list[tuple[float, float]]]:
    if not header_lines:
        return []
    resolve_ttf = getattr(backend, "_resolve_handwriting_ttf_path", lambda _font: None)
    if tight_layout:
        ttf_path = (
            resolve_ttf("GOST_BU.ttf")
            or resolve_ttf("GOST_AU.ttf")
            or resolve_ttf("GOST_B.TTF")
            or resolve_ttf("GOST_A.TTF")
            or resolve_ttf("ARIALNI.TTF")
            or resolve_ttf("ARIALN.TTF")
            or resolve_ttf("Arial")
        )
    else:
        ttf_path = (
            resolve_ttf("Arial")
            or resolve_ttf("Cambria")
            or resolve_ttf("Times New Roman")
            or resolve_ttf("Marck Script")
        )
    if ttf_path is None:
        return []
    fit_text = getattr(backend, "_fit_formula_ocr_font_size_units", None)
    render_line = getattr(backend, "_render_singleline_text_line_ttf", None)
    if fit_text is None or render_line is None:
        return []
    prev_ttf_backend = str(getattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "autotrace3"))

    out: list[list[tuple[float, float]]] = []
    try:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "skeleton")
        for line in header_lines:
            text = str(line.get("text", "")).strip()
            bbox_mm = tuple(line.get("bbox_mm", ()) or ())
            if not text or len(bbox_mm) < 4:
                continue
            box_x0, box_y0, box_x1, box_y1 = [float(v) for v in bbox_mm[:4]]
            target_x0 = float(header_text_dst_x0) + ((float(box_x0) - float(src_x0) - float(header_text_src_x0)) * float(header_text_scale_x))
            target_y0 = (float(box_y0) - float(src_y0)) * float(header_scale_y)
            target_x1 = float(header_text_dst_x0) + ((float(box_x1) - float(src_x0) - float(header_text_src_x0)) * float(header_text_scale_x))
            target_y1 = (float(box_y1) - float(src_y0)) * float(header_scale_y)
            target_w = max(1.0, float(target_x1 - target_x0))
            target_h = max(1.0, float(target_y1 - target_y0))
            fit = fit_text(
                text,
                ttf_path=ttf_path,
                target_w_u=target_w,
                target_h_u=target_h,
            )
            if fit is None:
                continue
            font_size_u, _bbox_u = fit
            line_polys = render_line(
                text,
                ttf_path=ttf_path,
                font_size=float(font_size_u),
                baseline_x=0.0,
                baseline_y=0.0,
                logger=logger,
            )
            line_polys = [[(float(x), float(y)) for x, y in poly] for poly in list(line_polys or []) if len(poly) >= 2]
            if not line_polys:
                continue
            ax0, ay0, ax1, ay1 = _polys_bbox_mm(line_polys)
            actual_w = max(1e-6, float(ax1 - ax0))
            actual_h = max(1e-6, float(ay1 - ay0))
            width_fill = 1.0 if tight_layout else 0.985
            height_fill = 1.0 if tight_layout else 0.94
            fit_scale = min((float(target_w) * width_fill) / actual_w, (float(target_h) * height_fill) / actual_h, 1.0)
            if abs(float(fit_scale) - 1.0) > 1e-6:
                line_polys = [
                    [((float(x) - float(ax0)) * float(fit_scale), (float(y) - float(ay0)) * float(fit_scale)) for x, y in poly]
                    for poly in line_polys
                ]
                ax0, ay0, ax1, ay1 = _polys_bbox_mm(line_polys)
                actual_w = max(1e-6, float(ax1 - ax0))
                actual_h = max(1e-6, float(ay1 - ay0))
            pad_x_ratio = 0.0 if tight_layout else 0.03
            pad_y_ratio = 0.0 if tight_layout else 0.06
            pad_x_u = max(0.0, (float(target_w) - actual_w) * pad_x_ratio)
            pad_y_u = max(0.0, (float(target_h) - actual_h) * pad_y_ratio)
            shift_x = float(target_x0) - float(ax0) + float(pad_x_u)
            shift_y = float(target_y0) - float(ay0) + float(pad_y_u)
            line_polys = [[(float(x) + float(shift_x), float(y) + float(shift_y)) for x, y in poly] for poly in line_polys]
            for poly in line_polys:
                if len(poly) >= 2:
                    out.append(poly)
        return out
    finally:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", prev_ttf_backend)


def _render_pdf_text_lines_polylines_in_place(
    text_lines: list[dict[str, Any]],
    *,
    tight_layout: bool,
    ttf_backend: str = "autotrace3",
    logger,
) -> list[list[tuple[float, float]]]:
    if not text_lines:
        return []
    resolve_ttf = getattr(backend, "_resolve_handwriting_ttf_path", lambda _font: None)
    if tight_layout:
        ttf_path = (
            resolve_ttf("GOST_BU.ttf")
            or resolve_ttf("GOST_AU.ttf")
            or resolve_ttf("GOST_B.TTF")
            or resolve_ttf("GOST_A.TTF")
            or resolve_ttf("ARIALNI.TTF")
            or resolve_ttf("ARIALN.TTF")
            or resolve_ttf("Arial")
        )
    else:
        ttf_path = (
            resolve_ttf("Arial")
            or resolve_ttf("Cambria")
            or resolve_ttf("Times New Roman")
            or resolve_ttf("Marck Script")
        )
    if ttf_path is None:
        return []
    fit_text = getattr(backend, "_fit_formula_ocr_font_size_units", None)
    render_line = getattr(backend, "_render_singleline_text_line_ttf", None)
    if fit_text is None or render_line is None:
        return []

    prev_ttf_backend = str(getattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "autotrace3"))
    out: list[list[tuple[float, float]]] = []
    try:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", str(ttf_backend))
        for line in text_lines:
            text = str(line.get("text", "")).strip()
            bbox_mm = tuple(line.get("bbox_mm", ()) or ())
            if not text or len(bbox_mm) < 4:
                continue
            box_x0, box_y0, box_x1, box_y1 = [float(v) for v in bbox_mm[:4]]
            target_w = max(1.0, float(box_x1 - box_x0))
            target_h = max(1.0, float(box_y1 - box_y0))
            fit = fit_text(
                text,
                ttf_path=ttf_path,
                target_w_u=target_w,
                target_h_u=target_h,
            )
            if fit is None:
                continue
            font_size_u, _bbox_u = fit
            line_polys = render_line(
                text,
                ttf_path=ttf_path,
                font_size=float(font_size_u),
                baseline_x=0.0,
                baseline_y=0.0,
                logger=logger,
            )
            line_polys = [[(float(x), float(y)) for x, y in poly] for poly in list(line_polys or []) if len(poly) >= 2]
            if not line_polys:
                continue
            ax0, ay0, ax1, ay1 = _polys_bbox_mm(line_polys)
            actual_w = max(1e-6, float(ax1 - ax0))
            actual_h = max(1e-6, float(ay1 - ay0))
            width_fill = 1.0 if tight_layout else 0.985
            height_fill = 1.0 if tight_layout else 0.94
            fit_scale = min((float(target_w) * width_fill) / actual_w, (float(target_h) * height_fill) / actual_h, 1.0)
            if abs(float(fit_scale) - 1.0) > 1e-6:
                line_polys = [
                    [((float(x) - float(ax0)) * float(fit_scale), (float(y) - float(ay0)) * float(fit_scale)) for x, y in poly]
                    for poly in line_polys
                ]
                ax0, ay0, ax1, ay1 = _polys_bbox_mm(line_polys)
                actual_w = max(1e-6, float(ax1 - ax0))
                actual_h = max(1e-6, float(ay1 - ay0))
            pad_x_u = 0.0 if tight_layout else max(0.0, (float(target_w) - actual_w) * 0.03)
            pad_y_u = 0.0 if tight_layout else max(0.0, (float(target_h) - actual_h) * 0.06)
            shift_x = float(box_x0) - float(ax0) + float(pad_x_u)
            shift_y = float(box_y0) - float(ay0) + float(pad_y_u)
            for poly in line_polys:
                if len(poly) >= 2:
                    out.append([(float(x) + float(shift_x), float(y) + float(shift_y)) for x, y in poly])
        return out
    finally:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", prev_ttf_backend)


def _parse_svg_matrix_transform(transform_text: str) -> tuple[float, float, float, float, float, float]:
    text = str(transform_text or "").strip()
    if not text.startswith("matrix(") or not text.endswith(")"):
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    try:
        values = [float(v.strip()) for v in text[7:-1].replace(",", " ").split()]
    except Exception:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if len(values) != 6:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    return (
        float(values[0]),
        float(values[1]),
        float(values[2]),
        float(values[3]),
        float(values[4]),
        float(values[5]),
    )


def _svg_title_block_region_from_pdf_lines(
    title_lines: list[dict[str, Any]],
) -> tuple[float, float, float, float] | None:
    line_boxes = [tuple(line.get("bbox_mm", ()) or ()) for line in title_lines if len(tuple(line.get("bbox_mm", ()) or ())) >= 4]
    if not line_boxes:
        return None
    return (
        min(float(b[0]) for b in line_boxes) - 1.0,
        min(float(b[1]) for b in line_boxes) - 1.0,
        max(float(b[2]) for b in line_boxes) + 1.0,
        max(float(b[3]) for b in line_boxes) + 1.0,
    )


def _remove_svg_text_nodes_in_region(
    svg_path: Path,
    *,
    region_mm: tuple[float, float, float, float],
    page_w_mm: float,
    page_h_mm: float,
) -> int:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    view_box = str(root.get("viewBox", "") or "").strip().replace(",", " ").split()
    if len(view_box) != 4:
        return 0
    try:
        vb_x = float(view_box[0])
        vb_y = float(view_box[1])
        vb_w = float(view_box[2])
        vb_h = float(view_box[3])
    except Exception:
        return 0
    sx = float(vb_w) / max(1e-9, float(page_w_mm))
    sy = float(vb_h) / max(1e-9, float(page_h_mm))
    rx0, ry0, rx1, ry1 = [float(v) for v in region_mm]

    def _anchor_mm(node: ET.Element) -> tuple[float, float] | None:
        tspans = [child for child in list(node) if str(child.tag).split("}")[-1].lower() == "tspan"]
        if tspans:
            anchor_node = tspans[0]
            x_text = anchor_node.attrib.get("x", node.attrib.get("x", ""))
            y_text = anchor_node.attrib.get("y", node.attrib.get("y", ""))
        else:
            x_text = node.attrib.get("x", "")
            y_text = node.attrib.get("y", "")
        try:
            x_u = float(str(x_text).replace(",", " ").split()[0])
            y_u = float(str(y_text).replace(",", " ").split()[0])
        except Exception:
            return None
        a, b, c, d, e, f = _parse_svg_matrix_transform(node.attrib.get("transform", ""))
        tx = (a * x_u) + (c * y_u) + e
        ty = (b * x_u) + (d * y_u) + f
        x_mm = (float(tx) - float(vb_x)) / float(sx)
        y_mm = (float(ty) - float(vb_y)) / float(sy)
        return float(x_mm), float(y_mm)

    removed = 0
    for parent in list(root.iter()):
        for child in list(parent):
            if str(child.tag).split("}")[-1].lower() != "text":
                continue
            anchor = _anchor_mm(child)
            if anchor is None:
                continue
            x_mm, y_mm = anchor
            if float(rx0) <= float(x_mm) <= float(rx1) and float(ry0) <= float(y_mm) <= float(ry1):
                parent.remove(child)
                removed += 1

    if removed > 0:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    return int(removed)


def _title_block_text_poly_candidate_mm(
    poly: list[tuple[float, float]],
    *,
    region_x0: float,
    region_y0: float,
    region_x1: float,
    region_y1: float,
) -> bool:
    if len(poly) < 2:
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    if float(x0) < float(region_x0) or float(y0) < float(region_y0):
        return False
    if float(x1) > float(region_x1) or float(y1) > float(region_y1):
        return False
    bw = float(x1 - x0)
    bh = float(y1 - y0)
    if _poly_is_axis_aligned_mm(poly, eps=0.18) and min(bw, bh) <= 0.70 and max(bw, bh) >= 4.0:
        return False
    return True


def _kompas_text_poly_candidate_mm(
    poly: list[tuple[float, float]],
    *,
    text_regions: list[tuple[float, float, float, float]],
    pad_mm: float = 0.45,
) -> bool:
    if len(poly) < 2 or not text_regions:
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    bw = float(x1) - float(x0)
    bh = float(y1) - float(y0)
    # Preserve table/frame/dimension vectors. Text glyph outlines can contain
    # short straight strokes, but real technical lines are longer axis-aligned
    # segments and must not be removed.
    if _poly_is_axis_aligned_mm(poly, eps=0.18) and min(bw, bh) <= 0.70 and max(bw, bh) >= 4.0:
        return False
    for rx0, ry0, rx1, ry1 in text_regions:
        region_h = max(0.0, float(ry1) - float(ry0))
        pad_x = max(float(pad_mm), min(2.5, region_h * 0.25))
        pad_y = max(float(pad_mm), min(5.0, region_h * 0.50))
        if (
            float(x0) >= float(rx0) - pad_x
            and float(y0) >= float(ry0) - pad_y
            and float(x1) <= float(rx1) + pad_x
            and float(y1) <= float(ry1) + pad_y
        ):
            return True
    return False


def _kompas_text_region_index_for_poly_mm(
    poly: list[tuple[float, float]],
    *,
    text_regions: list[tuple[float, float, float, float]],
    pad_mm: float = 0.45,
) -> int | None:
    if not _kompas_text_poly_candidate_mm(poly, text_regions=text_regions, pad_mm=pad_mm):
        return None
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    cx = (float(x0) + float(x1)) * 0.5
    cy = (float(y0) + float(y1)) * 0.5
    best_idx: int | None = None
    best_dist = float("inf")
    for idx, (rx0, ry0, rx1, ry1) in enumerate(text_regions):
        region_h = max(0.0, float(ry1) - float(ry0))
        pad_x = max(float(pad_mm), min(2.5, region_h * 0.25))
        pad_y = max(float(pad_mm), min(5.0, region_h * 0.50))
        if not (
            float(x0) >= float(rx0) - pad_x
            and float(y0) >= float(ry0) - pad_y
            and float(x1) <= float(rx1) + pad_x
            and float(y1) <= float(ry1) + pad_y
        ):
            continue
        rcx = (float(rx0) + float(rx1)) * 0.5
        rcy = (float(ry0) + float(ry1)) * 0.5
        dist = (cx - rcx) ** 2 + (cy - rcy) ** 2
        if dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx


def _reroute_kompas_text_polylines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    source_pdf: Path,
    page_index: int,
    logger,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    text_lines = _extract_kompas_plot_text_lines_from_pdf(source_pdf, page_index=page_index)
    if not text_lines:
        return list(polys_mm), {
            "kompas_text_lines": 0.0,
            "kompas_text_removed": 0.0,
            "kompas_text_rendered": 0.0,
        }
    text_regions = [
        tuple(line.get("bbox_mm", ()) or ())
        for line in text_lines
        if len(tuple(line.get("bbox_mm", ()) or ())) >= 4
    ]
    text_regions = [(float(a), float(b), float(c), float(d)) for a, b, c, d in text_regions]
    if not text_regions:
        return list(polys_mm), {
            "kompas_text_lines": 0.0,
            "kompas_text_removed": 0.0,
            "kompas_text_rendered": 0.0,
        }

    kept: list[list[tuple[float, float]]] = []
    removed = 0
    removed_bboxes_by_region: dict[int, list[tuple[float, float, float, float]]] = {}
    for poly in polys_mm:
        region_idx = _kompas_text_region_index_for_poly_mm(poly, text_regions=text_regions)
        if region_idx is not None:
            removed += 1
            removed_bboxes_by_region.setdefault(region_idx, []).append(_poly_bbox_mm(poly))
            continue
        kept.append(poly)

    render_lines: list[dict[str, Any]] = []
    for idx, line in enumerate(text_lines):
        row = dict(line)
        visible_boxes = removed_bboxes_by_region.get(idx, [])
        if not visible_boxes:
            # Do not draw replacement text unless the old KOMPAS glyph vectors
            # were actually removed. Otherwise the preview/G-code contains
            # unreadable double text: original outlines plus our single-line
            # replacement.
            continue
        vx0 = min(float(box[0]) for box in visible_boxes)
        vy0 = min(float(box[1]) for box in visible_boxes)
        vx1 = max(float(box[2]) for box in visible_boxes)
        vy1 = max(float(box[3]) for box in visible_boxes)
        if (vx1 - vx0) >= 0.35 and (vy1 - vy0) >= 0.35:
            row["bbox_mm"] = (vx0, vy0, vx1, vy1)
        render_lines.append(row)

    rerendered = []
    if render_lines:
        rerendered = _render_pdf_text_lines_polylines_in_place(
            render_lines,
            tight_layout=True,
            ttf_backend="skeleton",
            logger=logger,
        )
    if removed > 0 and not rerendered:
        logger("KOMPAS text reroute skipped: renderer produced no replacement strokes; source vectors kept.")
        return list(polys_mm), {
            "kompas_text_lines": float(len(text_lines)),
            "kompas_text_removed": 0.0,
            "kompas_text_rendered": 0.0,
        }
    if rerendered:
        kept.extend(rerendered)
        logger(
            "KOMPAS text reroute: removed "
            f"{removed} outline polyline(s), rendered {len(rerendered)} single-line polyline(s) "
            f"from {len(text_lines)} PDF text line(s)."
        )
    return kept, {
        "kompas_text_lines": float(len(text_lines)),
        "kompas_text_removed": float(removed),
        "kompas_text_rendered": float(len(rerendered)),
    }


def _reroute_title_block_text_polylines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    source_pdf: Path,
    page_index: int,
    ttf_backend: str = "skeleton",
    tight_layout: bool = False,
    logger,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    title_lines = _extract_title_block_text_lines_from_pdf(source_pdf, page_index=page_index)
    if not title_lines:
        return list(polys_mm), {"title_block_text_lines": 0.0, "title_block_text_removed": 0.0, "title_block_text_rendered": 0.0}
    line_boxes = [tuple(line.get("bbox_mm", ()) or ()) for line in title_lines if len(tuple(line.get("bbox_mm", ()) or ())) >= 4]
    if not line_boxes:
        return list(polys_mm), {"title_block_text_lines": 0.0, "title_block_text_removed": 0.0, "title_block_text_rendered": 0.0}
    region_x0 = min(float(b[0]) for b in line_boxes) - 1.0
    region_y0 = min(float(b[1]) for b in line_boxes) - 1.0
    region_x1 = max(float(b[2]) for b in line_boxes) + 1.0
    region_y1 = max(float(b[3]) for b in line_boxes) + 1.0

    kept: list[list[tuple[float, float]]] = []
    removed = 0
    for poly in polys_mm:
        if _title_block_text_poly_candidate_mm(
            poly,
            region_x0=float(region_x0),
            region_y0=float(region_y0),
            region_x1=float(region_x1),
            region_y1=float(region_y1),
        ):
            removed += 1
            continue
        kept.append(poly)

    rerendered = _render_pdf_text_lines_polylines_in_place(
        title_lines,
        tight_layout=bool(tight_layout),
        ttf_backend=str(ttf_backend),
        logger=logger,
    )
    if removed > 0 and not rerendered:
        logger("Title block text reroute skipped: renderer produced no replacement strokes; source vectors kept.")
        return list(polys_mm), {
            "title_block_text_lines": float(len(title_lines)),
            "title_block_text_removed": 0.0,
            "title_block_text_rendered": 0.0,
        }
    if rerendered:
        kept.extend(rerendered)
        logger(
            "Title block text reroute: removed "
            f"{removed} source polyline(s), rendered {len(rerendered)} polyline(s) from {len(title_lines)} PDF text line(s)."
        )
    return kept, {
        "title_block_text_lines": float(len(title_lines)),
        "title_block_text_removed": float(removed),
        "title_block_text_rendered": float(len(rerendered)),
    }


def _transform_a4_header_text_source_polylines(
    header_text_source_polys: list[list[tuple[float, float]]],
    *,
    src_x0: float,
    src_y0: float,
    header_scale_y: float,
    header_text_src_x0: float,
    header_text_dst_x0: float,
    header_text_scale_x: float,
    target_w_mm: float,
    target_h_mm: float,
) -> list[list[tuple[float, float]]]:
    out: list[list[tuple[float, float]]] = []
    if not header_text_source_polys:
        return out
    group_x0, group_y0, group_x1, group_y1 = _polys_bbox_mm(header_text_source_polys)
    group_w = max(1e-6, float(group_x1 - group_x0))
    available_w = max(8.0, float(target_w_mm) - float(header_text_dst_x0) - 4.0)
    group_scale_x = min(float(header_text_scale_x), float(available_w) / float(group_w))
    target_group_x0 = float(header_text_dst_x0) + 2.0
    target_group_y0 = (float(group_y0) - float(src_y0)) * float(header_scale_y)
    for poly in header_text_source_polys:
        if len(poly) < 2:
            continue
        mapped: list[tuple[float, float]] = []
        for x, y in poly:
            nx = float(target_group_x0) + ((float(x) - float(group_x0)) * float(group_scale_x))
            ny = float(target_group_y0) + ((float(y) - float(group_y0)) * float(header_scale_y))
            nx = max(0.0, min(float(target_w_mm), nx))
            ny = max(0.0, min(float(target_h_mm), ny))
            mapped.append((nx, ny))
        if len(mapped) >= 2:
            _mx0, _my0, _mx1, _my1 = _poly_bbox_mm(mapped)
            out.append(mapped)
    return out


def _analyze_gcode(nc_path: Path) -> dict[str, Any]:
    lines = nc_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    polylines = _gcode_to_polylines(lines, z_up=float(backend.Z_UP), z_down=float(backend.Z_DOWN))
    total_segments = 0
    total_draw_len = 0.0
    pen_down_strokes = 0
    short_segments_lt_035_mm = 0
    micro_segments_lt_015_mm = 0
    tiny_strokes_lt_08_mm = 0
    point_like_strokes = 0
    avg_stroke_length_mm = 0.0
    xs: list[float] = []
    ys: list[float] = []
    seen: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    for poly in polylines:
        if len(poly) < 2:
            continue
        pen_down_strokes += 1
        stroke_len = _polyline_length(poly)
        total_draw_len += stroke_len
        avg_stroke_length_mm += stroke_len
        if stroke_len < 0.8:
            tiny_strokes_lt_08_mm += 1
        px = [float(pt[0]) for pt in poly]
        py = [float(pt[1]) for pt in poly]
        span_x = max(px) - min(px)
        span_y = max(py) - min(py)
        if stroke_len < 0.35 or (span_x <= 0.30 and span_y <= 0.30 and stroke_len <= 0.80):
            point_like_strokes += 1
        for idx in range(1, len(poly)):
            a = poly[idx - 1]
            b = poly[idx]
            total_segments += 1
            seen[_segment_key(a, b)] = seen.get(_segment_key(a, b), 0) + 1
            seg_len = math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
            if seg_len < 0.35:
                short_segments_lt_035_mm += 1
            if seg_len < 0.15:
                micro_segments_lt_015_mm += 1
            xs.extend([float(a[0]), float(b[0])])
            ys.extend([float(a[1]), float(b[1])])
    duplicate_segments = sum(max(0, cnt - 1) for cnt in seen.values())
    if pen_down_strokes:
        avg_stroke_length_mm /= float(pen_down_strokes)
    return {
        "draw_length_mm": round(total_draw_len, 3),
        "segments_total": int(total_segments),
        "segments_duplicate": int(duplicate_segments),
        "pen_down_strokes": int(pen_down_strokes),
        "short_segments_lt_035_mm": int(short_segments_lt_035_mm),
        "micro_segments_lt_015_mm": int(micro_segments_lt_015_mm),
        "tiny_strokes_lt_08_mm": int(tiny_strokes_lt_08_mm),
        "point_like_strokes": int(point_like_strokes),
        "avg_stroke_length_mm": round(avg_stroke_length_mm, 3),
        "bounds": {
            "x_min": min(xs) if xs else 0.0,
            "x_max": max(xs) if xs else 0.0,
            "y_min": min(ys) if ys else 0.0,
            "y_max": max(ys) if ys else 0.0,
        },
    }


def _bounds_text(metrics: dict[str, Any]) -> str:
    b = dict(metrics.get("bounds", {}))
    return (
        f"{float(b.get('x_min', 0.0)):.3f}..{float(b.get('x_max', 0.0)):.3f} x, "
        f"{float(b.get('y_min', 0.0)):.3f}..{float(b.get('y_max', 0.0)):.3f} y"
    )


def _aggregate_row_fragmentation(rows: list[ArtifactRow]) -> tuple[dict[str, Any], float]:
    ok_rows = [row for row in rows if row.ok]
    metrics = {
        "segments_total": sum(int(row.segments_total or 0) for row in ok_rows),
        "pen_down_strokes": sum(int(row.pen_down_strokes or 0) for row in ok_rows),
        "tiny_strokes_lt_08_mm": sum(int(row.tiny_strokes_lt_08_mm or 0) for row in ok_rows),
        "point_like_strokes": sum(int(row.point_like_strokes or 0) for row in ok_rows),
    }
    return metrics, _candidate_fragmentation_score(metrics)


def _parse_fit_scale(logs: list[str]) -> float | None:
    rx = re.compile(r"Fit to work area: scale=([0-9.]+)")
    for line in logs:
        match = rx.search(line)
        if match:
            return round(float(match.group(1)), 6)
    return None


def _has_clipping_warning(logs: list[str]) -> bool:
    markers = [
        "Warning: significant clipping/transforming occurred.",
        "Two-pass 1:1 is impossible",
        "dropped out-of-area segments",
    ]
    joined = "\n".join(logs)
    return any(marker in joined for marker in markers)


def _bridge_preview_copy_targets(prefix: Path) -> tuple[Path, Path, Path, Path]:
    return (
        prefix.with_suffix(".svg"),
        prefix.with_suffix(".pdf"),
        prefix.with_suffix(".nc"),
        prefix.with_suffix(".gcode"),
    )


def _preview_artifact_sources(*, op_id: str | None = None) -> tuple[Path, Path, Path]:
    tmp = PROJECT_ROOT / "_tmp"
    if op_id:
        token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(op_id or "").strip()).strip("._")
        if token:
            if len(token) > 80:
                token = token[:80]
            stem = f"latest_preview_{token}"
            unique_svg = tmp / f"{stem}_vector.svg"
            unique_pdf = tmp / f"{stem}_vector.pdf"
            unique_nc = tmp / f"{stem}.nc"
            if unique_svg.exists() and unique_pdf.exists() and unique_nc.exists():
                return unique_svg, unique_pdf, unique_nc
    return (
        tmp / "latest_preview_vector.svg",
        tmp / "latest_preview_vector.pdf",
        tmp / "latest_preview.nc",
    )


def _copy_latest_preview_artifacts(prefix: Path, *, op_id: str | None = None) -> tuple[Path, Path, Path, Path]:
    src_svg, src_pdf, src_nc = _preview_artifact_sources(op_id=op_id)
    dst_svg, dst_pdf, dst_nc, dst_gcode = _bridge_preview_copy_targets(prefix)
    _copy_file(src_svg, dst_svg)
    _copy_file(src_pdf, dst_pdf)
    _copy_nc_and_gcode(src_nc, dst_nc, dst_gcode)
    return dst_svg, dst_pdf, dst_nc, dst_gcode


def _pdf_first_page_size_mm(pdf_path: Path) -> tuple[float, float]:
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        return (
            float(page.rect.width) * 25.4 / 72.0,
            float(page.rect.height) * 25.4 / 72.0,
        )
    finally:
        doc.close()


def _parse_a3_pass_log(log_path: Path) -> dict[str, float | int]:
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    fit_match = _A3_FIT_RE.search(text)
    pass_match = _A3_PASS_RE.search(text)
    if pass_match is None:
        raise ValueError(f"Cannot parse A3 pass transform from log: {log_path}")
    if fit_match is None:
        if "Fit guard (1:1 mm)" in text or "keeping scale=1.0" in text:
            fit_scale = 1.0
            fit_tx = 0.0
            fit_ty = 0.0
        else:
            raise ValueError(f"Cannot parse A3 pass transform from log: {log_path}")
    else:
        fit_scale = float(fit_match.group(1))
        fit_tx = float(fit_match.group(2))
        fit_ty = float(fit_match.group(3))
    area_match = _A3_AREA_RE.search(text)
    if area_match is not None:
        area_min_x, area_max_x, area_min_y, area_max_y = [float(area_match.group(i)) for i in range(1, 5)]
    else:
        area_min_x, area_max_x, area_min_y, area_max_y = backend.work_area_bounds()
    translate_match = _A3_POST_TRANSLATE_RE.search(text)
    post_tx = float(translate_match.group(1)) if translate_match is not None else 0.0
    post_ty = float(translate_match.group(2)) if translate_match is not None else 0.0
    return {
        "scale": float(fit_scale),
        "fit_tx": float(fit_tx),
        "fit_ty": float(fit_ty),
        "shift_x": float(pass_match.group(1)),
        "shift_y": float(pass_match.group(2)),
        "rotation_deg": 180 if "rotating geometry by 180 deg" in text else 0,
        "post_tx": post_tx,
        "post_ty": post_ty,
        "area_min_x": float(area_min_x),
        "area_max_x": float(area_max_x),
        "area_min_y": float(area_min_y),
        "area_max_y": float(area_max_y),
    }


def _inverse_a3_pass_polylines_to_sheet(
    *,
    nc_path: Path,
    log_path: Path,
    keep_fitted_coords: bool = False,
) -> list[list[tuple[float, float]]]:
    info = _parse_a3_pass_log(log_path)
    scale = float(info["scale"])
    tx = float(info["fit_tx"]) + float(info["shift_x"])
    ty = float(info["fit_ty"]) + float(info["shift_y"])
    rotation_deg = int(info["rotation_deg"])
    post_tx = float(info["post_tx"])
    post_ty = float(info["post_ty"])
    center_x = 0.5 * (float(info["area_min_x"]) + float(info["area_max_x"]))
    center_y = 0.5 * (float(info["area_min_y"]) + float(info["area_max_y"]))

    polylines = _gcode_to_polylines(
        nc_path.read_text(encoding="utf-8", errors="ignore").splitlines(),
        z_up=float(backend.Z_UP),
        z_down=float(backend.Z_DOWN),
    )
    out: list[list[tuple[float, float]]] = []
    for poly in polylines:
        recon: list[tuple[float, float]] = []
        for x, y in poly:
            px = float(x) - post_tx
            py = float(y) - post_ty
            if rotation_deg == 180:
                px = (2.0 * center_x) - px
                py = (2.0 * center_y) - py
            if keep_fitted_coords:
                recon.append((px, py))
            else:
                recon.append(((px - tx) / scale, (py - ty) / scale))
        if len(recon) >= 2:
            out.append(recon)
    return out


def _render_polylines_pdf(
    *,
    polylines: list[list[tuple[float, float]]],
    out_pdf: Path,
    canvas_bounds_mm: tuple[float, float, float, float],
) -> None:
    x0, x1, y0, y1 = [float(value) for value in canvas_bounds_mm]
    width_mm = max(1.0, x1 - x0)
    height_mm = max(1.0, y1 - y0)
    mm_to_pt = 72.0 / 25.4
    doc = fitz.open()
    try:
        page = doc.new_page(width=width_mm * mm_to_pt, height=height_mm * mm_to_pt)
        shape = page.new_shape()
        for poly in polylines:
            if len(poly) < 2:
                continue
            prev = None
            for x_mm, y_mm in poly:
                px = (float(x_mm) - x0) * mm_to_pt
                py = (float(y_mm) - y0) * mm_to_pt
                point = fitz.Point(px, py)
                if prev is not None:
                    shape.draw_line(prev, point)
                prev = point
        shape.finish(color=(0.0, 0.0, 0.0), width=0.45)
        shape.commit()
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out_pdf)
    finally:
        doc.close()


def _center_polylines_on_page(
    polylines: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    if not polylines:
        return [], {"offset_x_mm": 0.0, "offset_y_mm": 0.0}
    x0, y0, x1, y1 = _polys_bbox_mm(polylines)
    width = max(1e-9, float(x1 - x0))
    height = max(1e-9, float(y1 - y0))
    offset_x = (float(page_w_mm) - float(width)) * 0.5 - float(x0)
    offset_y = (float(page_h_mm) - float(height)) * 0.5 - float(y0)
    shifted: list[list[tuple[float, float]]] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        shifted.append([(float(x) + float(offset_x), float(y) + float(offset_y)) for x, y in poly])
    return shifted, {
        "offset_x_mm": float(offset_x),
        "offset_y_mm": float(offset_y),
        "bounds_x0": float(x0),
        "bounds_y0": float(y0),
        "bounds_x1": float(x1),
        "bounds_y1": float(y1),
    }


def _center_polylines_on_page_x(
    polylines: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    if not polylines:
        return [], {"offset_x_mm": 0.0}
    x0, _y0, x1, _y1 = _polys_bbox_mm(polylines)
    width = max(1e-9, float(x1 - x0))
    offset_x = (float(page_w_mm) - float(width)) * 0.5 - float(x0)
    shifted: list[list[tuple[float, float]]] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        shifted.append([(float(x) + float(offset_x), float(y)) for x, y in poly])
    return shifted, {
        "offset_x_mm": float(offset_x),
        "bounds_x0": float(x0),
        "bounds_x1": float(x1),
    }


def _translate_polylines_mm(
    polylines: list[list[tuple[float, float]]],
    *,
    offset_x_mm: float,
    offset_y_mm: float,
) -> list[list[tuple[float, float]]]:
    shifted: list[list[tuple[float, float]]] = []
    dx = float(offset_x_mm)
    dy = float(offset_y_mm)
    for poly in polylines:
        if len(poly) < 2:
            continue
        shifted.append([(float(x) + dx, float(y) + dy) for x, y in poly])
    return shifted


def _maybe_reanchor_a3_clean_source_polylines(
    polylines: list[list[tuple[float, float]]],
    *,
    ref_bbox_mm: tuple[float, float, float, float] | None,
    logger=None,
) -> tuple[list[list[tuple[float, float]]], bool]:
    if not polylines or ref_bbox_mm is None:
        return polylines, False
    src_x0, src_y0, src_x1, src_y1 = _polys_bbox_mm(polylines)
    src_w = max(1e-9, float(src_x1 - src_x0))
    src_h = max(1e-9, float(src_y1 - src_y0))
    ref_x0, ref_y0, ref_x1, ref_y1 = [float(v) for v in ref_bbox_mm]
    ref_w = max(1e-9, float(ref_x1 - ref_x0))
    if not (
        float(src_x0) <= 2.0
        and float(src_y0) <= 2.0
        and float(src_w) <= 360.5
        and float(src_h) <= 280.5
        and (float(ref_w) - float(src_w)) >= 35.0
    ):
        return polylines, False
    target_x0 = float(ref_x0) + max(0.0, (float(ref_w) - float(src_w)) * 0.5)
    target_y0 = float(ref_y0)
    shift_x = float(target_x0) - float(src_x0)
    shift_y = float(target_y0) - float(src_y0)
    if abs(float(shift_x)) < 0.05 and abs(float(shift_y)) < 0.05:
        return polylines, False
    shifted = _translate_polylines_mm(
        polylines,
        offset_x_mm=float(shift_x),
        offset_y_mm=float(shift_y),
    )
    if logger is not None:
        logger(
            "A3 clean source re-anchored to original source bbox: "
            f"shift=({float(shift_x):.3f},{float(shift_y):.3f}) mm, "
            f"ref_bbox=({float(ref_x0):.3f},{float(ref_y0):.3f})..({float(ref_x1):.3f},{float(ref_y1):.3f}) mm"
        )
    return shifted, True


def _pdf_visible_bbox_mm(pdf_path: Path, *, threshold: int = 245, zoom: float = 4.0) -> tuple[float, float, float, float] | None:
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(float(zoom), float(zoom)), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        xs: list[int] = []
        ys: list[int] = []
        width_px, height_px = img.size
        for y_px in range(height_px):
            for x_px in range(width_px):
                if int(img.getpixel((x_px, y_px))) < int(threshold):
                    xs.append(int(x_px))
                    ys.append(int(y_px))
        if not xs or not ys:
            return None
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
        mm_per_px_x = float(page_w_mm) / float(width_px)
        mm_per_px_y = float(page_h_mm) / float(height_px)
        return (
            float(min(xs)) * float(mm_per_px_x),
            float(min(ys)) * float(mm_per_px_y),
            float(max(xs)) * float(mm_per_px_x),
            float(max(ys)) * float(mm_per_px_y),
        )
    finally:
        doc.close()


def _build_sheet_preview_from_gcode(
    *,
    gcode_path: Path,
    reference_pdf: Path,
    out_svg: Path,
    out_pdf: Path,
    logs: list[str],
) -> tuple[bool, str]:
    try:
        lines = gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        return False, f"Failed to read G-code for sheet preview: {exc}"

    z_values: list[float] = []
    for line in lines:
        match = re.search(r"(?:^|\s)Z(-?\d+(?:\.\d+)?)", str(line))
        if match:
            try:
                z_values.append(float(match.group(1)))
            except Exception:
                pass
    if not z_values:
        return False, "No Z values found while building sheet preview."

    z_up = float(min(z_values))
    z_down = float(max(z_values))
    try:
        polylines = _gcode_to_polylines(lines, z_up=z_up, z_down=z_down)
    except Exception as exc:
        return False, f"Failed to convert G-code to polylines for sheet preview: {exc}"
    if not polylines:
        return False, "No drawing polylines recovered from G-code for sheet preview."

    page_w_mm, page_h_mm = _pdf_first_page_size_mm(reference_pdf)
    ref_bbox = _pdf_visible_bbox_mm(reference_pdf)
    if ref_bbox is None:
        shifted, meta = _center_polylines_on_page(polylines, page_w_mm=float(page_w_mm), page_h_mm=float(page_h_mm))
        logs.append(
            "Sheet preview fallback: centered on source page because visible reference bbox was not detected."
        )
    else:
        src_x0, src_y0, src_x1, src_y1 = _polys_bbox_mm(polylines)
        width_mm = max(1e-9, float(src_x1 - src_x0))
        height_mm = max(1e-9, float(src_y1 - src_y0))
        ref_x0, ref_y0, _ref_x1, _ref_y1 = [float(v) for v in ref_bbox]
        left_margin_mm = max(0.0, float(ref_x0))
        right_margin_mm = max(0.0, float(page_w_mm) - float(_ref_x1))
        top_margin_mm = max(0.0, float(ref_y0))
        bottom_margin_mm = max(0.0, float(page_h_mm) - float(_ref_y1))
        compact_reference_bbox = (
            left_margin_mm <= 2.0
            and right_margin_mm <= 2.0
            and top_margin_mm <= 2.0
            and bottom_margin_mm <= 2.0
        )
        if compact_reference_bbox:
            target_x0 = max(0.0, (float(page_w_mm) - float(width_mm)) * 0.5)
            target_x0 = min(float(target_x0), max(0.0, float(page_w_mm) - float(width_mm)))
            target_y0 = max(0.0, (float(page_h_mm) - float(height_mm)) * 0.5)
            target_y0 = min(float(target_y0), max(0.0, float(page_h_mm) - float(height_mm)))
        elif left_margin_mm <= 2.0 and right_margin_mm <= 2.0:
            target_x0 = min(max(0.0, float(ref_x0)), max(0.0, float(page_w_mm) - float(width_mm)))
            target_y0 = min(max(0.0, float(ref_y0)), max(0.0, float(page_h_mm) - float(height_mm)))
        else:
            target_x0 = max(0.0, (float(page_w_mm) - float(width_mm)) * 0.5)
            target_x0 = min(float(target_x0), max(0.0, float(page_w_mm) - float(width_mm)))
            target_y0 = min(max(0.0, float(ref_y0)), max(0.0, float(page_h_mm) - float(height_mm)))
        offset_x = float(target_x0) - float(src_x0)
        offset_y = float(target_y0) - float(src_y0)
        shifted = [
            [(float(x) + float(offset_x), float(y) + float(offset_y)) for x, y in poly]
            for poly in polylines
            if len(poly) >= 2
        ]
        meta = {
            "offset_x_mm": float(offset_x),
            "offset_y_mm": float(offset_y),
            "reference_x0_mm": float(ref_x0),
            "reference_y0_mm": float(ref_y0),
            "reference_x1_mm": float(_ref_x1),
            "reference_y1_mm": float(_ref_y1),
            "compact_reference_bbox": bool(compact_reference_bbox),
        }
        if compact_reference_bbox:
            logs.append(
                "Sheet preview centered on compact source page bbox: "
                f"ref=({float(ref_x0):.3f},{float(ref_y0):.3f})..({float(_ref_x1):.3f},{float(_ref_y1):.3f}) mm"
            )
        elif left_margin_mm <= 2.0 and right_margin_mm <= 2.0:
            logs.append(
                "Sheet preview aligned to reference bbox X/Y: "
                f"ref=({float(ref_x0):.3f},{float(ref_y0):.3f})..({float(_ref_x1):.3f},{float(_ref_y1):.3f}) mm"
            )
        else:
            logs.append(
                "Sheet preview aligned to reference bbox Y and centered on page X: "
                f"ref=({float(ref_x0):.3f},{float(ref_y0):.3f})..({float(_ref_x1):.3f},{float(_ref_y1):.3f}) mm"
            )
    _write_svg_preview(shifted, out_svg, canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)))
    _render_polylines_pdf(polylines=shifted, out_pdf=out_pdf, canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)))
    logs.append(
        "Sheet preview placed on source page: "
        f"offset=({float(meta.get('offset_x_mm', 0.0)):.3f},{float(meta.get('offset_y_mm', 0.0)):.3f}) mm"
    )
    return True, ""


def _build_fixed_canvas_preview_from_gcode(
    *,
    gcode_path: Path,
    out_svg: Path,
    out_pdf: Path,
    page_w_mm: float,
    page_h_mm: float,
    logs: list[str],
) -> tuple[bool, str]:
    try:
        lines = gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        return False, f"Failed to read G-code for fixed-canvas preview: {exc}"

    z_values: list[float] = []
    for line in lines:
        match = re.search(r"(?:^|\s)Z(-?\d+(?:\.\d+)?)", str(line))
        if match:
            try:
                z_values.append(float(match.group(1)))
            except Exception:
                pass
    if not z_values:
        return False, "No Z values found while building fixed-canvas preview."

    try:
        polylines = _gcode_to_polylines(lines, z_up=float(min(z_values)), z_down=float(max(z_values)))
    except Exception as exc:
        return False, f"Failed to convert G-code to polylines for fixed-canvas preview: {exc}"
    if not polylines:
        return False, "No drawing polylines recovered from G-code for fixed-canvas preview."

    shifted, meta = _center_polylines_on_page(
        polylines,
        page_w_mm=float(page_w_mm),
        page_h_mm=float(page_h_mm),
    )
    _write_svg_preview(shifted, out_svg, canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)))
    _render_polylines_pdf(polylines=shifted, out_pdf=out_pdf, canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)))
    logs.append(
        "Fixed-canvas preview centered on page: "
        f"page={float(page_w_mm):.3f}x{float(page_h_mm):.3f} mm, "
        f"offset=({float(meta.get('offset_x_mm', 0.0)):.3f},{float(meta.get('offset_y_mm', 0.0)):.3f}) mm"
    )
    return True, ""


def _machine_work_area_size_mm() -> tuple[float, float]:
    area_min_x, area_max_x, area_min_y, area_max_y = backend.base_work_area_bounds()
    return (
        max(1.0, float(area_max_x) - float(area_min_x)),
        max(1.0, float(area_max_y) - float(area_min_y)),
    )


def _machine_work_area_bounds_mm() -> tuple[float, float, float, float]:
    area_min_x, area_max_x, area_min_y, area_max_y = backend.base_work_area_bounds()
    return (
        float(min(area_min_x, area_max_x)),
        float(max(area_min_x, area_max_x)),
        float(min(area_min_y, area_max_y)),
        float(max(area_min_y, area_max_y)),
    )


def _work_area_frame_polyline(bounds_mm: tuple[float, float, float, float] | None = None) -> list[tuple[float, float]]:
    min_x, max_x, min_y, max_y = bounds_mm if bounds_mm is not None else _machine_work_area_bounds_mm()
    return [
        (float(min_x), float(max_y)),
        (float(max_x), float(max_y)),
        (float(max_x), float(min_y)),
        (float(min_x), float(min_y)),
        (float(min_x), float(max_y)),
    ]


def _rewrite_preview_on_work_area_canvas_from_gcode(
    *,
    gcode_path: Path,
    out_svg: Path,
    out_pdf: Path,
    logs: list[str],
) -> tuple[bool, str]:
    work_w_mm, work_h_mm = _machine_work_area_size_mm()
    ok, err = _build_fixed_canvas_preview_from_gcode(
        gcode_path=gcode_path,
        out_svg=out_svg,
        out_pdf=out_pdf,
        page_w_mm=float(work_w_mm),
        page_h_mm=float(work_h_mm),
        logs=logs,
    )
    if ok:
        logs.append(
            "Preview canvas switched to machine work area: "
            f"{float(work_w_mm):.3f}x{float(work_h_mm):.3f} mm."
        )
    return ok, err


def _is_outer_bbox_frame_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    bbox_mm: tuple[float, float, float, float],
    edge_eps_mm: float = 0.80,
) -> bool:
    src_x0, src_y0, src_x1, src_y1 = [float(v) for v in bbox_mm]
    width = max(1e-9, src_x1 - src_x0)
    height = max(1e-9, src_y1 - src_y0)
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    dx = abs(bx - ax)
    dy = abs(by - ay)
    horizontal = dy <= float(edge_eps_mm)
    vertical = dx <= float(edge_eps_mm)
    if horizontal:
        y = (ay + by) * 0.5
        if (abs(y - src_y0) <= float(edge_eps_mm) or abs(y - src_y1) <= float(edge_eps_mm)) and dx >= max(
            20.0,
            width * 0.35,
        ):
            return True
    if vertical:
        x = (ax + bx) * 0.5
        if (abs(x - src_x0) <= float(edge_eps_mm) or abs(x - src_x1) <= float(edge_eps_mm)) and dy >= max(
            20.0,
            height * 0.35,
        ):
            return True
    return False


def _structural_outer_frame_bbox_mm(
    polylines: list[list[tuple[float, float]]],
) -> tuple[float, float, float, float]:
    content_bbox = _polys_bbox_mm(polylines)
    content_w = max(1e-9, float(content_bbox[2]) - float(content_bbox[0]))
    content_h = max(1e-9, float(content_bbox[3]) - float(content_bbox[1]))
    horizontal_ys: list[float] = []
    vertical_xs: list[float] = []
    for poly in polylines:
        if len(poly) < 2:
            continue
        for idx in range(1, len(poly)):
            ax, ay = poly[idx - 1]
            bx, by = poly[idx]
            x0, x1 = sorted((float(ax), float(bx)))
            y0, y1 = sorted((float(ay), float(by)))
            bw = float(x1) - float(x0)
            bh = float(y1) - float(y0)
            if bh <= 0.35 and bw >= max(40.0, content_w * 0.35):
                horizontal_ys.append((float(y0) + float(y1)) * 0.5)
            if bw <= 0.35 and bh >= max(40.0, content_h * 0.35):
                vertical_xs.append((float(x0) + float(x1)) * 0.5)
    if len(horizontal_ys) >= 2 and len(vertical_xs) >= 2:
        return min(vertical_xs), min(horizontal_ys), max(vertical_xs), max(horizontal_ys)
    return content_bbox


def _strip_outer_bbox_frame_segments(
    polylines: list[list[tuple[float, float]]],
) -> tuple[list[list[tuple[float, float]]], dict[str, Any]]:
    clean_polys = [list(poly) for poly in polylines if len(poly) >= 2]
    if not clean_polys:
        return [], {"applied": False, "removed_segments": 0}
    bbox = _structural_outer_frame_bbox_mm(clean_polys)
    kept: list[list[tuple[float, float]]] = []
    removed_segments = 0
    for poly in clean_polys:
        current: list[tuple[float, float]] = []
        for idx in range(1, len(poly)):
            a = (float(poly[idx - 1][0]), float(poly[idx - 1][1]))
            b = (float(poly[idx][0]), float(poly[idx][1]))
            if _is_outer_bbox_frame_segment(a, b, bbox_mm=bbox):
                if len(current) >= 2:
                    kept.append(current)
                current = []
                removed_segments += 1
                continue
            if not current:
                current = [a]
            current.append(b)
        if len(current) >= 2:
            kept.append(current)

    if removed_segments < 2:
        return clean_polys, {
            "applied": False,
            "removed_segments": int(removed_segments),
            "source_bbox": [round(float(v), 4) for v in bbox],
        }

    return kept, {
        "applied": True,
        "removed_segments": int(removed_segments),
        "source_bbox": [round(float(v), 4) for v in bbox],
    }


def _polyline_segment_count(polylines: list[list[tuple[float, float]]]) -> int:
    return sum(max(0, len(poly) - 1) for poly in polylines)


def _prepare_kompas_a4_clean_bbox_fit_polylines(
    source_polys: list[list[tuple[float, float]]],
    *,
    logs: list[str],
) -> tuple[list[list[tuple[float, float]]], dict[str, Any]]:
    stripped, frame_meta = _strip_outer_bbox_frame_segments(source_polys)
    if not bool(frame_meta.get("applied")):
        return [], {
            "applied": False,
            "reason": "source_outer_frame_not_found",
            **frame_meta,
        }

    work_x0, work_x1, work_y0, work_y1 = _machine_work_area_bounds_mm()
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
    pre_clip_segments = _polyline_segment_count(mapped_inner)
    pre_clip_bbox = _polys_bbox_mm(mapped_inner) if mapped_inner else (0.0, 0.0, 0.0, 0.0)
    clip_logs: list[str] = []
    clipped_inner = backend.clip_polylines_to_work_area(mapped_inner, logger=clip_logs.append)
    post_clip_segments = _polyline_segment_count(clipped_inner)
    clipped_segments = max(0, int(pre_clip_segments) - int(post_clip_segments))
    if clip_logs:
        logs.extend(f"KOMPAS A4 1:1 clip: {line}" for line in clip_logs)

    optimized_inner = backend.deduplicate_segments(clipped_inner, logger=logs.append)
    optimized_inner = backend.deduplicate_collinear_overlaps(optimized_inner, logger=logs.append)
    optimized_inner = backend.reorder_polylines(optimized_inner, logger=logs.append)
    final_polys = [_work_area_frame_polyline((work_x0, work_x1, work_y0, work_y1)), *optimized_inner]
    final_polys = backend.deduplicate_segments(final_polys, logger=logs.append)
    final_polys = backend.deduplicate_collinear_overlaps(final_polys, logger=logs.append)
    logs.append(
        "KOMPAS A4 clean-bbox route: source-page fit disabled; "
        f"source_frame_bbox={[round(float(v), 4) for v in frame_meta['source_bbox']]}; "
        f"content_scale={content_scale:.6f}; "
        f"translate=({dx:.4f},{dy:.4f}) mm; "
        f"pre_clip_bbox={[round(float(v), 4) for v in pre_clip_bbox]}; "
        f"clipped_segments={clipped_segments}; "
        "work_area_frame=full."
    )
    return final_polys, {
        "applied": True,
        "source_bbox": frame_meta["source_bbox"],
        "removed_segments": int(frame_meta.get("removed_segments", 0)),
        "content_scale": round(float(content_scale), 6),
        "translate_x_mm": round(float(dx), 6),
        "translate_y_mm": round(float(dy), 6),
        "pre_clip_bbox": [round(float(v), 4) for v in pre_clip_bbox],
        "clipped_segments": int(clipped_segments),
        "work_area_bounds": [round(float(v), 4) for v in (work_x0, work_x1, work_y0, work_y1)],
    }


@contextmanager
def _literal_gcode_rewrite_context() -> Any:
    prev = {
        "SIMPLIFY_ENABLED": bool(getattr(backend, "SIMPLIFY_ENABLED", True)),
        "EMIT_ARCS": bool(getattr(backend, "EMIT_ARCS", True)),
        "LINE_FIT_TOL_MM": float(getattr(backend, "LINE_FIT_TOL_MM", 0.0)),
        "RDP_SIMPLIFY_EPS_MM": float(getattr(backend, "RDP_SIMPLIFY_EPS_MM", 0.0)),
        "TECH_TEXT_JOIN_ENABLE": bool(getattr(backend, "TECH_TEXT_JOIN_ENABLE", True)),
    }
    try:
        setattr(backend, "SIMPLIFY_ENABLED", False)
        setattr(backend, "EMIT_ARCS", False)
        setattr(backend, "LINE_FIT_TOL_MM", 0.0)
        setattr(backend, "RDP_SIMPLIFY_EPS_MM", 0.0)
        setattr(backend, "TECH_TEXT_JOIN_ENABLE", False)
        yield
    finally:
        for key, value in prev.items():
            setattr(backend, key, value)


def _rewrite_final_gcode_from_polylines(
    polylines: list[list[tuple[float, float]]],
    *,
    dst_nc: Path,
    dst_gcode: Path,
) -> None:
    dst_nc.parent.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "_tmp").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(PROJECT_ROOT / "_tmp"), ignore_cleanup_errors=True) as td:
        work = Path(td)
        xy_path = work / "frame_rewrite_xy.gcode"
        pen_path = work / "frame_rewrite_pen.gcode"
        final_path = work / "frame_rewrite_final.gcode"
        with _literal_gcode_rewrite_context():
            backend.write_xy_gcode(
                xy_path,
                polylines,
                float(backend.FEED_TRAVEL),
                float(backend.FEED_DRAW),
                join_eps=0.0,
            )
            backend.apply_penlift(
                xy_path,
                pen_path,
                z_down=float(backend.Z_DOWN),
                handwriting_mode=False,
                force_full_lift=True,
            )
            backend.make_final_with_preamble(pen_path, final_path)
        _copy_nc_and_gcode(final_path, dst_nc, dst_gcode)


def _build_tiled_combined_preview(
    *,
    source_pdf: Path,
    package_dir: Path,
    report: dict[str, Any],
    canvas_size_mm: tuple[float, float] | None = None,
    similarity_reference_pdf: Path | None = None,
    keep_fitted_coords: bool = False,
) -> dict[str, Any] | None:
    pass_ncs = sorted((package_dir / "pages").glob("pass_*.nc"))
    if not pass_ncs:
        return None
    pass_logs = [package_dir / "logs" / f"{nc.stem}.log.txt" for nc in pass_ncs]
    if not all(path.exists() for path in pass_logs):
        return None

    reference_pdf = similarity_reference_pdf or source_pdf

    polylines: list[list[tuple[float, float]]] = []
    for nc_path, log_path in zip(pass_ncs, pass_logs):
        polylines.extend(
            _inverse_a3_pass_polylines_to_sheet(
                nc_path=nc_path,
                log_path=log_path,
                keep_fitted_coords=keep_fitted_coords,
            )
        )
    if not polylines:
        return None

    if canvas_size_mm is None:
        ref_w_mm, ref_h_mm = _pdf_first_page_size_mm(reference_pdf)
    else:
        ref_w_mm, ref_h_mm = [float(v) for v in canvas_size_mm]
    combined_svg = package_dir / "combined_preview.svg"
    combined_pdf = package_dir / "combined_preview.pdf"
    _write_svg_preview(polylines, combined_svg, canvas_bounds_mm=(0.0, ref_w_mm, 0.0, ref_h_mm))
    _render_polylines_pdf(polylines=polylines, out_pdf=combined_pdf, canvas_bounds_mm=(0.0, ref_w_mm, 0.0, ref_h_mm))
    similarity = _layout_similarity_pdf(reference_pdf, combined_pdf, source_page_index=0)
    return {
        "reference_pdf": str(reference_pdf),
        "svg": str(combined_svg),
        "pdf": str(combined_pdf),
        "layout_similarity": float(similarity),
    }


def _build_a3_combined_preview(
    *,
    source_pdf: Path,
    package_dir: Path,
    report: dict[str, Any],
) -> dict[str, Any] | None:
    if bool(report.get("forced_a3_two_pass")):
        # For oversized source sheets forced into a 2-pass A3 workflow, the
        # stitched preview is primarily a source-vs-output audit artifact.
        # Keep it in source-sheet coordinates so comparison remains readable;
        # the actual A3-ready outputs are pass_01/pass_02.
        return _build_tiled_combined_preview(
            source_pdf=source_pdf,
            package_dir=package_dir,
            report=report,
        )
    return _build_tiled_combined_preview(source_pdf=source_pdf, package_dir=package_dir, report=report)


@contextmanager
def _backend_override_context(backend_overrides: dict[str, Any] | None):
    overrides = dict(backend_overrides or {})
    if not overrides:
        yield
        return
    saved: dict[str, Any] = {}
    try:
        for key, value in overrides.items():
            if hasattr(backend, key):
                saved[key] = getattr(backend, key)
                setattr(backend, key, value)
        yield
    finally:
        for key, value in saved.items():
            setattr(backend, key, value)


def _mirror_package_root_artifacts(package_dir: Path, rows: list[ArtifactRow]) -> None:
    for row in rows:
        if not bool(row.ok):
            continue
        for src_text in (row.preview_pdf, row.preview_svg, row.nc, row.gcode):
            if not src_text:
                continue
            src = Path(str(src_text))
            if not src.exists() or not src.is_file():
                continue
            _copy_file(src, package_dir / src.name)


def _polyline_axis_aligned(poly: list[tuple[float, float]], *, eps_mm: float = 0.08) -> bool:
    if len(poly) < 2:
        return False
    for idx in range(1, len(poly)):
        x0, y0 = poly[idx - 1]
        x1, y1 = poly[idx]
        dx = abs(float(x1) - float(x0))
        dy = abs(float(y1) - float(y0))
        if dx <= eps_mm or dy <= eps_mm:
            continue
        return False
    return True


def _table_like_overlay_polylines(page_svg: Path) -> list[list[tuple[float, float]]]:
    try:
        items = backend.extract_polylines(page_svg)
    except Exception:
        return []
    out: list[list[tuple[float, float]]] = []
    for item in items:
        poly = list(item.points or [])
        if len(poly) < 2:
            continue
        if not bool(item.is_stroke):
            continue
        if bool(item.is_fill) and len(poly) > 2:
            continue
        if not _polyline_axis_aligned(poly):
            continue
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        width_mm = max(xs) - min(xs)
        height_mm = max(ys) - min(ys)
        draw_len_mm = _polyline_length(poly)
        if max(width_mm, height_mm) < 3.5 and draw_len_mm < 5.0:
            continue
        out.append(poly)
    return out


def _merge_table_like_vectors_into_svg(*, source_page_svg: Path, target_svg: Path) -> int:
    polylines = _table_like_overlay_polylines(source_page_svg)
    if not polylines:
        return 0
    tree = ET.parse(target_svg)
    root = tree.getroot()
    target_scale = float(backend.infer_scale(root) or 1.0)
    if target_scale <= 1e-9:
        return 0
    ns_uri = str(root.tag).split("}")[0].strip("{") if "}" in str(root.tag) else "http://www.w3.org/2000/svg"
    group = ET.Element(f"{{{ns_uri}}}g")
    group.set("id", "table_vector_overlay")
    stroke_width_units = max(0.35, 0.18 / target_scale)
    added = 0
    for poly in polylines:
        if len(poly) < 2:
            continue
        d_parts = [f"M {poly[0][0] / target_scale:.4f} {poly[0][1] / target_scale:.4f}"]
        for x_mm, y_mm in poly[1:]:
            d_parts.append(f"L {x_mm / target_scale:.4f} {y_mm / target_scale:.4f}")
        path_el = ET.Element(f"{{{ns_uri}}}path")
        path_el.set("d", " ".join(d_parts))
        path_el.set("fill", "none")
        path_el.set("stroke", "#222222")
        path_el.set("stroke-width", f"{stroke_width_units:.4f}")
        path_el.set("stroke-linecap", "round")
        path_el.set("stroke-linejoin", "miter")
        group.append(path_el)
        added += 1
    if added <= 0:
        return 0
    root.append(group)
    tree.write(target_svg, encoding="utf-8", xml_declaration=True)
    return added


def _rewrite_pdf_page_text_to_handwritten_pdf(
    *,
    source_pdf: Path,
    page_index: int,
    font_path: Path,
    out_pdf: Path,
    formula_font_path: Path | None = None,
    render_dpi: int = 450,
) -> None:
    def _classify_line_role(text: str, spans: list[dict[str, Any]]) -> str:
        raw = str(text or "").strip()
        if not raw:
            return text_content_routing.ROLE_BODY_HANDWRITING
        span_font_size = 0.0
        try:
            span_font_size = max(float(span.get("size", 0.0) or 0.0) for span in spans) if spans else 0.0
        except Exception:
            span_font_size = 0.0
        return text_content_routing.classify_text_content_role(
            raw,
            font_size=span_font_size or None,
            font_names=[str(span.get("font", "")) for span in spans],
            text_contains_formula_script_fn=getattr(backend, "_text_contains_formula_script", lambda _text: False),
        )

    def _line_prefers_print_formula_font(
        text: str,
        spans: list[dict[str, Any]],
        *,
        line_bbox: list[float] | tuple[float, ...] | None = None,
        block_print_cutoff_y: float | None = None,
    ) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        span_font_size = 0.0
        try:
            span_font_size = max(float(span.get("size", 0.0) or 0.0) for span in spans) if spans else 0.0
        except Exception:
            span_font_size = 0.0
        route = _classify_line_role(raw, spans)
        if route != text_content_routing.ROLE_BODY_HANDWRITING:
            return True
        if block_print_cutoff_y is not None and line_bbox and len(line_bbox) >= 4:
            try:
                if float(line_bbox[3]) <= float(block_print_cutoff_y):
                    return True
            except Exception:
                pass
        lower_text = raw.casefold()
        if any(
            token in lower_text
            for token in (
                "\u0442\u0430\u0431\u043b\u0438\u0446",
                "\u0440\u0438\u0441\u0443\u043d\u043e\u043a",
                "\u0440\u0438\u0441.",
                "\u0441\u0445\u0435\u043c",
            )
        ):
            return True
        compact = re.sub(r"\s+", "", raw, flags=re.UNICODE)
        if not compact:
            return False
        if any(ch in compact for ch in "=+-*/^_<>≈≤≥±×÷√∑∫∞[]{}|"):
            return True
        if bool(getattr(backend, "_text_contains_formula_script", lambda _text: False)(compact)):
            return True
        if len(compact) <= 12 and re.search(r"[A-Za-zА-Яа-я]", compact) and re.search(r"\d", compact):
            return True
        if len(compact) <= 8 and re.fullmatch(r"[A-Za-zА-Яа-я]{1,3}\d{0,2}", compact):
            return True
        fonts = " ".join(str(span.get("font", "")) for span in spans).lower()
        if "math" in fonts:
            return True
        alpha = sum(1 for ch in compact if ch.isalpha())
        digits = sum(1 for ch in compact if ch.isdigit())
        operators = sum(1 for ch in compact if ch in "=+-*/^_<>≈≤≥±×÷√∑∫∞")
        if len(compact) <= 24 and operators >= 1 and (alpha + digits) >= 2:
            return True
        if bool(getattr(backend, "_text_prefers_print_font", lambda _text, font_size=None: False)(raw, font_size=span_font_size or None)):
            return True
        return False

    def _block_print_cutoff_y(block: dict[str, Any]) -> float | None:
        consecutive_non_body = 0
        cutoff_y = None
        for line in block.get("lines", []):
            spans = list(line.get("spans", []))
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if not text:
                continue
            bbox = list(line.get("bbox", []))
            if len(bbox) < 4:
                continue
            role = _classify_line_role(text, spans)
            if role != text_content_routing.ROLE_BODY_HANDWRITING:
                consecutive_non_body += 1
                cutoff_y = float(bbox[3]) + 2.0
                continue
            if consecutive_non_body >= 3:
                return cutoff_y
            consecutive_non_body = 0
            cutoff_y = None
        if consecutive_non_body >= 3:
            return cutoff_y
        return None

    doc = fitz.open(source_pdf)
    page = doc[page_index]
    scale = float(render_dpi) / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw = ImageDraw.Draw(image)
    page_dict = page.get_text("dict")

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        block_print_cutoff_y = _block_print_cutoff_y(block)
        bbox = block.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = [float(v) * scale for v in bbox]
        draw.rectangle((x0 - 4, y0 - 4, x1 + 4, y1 + 4), fill="white")
        for line in block.get("lines", []):
            spans = list(line.get("spans", []))
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if not text:
                continue
            rendered_text = str(getattr(backend, "_normalize_handwriting_text_string", lambda value: value)(text))
            line_bbox = line.get("bbox")
            if not line_bbox:
                continue
            lx0, ly0, lx1, ly1 = [float(v) * scale for v in line_bbox]
            target_h = max(12, int((ly1 - ly0) * 0.92))
            target_w = max(12, int((lx1 - lx0) * 0.98))
            size = target_h
            selected_font_path = (
                formula_font_path
                if (
                    formula_font_path is not None
                    and _line_prefers_print_formula_font(
                        text,
                        spans,
                        line_bbox=list(line_bbox),
                        block_print_cutoff_y=block_print_cutoff_y,
                    )
                )
                else font_path
            )
            font = ImageFont.truetype(str(selected_font_path), size=size)
            while size > 8:
                font = ImageFont.truetype(str(selected_font_path), size=size)
                bb = draw.textbbox((0, 0), rendered_text, font=font)
                text_w = bb[2] - bb[0]
                text_h = bb[3] - bb[1]
                if text_w <= target_w and text_h <= max(12, int((ly1 - ly0) * 1.05)):
                    break
                size -= 1
            draw.text((lx0, ly0), rendered_text, font=font, fill=(25, 25, 25))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    raster_png = out_pdf.with_suffix(".png")
    image.save(raster_png)

    out_doc = fitz.open()
    out_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
    out_page.insert_image(out_page.rect, filename=str(raster_png))
    out_doc.save(out_pdf)
    out_doc.close()


def _prepare_toe_raster_fallback(
    *,
    source_pdf: Path,
    page_index: int,
    page_svg: Path | None,
    prefix: Path,
    font_label: str,
    font_path: Path,
    backend_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="toe_raster_fallback_") as td:
        td_path = Path(td)
        rewritten_pdf = td_path / "rewritten.pdf"
        rewritten_svg = td_path / "rewritten.svg"
        candidate_prefix = prefix.parent / f"{prefix.name}__fallback_candidate"
        ctx = _ctx(f"preview-{time.time_ns()}")
        preflight_logs: list[str] = []
        formula_font_path = None
        for candidate in (
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "times.ttf",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "cambria.ttc",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
        ):
            if candidate.exists() and candidate.is_file():
                formula_font_path = candidate
                break
        _rewrite_pdf_page_text_to_handwritten_pdf(
            source_pdf=source_pdf,
            page_index=page_index - 1,
            font_path=font_path,
            out_pdf=rewritten_pdf,
            formula_font_path=formula_font_path,
        )
        preview_input = rewritten_pdf
        try:
            _export_pdf_page_to_mupdf_svg(rewritten_pdf, 0, rewritten_svg)
            preview_input = rewritten_svg
            if page_svg is not None and page_svg.exists() and page_svg.is_file():
                merged = _merge_table_like_vectors_into_svg(
                    source_page_svg=page_svg,
                    target_svg=rewritten_svg,
                )
                preflight_logs.append(f"table_vector_overlay_count={int(merged)}")
        except Exception as exc:
            preflight_logs.append(f"table_vector_overlay_failed={exc!r}")
            preview_input = rewritten_pdf
        with _backend_override_context(backend_overrides):
            ok, msg, logs = _bridge_run_preview(
                ctx=ctx,
                input_path=preview_input,
                sheet=SheetConfig(sheet_format="a4", anchor="lower_left"),
                tool_mode="pencil",
                render_mode="handwriting",
                quality_profile="high",
                force_text_to_path=False,
                handwriting_enabled=True,
                handwriting_font=str(font_path),
                handwriting_formula_font=str(toe_font_policy.DEFAULT_FORMULA_FONT_FAMILY),
                image_contours_mode="always",
                source_page_index=1,
                source_all_pages=False,
                exact_geometry_mode=True,
                safe_travel_lift=False,
                strict_one_to_one=False,
            )
        if not ok:
            return {
                "ok": False,
                "message": msg,
                "logs": [*preflight_logs, *logs],
                "font_label": font_label,
                "font_path": str(font_path),
            }
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(candidate_prefix, op_id=ctx.op_id)
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1)
        return {
            "ok": True,
            "message": msg,
            "logs": [*preflight_logs, *logs],
            "font_label": font_label,
            "font_path": str(font_path),
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "notes": (
                "fallback=raster_rewrite_handdraw; "
                f"body_font={font_label}; "
                f"formula_font={toe_font_policy.DEFAULT_FORMULA_FONT_FAMILY}; "
                "table_vector_overlay=enabled"
            ),
        }


def _bridge_run_preview(
    *,
    ctx: OperationContext,
    input_path: Path,
    sheet: SheetConfig,
    tool_mode: str,
    render_mode: str,
    quality_profile: str,
    force_text_to_path: bool,
    handwriting_enabled: bool,
    handwriting_font: str,
    handwriting_formula_font: str,
    image_contours_mode: str,
    source_page_index: int,
    source_all_pages: bool,
    exact_geometry_mode: bool,
    safe_travel_lift: bool,
    strict_one_to_one: bool,
) -> tuple[bool, str, list[str]]:
    bridge = BackendBridge(PROJECT_ROOT)
    logs: list[str] = []
    with _technical_drawing_backend_precision():
        ok, msg = bridge.run_preview(
            ctx=ctx,
            input_path=input_path,
            sheet=sheet,
            tool_mode=tool_mode,
            render_mode=render_mode,
            quality_profile=quality_profile,
            force_text_to_path=force_text_to_path,
            handwriting_enabled=handwriting_enabled,
            handwriting_font=handwriting_font,
            handwriting_formula_font=handwriting_formula_font,
            image_contours_mode=image_contours_mode,
            source_page_index=source_page_index,
            source_all_pages=source_all_pages,
            exact_geometry_mode=exact_geometry_mode,
            safe_travel_lift=safe_travel_lift,
            strict_one_to_one=strict_one_to_one,
            log=logs.append,
        )
    return ok, msg, logs


def _configure_drawing_method3_backend(
    *,
    sheet_format: str = "a4",
    pass_cols: int = 1,
    pass_rows: int = 1,
    pass_col: int = 1,
    pass_row: int = 1,
) -> tuple[float, float]:
    backend.HANDWRITING_TEXT_ENABLED = True
    backend.HANDWRITING_FONT_FAMILY = "Marck Script"
    backend.HANDWRITING_CYRILLIC_FONT_FAMILY = "Marck Script"
    backend.HANDWRITING_SINGLELINE_TTF_BACKEND = "autotrace3"
    backend.HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = True
    backend.IMAGE_CONTOUR_MODE = "off"
    backend.IMAGE_CONTOUR_ENABLED = False
    backend.IMAGE_CONTOUR_WORD_ONLY = False
    backend.FORCE_TEXT_TO_PATH = False
    backend.USE_INKSCAPE_PDF_IMPORT = False
    backend.EXACT_GEOMETRY_MODE = True
    backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.0
    backend.SAFE_PEN_TRAVEL_UP = True
    backend.TOOL_MODE = "pen"
    backend.PASS_COLS = max(1, int(pass_cols))
    backend.PASS_ROWS = max(1, int(pass_rows))
    backend.PASS_COL = min(max(1, int(pass_col)), backend.PASS_COLS)
    backend.PASS_ROW = min(max(1, int(pass_row)), backend.PASS_ROWS)
    backend.apply_quality_profile("high", force_text_to_path=False)
    backend.configure_active_work_area(
        sheet_format=sheet_format,
        sheet_width_mm=None,
        sheet_height_mm=None,
        anchor="lower_left",
        offset_x_mm=0.0,
        offset_y_mm=0.0,
        logger=lambda *_args, **_kwargs: None,
    )
    area_min_x, area_max_x, area_min_y, area_max_y = backend.work_area_bounds()
    return (float(area_max_x) - float(area_min_x), float(area_max_y) - float(area_min_y))


def _parse_method3_svg_polylines(svg_path: Path) -> list[list[tuple[float, float]]]:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}
    out: list[list[tuple[float, float]]] = []
    for node in root.findall(".//svg:path", ns):
        d = str(node.get("d") or "").strip()
        if not d:
            continue
        tokens = d.replace(",", " ").split()
        pts: list[tuple[float, float]] = []
        idx = 0
        while idx < len(tokens):
            cmd = tokens[idx]
            if cmd in {"M", "L"} and (idx + 2) < len(tokens):
                try:
                    pts.append((float(tokens[idx + 1]), float(tokens[idx + 2])))
                except Exception:
                    pts = []
                    break
                idx += 3
                continue
            idx += 1
        if len(pts) >= 2:
            out.append(pts)
    return out


def _is_small_condition_image_rect_mm(
    x0_mm: float,
    y0_mm: float,
    x1_mm: float,
    y1_mm: float,
) -> bool:
    w_mm = max(0.0, float(x1_mm) - float(x0_mm))
    h_mm = max(0.0, float(y1_mm) - float(y0_mm))
    area_mm2 = float(w_mm) * float(h_mm)
    if w_mm < float(_CONDITION_IMAGE_MIN_W_MM) or h_mm < float(_CONDITION_IMAGE_MIN_H_MM):
        return False
    if w_mm > float(_CONDITION_IMAGE_MAX_W_MM) or h_mm > float(_CONDITION_IMAGE_MAX_H_MM):
        return False
    if area_mm2 > float(_CONDITION_IMAGE_MAX_AREA_MM2):
        return False
    return True


def _is_a3_header_band_image_rect_mm(
    x0_mm: float,
    y0_mm: float,
    x1_mm: float,
    y1_mm: float,
    *,
    page_w_mm: float,
    page_h_mm: float,
) -> bool:
    if float(page_w_mm) < 350.0 or float(page_h_mm) < 250.0:
        return False
    w_mm = max(0.0, float(x1_mm) - float(x0_mm))
    h_mm = max(0.0, float(y1_mm) - float(y0_mm))
    if float(x0_mm) > float(_A3_HEADER_IMAGE_MAX_X0_MM):
        return False
    if float(y0_mm) > float(_A3_HEADER_IMAGE_MAX_Y0_MM):
        return False
    if w_mm < float(_A3_HEADER_IMAGE_MIN_W_MM) or w_mm > float(_A3_HEADER_IMAGE_MAX_W_MM):
        return False
    if h_mm < float(_A3_HEADER_IMAGE_MIN_H_MM) or h_mm > float(_A3_HEADER_IMAGE_MAX_H_MM):
        return False
    return True


def _detect_a3_header_miniature_crop_px(image: Image.Image) -> tuple[int, int, int, int] | None:
    gray = image.convert("L")
    arr = np.array(gray, dtype=np.uint8)
    if arr.ndim != 2:
        return None
    height, width = arr.shape
    if width < 80 or height < 40:
        return None
    dark = arr < 230
    col_density = dark.mean(axis=0)
    search_left = max(0, int(round(width * 0.08)))
    search_right = min(width - 1, int(round(width * 0.40)))
    if search_right <= search_left:
        return None
    rel_idx = int(np.argmax(col_density[search_left:search_right]))
    divider_x = search_left + rel_idx
    if float(col_density[divider_x]) < 0.30:
        divider_x = min(width - 1, int(round(height * 1.25)))
    divider_x = max(1, min(divider_x, width - 1))
    work_left = max(0, min(int(round(height * 0.14)), divider_x - 4))
    work_right = max(work_left + 4, divider_x - 2)
    top_exclude = min(height - 1, max(0, int(round(height * 0.12))))
    roi = dark[top_exclude:, work_left:work_right]
    if roi.size == 0 or not bool(roi.any()):
        return None
    ys, xs = np.nonzero(roi)
    margin_x = max(2, int(round(height * 0.03)))
    margin_y = max(2, int(round(height * 0.03)))
    x0 = max(search_left, work_left + int(xs.min()) - margin_x)
    x1 = min(divider_x, work_left + int(xs.max()) + 1 + margin_x)
    y0 = max(top_exclude, top_exclude + int(ys.min()) - margin_y)
    y1 = min(height, top_exclude + int(ys.max()) + 1 + margin_y)
    if (x1 - x0) < 20 or (y1 - y0) < 20:
        return None
    return (x0, y0, x1, y1)


def _extract_small_condition_image_polylines_from_pdf(
    source_pdf: Path,
    *,
    page_index: int,
    logger,
) -> tuple[list[list[tuple[float, float]]], list[dict[str, float]]]:
    out: list[list[tuple[float, float]]] = []
    recovered: list[dict[str, float]] = []
    if fitz is None:
        return out, recovered

    doc = fitz.open(str(source_pdf))
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            return out, recovered
        page = doc[page_index]
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
        seen: set[tuple[float, float, float, float]] = set()
        prev_state = {
            "HANDWRITING_TEXT_ENABLED": bool(getattr(backend, "HANDWRITING_TEXT_ENABLED", False)),
            "HANDWRITING_SINGLELINE_TTF_BACKEND": str(getattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "autotrace3")),
            "IMAGE_CONTOUR_ENABLED": bool(getattr(backend, "IMAGE_CONTOUR_ENABLED", True)),
            "IMAGE_CONTOUR_WORD_ONLY": bool(getattr(backend, "IMAGE_CONTOUR_WORD_ONLY", False)),
            "IMAGE_CONTOUR_MODE": str(getattr(backend, "IMAGE_CONTOUR_MODE", "off")),
            "IMAGE_CONTOUR_VECTORIZE_MODE": str(getattr(backend, "IMAGE_CONTOUR_VECTORIZE_MODE", "centerline")),
            "IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE": str(getattr(backend, "IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE", "centerline")),
            "IMAGE_CONTOUR_MM_SIMPLIFY_EPS": float(getattr(backend, "IMAGE_CONTOUR_MM_SIMPLIFY_EPS", 0.12)),
            "IMAGE_CONTOUR_LINEART_SIMPLIFY_MM": float(getattr(backend, "IMAGE_CONTOUR_LINEART_SIMPLIFY_MM", 0.08)),
            "IMAGE_CONTOUR_SMALL_LINEART_SIMPLIFY_MM": float(getattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_SIMPLIFY_MM", 0.035)),
            "IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2": float(getattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2", 10.0)),
        }
        try:
            setattr(backend, "HANDWRITING_TEXT_ENABLED", True)
            setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "autotrace3")
            setattr(backend, "IMAGE_CONTOUR_ENABLED", True)
            setattr(backend, "IMAGE_CONTOUR_WORD_ONLY", False)
            setattr(backend, "IMAGE_CONTOUR_MODE", "always")
            setattr(backend, "IMAGE_CONTOUR_VECTORIZE_MODE", "centerline")
            setattr(backend, "IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE", "centerline")
            setattr(backend, "IMAGE_CONTOUR_MM_SIMPLIFY_EPS", 0.02)
            setattr(backend, "IMAGE_CONTOUR_LINEART_SIMPLIFY_MM", 0.02)
            setattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_SIMPLIFY_MM", 0.015)
            setattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2", 9999.0)
            with tempfile.TemporaryDirectory(prefix="plotter_condimg_") as td:
                td_path = Path(td)
                for img_idx, img in enumerate(page.get_images(full=True)):
                    xref = int(img[0])
                    extracted_image = None
                    try:
                        meta = doc.extract_image(xref)
                        if meta and meta.get("image"):
                            extracted_image = Image.open(io.BytesIO(meta["image"])).convert("L")
                    except Exception:
                        extracted_image = None
                    for rect_idx, rect in enumerate(page.get_image_rects(xref)):
                        x0_mm = float(rect.x0) * 25.4 / 72.0
                        y0_mm = float(rect.y0) * 25.4 / 72.0
                        x1_mm = float(rect.x1) * 25.4 / 72.0
                        y1_mm = float(rect.y1) * 25.4 / 72.0
                        key = (
                            round(x0_mm, 2),
                            round(y0_mm, 2),
                            round(x1_mm, 2),
                            round(y1_mm, 2),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        is_small = _is_small_condition_image_rect_mm(x0_mm, y0_mm, x1_mm, y1_mm)
                        is_header_band = _is_a3_header_band_image_rect_mm(
                            x0_mm,
                            y0_mm,
                            x1_mm,
                            y1_mm,
                            page_w_mm=page_w_mm,
                            page_h_mm=page_h_mm,
                        )
                        if not is_small and not is_header_band:
                            continue

                        png_path = td_path / f"condimg_{img_idx}_{rect_idx}.png"
                        svg_path = td_path / f"condimg_{img_idx}_{rect_idx}.svg"
                        source_img = extracted_image
                        if source_img is None:
                            pix_scale = 6.0 if is_header_band else 4.0
                            pix = page.get_pixmap(matrix=fitz.Matrix(pix_scale, pix_scale), clip=rect, alpha=False)
                            pix.save(png_path)
                            source_img = Image.open(png_path).convert("L")
                        image_x0_mm = float(x0_mm)
                        image_y0_mm = float(y0_mm)
                        image_x1_mm = float(x1_mm)
                        image_y1_mm = float(y1_mm)
                        if is_header_band:
                            crop_box = None
                            try:
                                crop_box = _detect_a3_header_miniature_crop_px(source_img)
                                if crop_box is not None:
                                    crop_x0, crop_y0, crop_x1, crop_y1 = crop_box
                                    full_width_px = max(1, int(source_img.size[0]))
                                    full_height_px = max(1, int(source_img.size[1]))
                                    source_img = source_img.crop(crop_box)
                                    full_width_px = max(1, int(extracted_image.size[0] if extracted_image is not None else source_img.size[0]))
                                    full_height_px = max(1, int(extracted_image.size[1] if extracted_image is not None else source_img.size[1]))
                                    rect_w_mm = max(0.0, float(x1_mm) - float(x0_mm))
                                    rect_h_mm = max(0.0, float(y1_mm) - float(y0_mm))
                                    image_x0_mm = float(x0_mm) + rect_w_mm * (float(crop_x0) / float(full_width_px))
                                    image_x1_mm = float(x0_mm) + rect_w_mm * (float(crop_x1) / float(full_width_px))
                                    image_y0_mm = float(y0_mm) + rect_h_mm * (float(crop_y0) / float(full_height_px))
                                    image_y1_mm = float(y0_mm) + rect_h_mm * (float(crop_y1) / float(full_height_px))
                                    logger(
                                        "A3 header miniature crop: "
                                        f"rect={x0_mm:.2f},{y0_mm:.2f},{x1_mm:.2f},{y1_mm:.2f} mm -> "
                                        f"crop_px={crop_x0},{crop_y0},{crop_x1},{crop_y1}."
                                    )
                            except Exception as exc:
                                logger(f"A3 header miniature crop skipped: {exc}")
                        source_img.save(png_path)
                        svg_path.write_text(
                            "\n".join(
                                [
                                    '<?xml version="1.0" encoding="UTF-8"?>',
                                    '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"',
                                    f'     width="{page_w_mm:.3f}mm" height="{page_h_mm:.3f}mm" viewBox="0 0 {page_w_mm:.6f} {page_h_mm:.6f}">',
                                    f'  <image href="{png_path.name}" x="{image_x0_mm:.4f}" y="{image_y0_mm:.4f}" width="{(image_x1_mm - image_x0_mm):.4f}" height="{(image_y1_mm - image_y0_mm):.4f}" preserveAspectRatio="none" />',
                                    '</svg>',
                                    "",
                                ]
                            ),
                            encoding="utf-8",
                        )
                        items = backend.extract_image_contour_items(svg_path, logger=logger)
                        added = 0
                        for item in items:
                            pts = list(getattr(item, "points", []) or [])
                            if len(pts) >= 2:
                                out.append([(float(x), float(y)) for x, y in pts])
                                added += 1
                        if added > 0:
                            recovered.append(
                                {
                                    "x0_mm": float(x0_mm),
                                    "y0_mm": float(y0_mm),
                                    "x1_mm": float(x1_mm),
                                    "y1_mm": float(y1_mm),
                                    "path_count": float(added),
                                }
                            )
                            logger(
                                "Condition image recovery: "
                                f"rect={x0_mm:.2f},{y0_mm:.2f},{x1_mm:.2f},{y1_mm:.2f} mm -> +{added} path(s)."
                            )
        finally:
            for key, value in prev_state.items():
                setattr(backend, key, value)
    finally:
        doc.close()
    return out, recovered


def _augment_method3_svg_with_condition_images(
    source_pdf: Path,
    *,
    source_svg: Path,
    source_preview_pdf: Path | None,
    page_index: int,
    logger,
    preserve_source_bounds: bool = False,
) -> dict[str, float]:
    extra_polys, recovered = _extract_small_condition_image_polylines_from_pdf(
        source_pdf,
        page_index=page_index,
        logger=logger,
    )
    if not extra_polys:
        return {"image_count": 0.0, "path_count": 0.0}

    source_polys = _parse_method3_svg_polylines(source_svg)
    shift_meta = {"shift_x_mm": 0.0, "shift_y_mm": 0.0}
    if preserve_source_bounds:
        extra_polys, shift_meta = _fit_overlay_polys_within_source_bounds(source_polys, extra_polys)
        if abs(float(shift_meta["shift_x_mm"])) > 1e-6 or abs(float(shift_meta["shift_y_mm"])) > 1e-6:
            logger(
                "Condition image recovery: preserving source bounds by translating overlay "
                f"({float(shift_meta['shift_x_mm']):.2f}, {float(shift_meta['shift_y_mm']):.2f}) mm."
            )
    source_polys.extend(extra_polys)
    with fitz.open(str(source_pdf)) as doc:
        page = doc[page_index]
        page_w_mm = float(page.rect.width) * 25.4 / 72.0
        page_h_mm = float(page.rect.height) * 25.4 / 72.0
    bridge = BackendBridge(PROJECT_ROOT)
    bridge._write_method3_svg(source_svg, source_polys, page_w_mm=page_w_mm, page_h_mm=page_h_mm)
    if source_preview_pdf is not None:
        _render_polylines_pdf(
            polylines=source_polys,
            out_pdf=source_preview_pdf,
            canvas_bounds_mm=(0.0, page_w_mm, 0.0, page_h_mm),
        )
    logger(
        "Condition image recovery summary: "
        f"{len(recovered)} image(s), {len(extra_polys)} path(s) merged into method3 source."
    )
    return {
        "image_count": float(len(recovered)),
        "path_count": float(len(extra_polys)),
        "shift_x_mm": float(shift_meta["shift_x_mm"]),
        "shift_y_mm": float(shift_meta["shift_y_mm"]),
    }


def _poly_bbox_mm(poly: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [float(x) for x, _y in poly]
    ys = [float(y) for _x, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _polys_bbox_mm(polys_mm: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [float(x) for poly in polys_mm for x, _y in poly]
    ys = [float(y) for poly in polys_mm for _x, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _translate_polys_mm(
    polys_mm: list[list[tuple[float, float]]],
    *,
    dx_mm: float,
    dy_mm: float,
) -> list[list[tuple[float, float]]]:
    dx = float(dx_mm)
    dy = float(dy_mm)
    return [[(float(x) + dx, float(y) + dy) for x, y in poly] for poly in polys_mm]


def _fit_overlay_polys_within_source_bounds(
    source_polys: list[list[tuple[float, float]]],
    extra_polys: list[list[tuple[float, float]]],
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    if not source_polys or not extra_polys:
        return list(extra_polys), {"shift_x_mm": 0.0, "shift_y_mm": 0.0}
    src_x0, src_y0, src_x1, src_y1 = _polys_bbox_mm(source_polys)
    ex_x0, ex_y0, ex_x1, ex_y1 = _polys_bbox_mm(extra_polys)
    shift_x = 0.0
    shift_y = 0.0
    if ex_x0 < src_x0:
        shift_x = float(src_x0 - ex_x0)
    elif ex_x1 > src_x1:
        shift_x = float(src_x1 - ex_x1)
    if ex_y0 < src_y0:
        shift_y = float(src_y0 - ex_y0)
    elif ex_y1 > src_y1:
        shift_y = float(src_y1 - ex_y1)
    return _translate_polys_mm(extra_polys, dx_mm=shift_x, dy_mm=shift_y), {
        "shift_x_mm": float(shift_x),
        "shift_y_mm": float(shift_y),
    }


def _poly_is_axis_aligned_mm(poly: list[tuple[float, float]], *, eps: float = 0.45) -> bool:
    if len(poly) < 2:
        return False
    for idx in range(1, len(poly)):
        x1, y1 = poly[idx - 1]
        x2, y2 = poly[idx]
        if abs(float(x2) - float(x1)) <= float(eps):
            continue
        if abs(float(y2) - float(y1)) <= float(eps):
            continue
        return False
    return True


def _poly_is_closed_mm(poly: list[tuple[float, float]], *, eps: float = _TECH_POINT_BOX_CLOSURE_EPS_MM) -> bool:
    if len(poly) < 3:
        return False
    x0, y0 = poly[0]
    x1, y1 = poly[-1]
    return math.hypot(float(x1) - float(x0), float(y1) - float(y0)) <= float(eps)


def _quantized_axis_values(vals: list[float], *, eps: float) -> list[float]:
    out: list[float] = []
    for val in sorted(float(v) for v in vals):
        if not out or abs(float(val) - float(out[-1])) > float(eps):
            out.append(float(val))
    return out


def _is_technical_point_box_poly(
    poly: list[tuple[float, float]],
    *,
    max_mm: float | None = None,
) -> bool:
    if len(poly) < 5 or not _poly_is_closed_mm(poly):
        return False
    ring = poly[:-1]
    if len(ring) != 4:
        return False
    if not _poly_is_axis_aligned_mm(poly, eps=float(_TECH_POINT_BOX_AXIS_EPS_MM)):
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    w = float(x1 - x0)
    h = float(y1 - y0)
    max_side = float(_TECH_POINT_BOX_MAX_MM if max_mm is None else max_mm)
    if w < float(_TECH_POINT_BOX_MIN_MM) or h < float(_TECH_POINT_BOX_MIN_MM):
        return False
    if w > float(max_side) or h > float(max_side):
        return False
    aspect = max(w, h) / max(1e-9, min(w, h))
    if aspect > float(_TECH_POINT_BOX_MAX_ASPECT):
        return False
    xs = _quantized_axis_values([pt[0] for pt in ring], eps=float(_TECH_POINT_BOX_AXIS_EPS_MM))
    ys = _quantized_axis_values([pt[1] for pt in ring], eps=float(_TECH_POINT_BOX_AXIS_EPS_MM))
    return len(xs) == 2 and len(ys) == 2


def _technical_point_dot_poly_from_box(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    cx = (float(x0) + float(x1)) * 0.5
    cy = (float(y0) + float(y1)) * 0.5
    r = min(float(x1 - x0), float(y1 - y0)) * 0.18
    r = max(float(_TECH_POINT_BOX_DOT_MIN_R_MM), min(float(_TECH_POINT_BOX_DOT_MAX_R_MM), float(r)))
    segs = max(6, int(_TECH_POINT_BOX_DOT_SEGMENTS))
    pts: list[tuple[float, float]] = []
    for idx in range(segs):
        ang = (2.0 * math.pi * float(idx)) / float(segs)
        pts.append((cx + (r * math.cos(ang)), cy + (r * math.sin(ang))))
    pts.append(pts[0])
    return pts


def _technical_point_box_center_mm(poly: list[tuple[float, float]]) -> tuple[float, float]:
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    return ((float(x0) + float(x1)) * 0.5, (float(y0) + float(y1)) * 0.5)


def _is_small_arrow_bbox_artifact_poly(poly: list[tuple[float, float]]) -> bool:
    if len(poly) < 5 or not _poly_is_closed_mm(poly):
        return False
    ring = poly[:-1]
    if len(ring) != 4:
        return False
    if not _poly_is_axis_aligned_mm(poly, eps=float(_TECH_POINT_BOX_AXIS_EPS_MM)):
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    w = float(x1 - x0)
    h = float(y1 - y0)
    if min(w, h) < float(_TECH_ARROW_BBOX_ARTIFACT_MIN_MM):
        return False
    if max(w, h) > float(_TECH_ARROW_BBOX_ARTIFACT_MAX_MM):
        return False
    aspect = max(w, h) / max(1e-9, min(w, h))
    if aspect < float(_TECH_ARROW_BBOX_ARTIFACT_MIN_ASPECT):
        return False
    xs = _quantized_axis_values([pt[0] for pt in ring], eps=float(_TECH_POINT_BOX_AXIS_EPS_MM))
    ys = _quantized_axis_values([pt[1] for pt in ring], eps=float(_TECH_POINT_BOX_AXIS_EPS_MM))
    return len(xs) == 2 and len(ys) == 2


def _poly_area_mm2(poly: list[tuple[float, float]]) -> float:
    ring = poly[:-1] if _poly_is_closed_mm(poly) else poly
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for idx in range(len(ring)):
        x1, y1 = ring[idx]
        x2, y2 = ring[(idx + 1) % len(ring)]
        total += (float(x1) * float(y2)) - (float(x2) * float(y1))
    return abs(float(total)) * 0.5


def _is_convex_ring_mm(ring: list[tuple[float, float]]) -> bool:
    n = len(ring)
    if n < 3:
        return False
    sign = 0
    for idx in range(n):
        p0 = ring[idx - 1]
        p1 = ring[idx]
        p2 = ring[(idx + 1) % n]
        z = (float(p1[0]) - float(p0[0])) * (float(p2[1]) - float(p1[1])) - (float(p1[1]) - float(p0[1])) * (float(p2[0]) - float(p1[0]))
        if abs(float(z)) <= 1e-9:
            continue
        cur = 1 if z > 0 else -1
        if sign == 0:
            sign = cur
        elif sign != cur:
            return False
    return True


def _vertex_angle_deg_mm(prev_pt: tuple[float, float], pt: tuple[float, float], next_pt: tuple[float, float]) -> float:
    ux = float(prev_pt[0]) - float(pt[0])
    uy = float(prev_pt[1]) - float(pt[1])
    vx = float(next_pt[0]) - float(pt[0])
    vy = float(next_pt[1]) - float(pt[1])
    nu = math.hypot(float(ux), float(uy))
    nv = math.hypot(float(vx), float(vy))
    if nu <= 1e-12 or nv <= 1e-12:
        return 180.0
    dot = ((ux * vx) + (uy * vy)) / (nu * nv)
    dot = max(-1.0, min(1.0, float(dot)))
    return float(math.degrees(math.acos(dot)))


def _compact_arrowhead_v_polyline_mm(poly: list[tuple[float, float]]) -> list[tuple[float, float]] | None:
    if len(poly) < 4 or not _poly_is_closed_mm(poly):
        return None
    ring = poly[:-1]
    n = len(ring)
    if n < 3 or n > int(_TECH_ARROWHEAD_MAX_VERTICES):
        return None
    if not _is_convex_ring_mm(ring):
        return None
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    w = float(x1 - x0)
    h = float(y1 - y0)
    if w <= 1e-9 or h <= 1e-9:
        return None
    if w > float(_TECH_ARROWHEAD_MAX_BBOX_MM) or h > float(_TECH_ARROWHEAD_MAX_BBOX_MM):
        return None
    area = _poly_area_mm2(poly)
    if area < float(_TECH_ARROWHEAD_MIN_AREA_MM2) or area > float(_TECH_ARROWHEAD_MAX_AREA_MM2):
        return None
    fill_ratio = float(area) / max(1e-9, float(w) * float(h))
    if fill_ratio > float(_TECH_ARROWHEAD_MAX_FILL_RATIO):
        return None

    tip_idx = -1
    tip_angle = 180.0
    for idx in range(n):
        angle = _vertex_angle_deg_mm(ring[idx - 1], ring[idx], ring[(idx + 1) % n])
        if angle < tip_angle:
            tip_angle = angle
            tip_idx = idx
    if tip_idx < 0:
        return None

    other_ids = [idx for idx in range(n) if idx != tip_idx]
    if len(other_ids) < 2:
        return None
    tip = ring[tip_idx]
    best_pair: tuple[int, int] | None = None
    best_pair_dist = -1.0
    for i_pos in range(len(other_ids)):
        for j_pos in range(i_pos + 1, len(other_ids)):
            ii = other_ids[i_pos]
            jj = other_ids[j_pos]
            dist = math.hypot(float(ring[ii][0]) - float(ring[jj][0]), float(ring[ii][1]) - float(ring[jj][1]))
            if dist > best_pair_dist:
                best_pair_dist = dist
                best_pair = (ii, jj)
    if best_pair is None:
        return None
    base_l = ring[best_pair[0]]
    base_r = ring[best_pair[1]]
    if math.hypot(float(base_l[0]) - float(tip[0]), float(base_l[1]) - float(tip[1])) < 0.15:
        return None
    if math.hypot(float(base_r[0]) - float(tip[0]), float(base_r[1]) - float(tip[1])) < 0.15:
        return None
    if math.hypot(float(base_l[0]) - float(base_r[0]), float(base_l[1]) - float(base_r[1])) < 0.08:
        return None
    return [base_l, tip, base_r]


def _poly_perimeter_mm(poly: list[tuple[float, float]]) -> float:
    if len(poly) < 2:
        return 0.0
    total = 0.0
    for idx in range(1, len(poly)):
        x0, y0 = poly[idx - 1]
        x1, y1 = poly[idx]
        total += math.hypot(float(x1) - float(x0), float(y1) - float(y0))
    return float(total)


def _point_segment_distance_mm(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    vx = float(bx) - float(ax)
    vy = float(by) - float(ay)
    wx = float(px) - float(ax)
    wy = float(py) - float(ay)
    seg2 = (vx * vx) + (vy * vy)
    if seg2 <= 1e-9:
        return math.hypot(float(px) - float(ax), float(py) - float(ay))
    t = max(0.0, min(1.0, ((wx * vx) + (wy * vy)) / seg2))
    proj_x = float(ax) + (t * vx)
    proj_y = float(ay) + (t * vy)
    return math.hypot(float(px) - proj_x, float(py) - proj_y)


def _is_compact_technical_marker_candidate(poly: list[tuple[float, float]]) -> bool:
    if len(poly) < 8 or not _poly_is_closed_mm(poly):
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    w = float(x1 - x0)
    h = float(y1 - y0)
    if w < float(_TECH_POINT_MARKER_MIN_MM) or h < float(_TECH_POINT_MARKER_MIN_MM):
        return False
    if w > float(_TECH_POINT_MARKER_MAX_W_MM) or h > float(_TECH_POINT_MARKER_MAX_H_MM):
        return False
    aspect = max(w, h) / max(1e-9, min(w, h))
    if aspect > float(_TECH_POINT_MARKER_MAX_ASPECT):
        return False
    if _poly_perimeter_mm(poly) > float(_TECH_POINT_MARKER_MAX_PERIM_MM):
        return False
    return True


def _count_marker_supports(
    center_x: float,
    center_y: float,
    polys_mm: list[list[tuple[float, float]]],
    *,
    skip_idx: int,
    support_dist_mm: float = _TECH_POINT_MARKER_SUPPORT_DIST_MM,
) -> int:
    supports = 0
    r = float(support_dist_mm)
    for idx, poly in enumerate(polys_mm):
        if idx == int(skip_idx) or len(poly) < 2:
            continue
        bx0, by0, bx1, by1 = _poly_bbox_mm(poly)
        if (center_x + r) < float(bx0) or (center_x - r) > float(bx1) or (center_y + r) < float(by0) or (center_y - r) > float(by1):
            continue
        if _poly_perimeter_mm(poly) < float(_TECH_POINT_MARKER_SUPPORT_LINE_MIN_MM):
            continue
        best = None
        for seg_idx in range(1, len(poly)):
            ax, ay = poly[seg_idx - 1]
            bx, by = poly[seg_idx]
            dist = _point_segment_distance_mm(center_x, center_y, ax, ay, bx, by)
            if best is None or dist < best:
                best = dist
                if dist <= r:
                    break
        if best is not None and best <= r:
            supports += 1
            if supports >= 3:
                break
    return int(supports)


def _normalize_technical_point_boxes(
    polys_mm: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
    logger=None,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    out: list[list[tuple[float, float]]] = []
    replaced = 0
    replaced_centers: list[tuple[float, float]] = []
    compact_signature_counts: dict[tuple[int, int, int], int] = {}
    candidate_info: dict[int, tuple[float, float, tuple[int, int, int]]] = {}
    for idx, poly in enumerate(polys_mm):
        if not _is_compact_technical_marker_candidate(poly):
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        sig = (len(poly), int(round((x1 - x0) * 10.0)), int(round((y1 - y0) * 10.0)))
        compact_signature_counts[sig] = compact_signature_counts.get(sig, 0) + 1
        candidate_info[idx] = (((x0 + x1) * 0.5), ((y0 + y1) * 0.5), sig)

    for idx, poly in enumerate(polys_mm):
        is_detail = _is_detail_polyline_mm(
            poly,
            page_w_mm=float(page_w_mm),
            page_h_mm=float(page_h_mm),
            crop_left_mm=float(getattr(backend, "PAGE_MARGIN_LEFT_MM", 0.0)),
            crop_right_mm=float(getattr(backend, "PAGE_MARGIN_RIGHT_MM", 0.0)),
            crop_top_mm=float(getattr(backend, "PAGE_MARGIN_TOP_MM", 0.0)),
            crop_bottom_mm=float(getattr(backend, "PAGE_MARGIN_BOTTOM_MM", 0.0)),
        )
        if _is_technical_point_box_poly(poly) and is_detail:
            cx, cy = _technical_point_box_center_mm(poly)
            if any(
                math.hypot(float(cx) - float(px), float(cy) - float(py)) <= float(_TECH_POINT_BOX_DUPLICATE_CENTER_EPS_MM)
                for px, py in replaced_centers
            ):
                replaced += 1
                continue
            out.append(_technical_point_dot_poly_from_box(poly))
            replaced_centers.append((float(cx), float(cy)))
            replaced += 1
            continue
        if _is_technical_point_box_poly(poly, max_mm=float(_TECH_POINT_BOX_EXTENDED_MAX_MM)) and is_detail:
            cx, cy = _technical_point_box_center_mm(poly)
            supports = _count_marker_supports(float(cx), float(cy), polys_mm, skip_idx=idx)
            if supports >= 1:
                bx0, by0, bx1, by1 = _poly_bbox_mm(poly)
                bw = float(bx1 - bx0)
                bh = float(by1 - by0)
                aspect = max(float(bw), float(bh)) / max(1e-9, min(float(bw), float(bh)))
                if any(
                    math.hypot(float(cx) - float(px), float(cy) - float(py)) <= float(_TECH_POINT_BOX_DUPLICATE_CENTER_EPS_MM)
                    for px, py in replaced_centers
                ):
                    replaced += 1
                    continue
                if aspect > float(_TECH_POINT_BOX_MAX_ASPECT):
                    replaced += 1
                    continue
                out.append(_technical_point_dot_poly_from_box(poly))
                replaced_centers.append((float(cx), float(cy)))
                replaced += 1
                continue
        if _is_small_arrow_bbox_artifact_poly(poly):
            cx, cy = _technical_point_box_center_mm(poly)
            supports = _count_marker_supports(float(cx), float(cy), polys_mm, skip_idx=idx)
            if supports >= int(_TECH_ARROW_BBOX_ARTIFACT_SUPPORTS_MIN):
                replaced += 1
                continue
        arrow_v = _compact_arrowhead_v_polyline_mm(poly)
        if arrow_v is not None and is_detail:
            cx, cy = _technical_point_box_center_mm(poly)
            supports = _count_marker_supports(float(cx), float(cy), polys_mm, skip_idx=idx)
            if supports >= 1:
                out.append(arrow_v)
                replaced += 1
                continue
        if idx in candidate_info and is_detail:
            center_x, center_y, sig = candidate_info[idx]
            repeated = int(compact_signature_counts.get(sig, 0)) >= int(_TECH_POINT_MARKER_REPEAT_MIN)
            supports = _count_marker_supports(center_x, center_y, polys_mm, skip_idx=idx)
            if repeated and supports >= 1:
                out.append(_technical_point_dot_poly_from_box(poly))
                replaced += 1
                continue
            if supports >= 2:
                out.append(_technical_point_dot_poly_from_box(poly))
                replaced += 1
                continue
        out.append(poly)
    if replaced and logger is not None:
        logger(f"Technical point marker normalization: replaced {replaced} point-marker loop(s) with compact dot markers.")
    return out, {"point_boxes_replaced": float(replaced)}


def _detect_a4_title_box_mm(
    polys_mm: list[list[tuple[float, float]]],
    detail_flags: list[bool],
    *,
    src_x0: float,
    src_y0: float,
) -> dict[str, float]:
    candidates: list[tuple[float, float, float, float, float, float]] = []
    for poly, _is_detail in zip(polys_mm, detail_flags):
        if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly):
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if x0 > (float(src_x0) + 1.5) or y0 > (float(src_y0) + 1.5):
            continue
        if x1 > (float(src_x0) + 105.0) or y1 > (float(src_y0) + 35.0):
            continue
        if bw < 45.0 or bw > 90.0 or bh < 8.0 or bh > 24.0:
            continue
        candidates.append((bw, bh, x0, y0, x1, y1))
    if not candidates:
        return {}

    _bw, _bh, x0, y0, x1, y1 = max(candidates, key=lambda row: (row[0], row[1]))
    title_text_bottom = 0.0
    for poly, is_detail in zip(polys_mm, detail_flags):
        if not is_detail or len(poly) < 2:
            continue
        px0, py0, px1, py1 = _poly_bbox_mm(poly)
        if px0 < (float(src_x0) - 0.5) or px1 > (float(x1) + 2.0):
            continue
        if py0 < (float(src_y0) - 1.0) or py1 > (float(src_y0) + 26.0):
            continue
        title_text_bottom = max(float(title_text_bottom), float(py1 - src_y0))

    source_h = float(y1 - y0)
    padded_h = max(source_h, float(title_text_bottom) + 7.5)
    target_h = min(max(source_h, padded_h), source_h * 1.85)
    return {
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
        "w": float(x1 - src_x0),
        "source_h": float(source_h),
        "target_h": float(target_h),
        "text_bottom": float(title_text_bottom),
    }


def _is_a4_header_content_poly_mm(
    poly: list[tuple[float, float]],
    *,
    src_x0: float,
    src_y0: float,
) -> bool:
    if len(poly) < 2:
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    bw = float(x1 - x0)
    bh = float(y1 - y0)
    if x0 < (float(src_x0) - 1.0) or y0 < (float(src_y0) - 1.0):
        return False
    if y1 > (float(src_y0) + float(_A4_HEADER_CONTENT_MAX_Y_MM)):
        return False
    if max(bw, bh) <= 0.0:
        return False
    # Ignore long, almost-zero-thickness frame/header separators. These belong to
    # the A4 frame fit and should not participate in the thumbnail/text retarget.
    if _poly_is_axis_aligned_mm(poly, eps=0.18) and min(bw, bh) <= 0.40 and max(bw, bh) >= 18.0:
        return False
    if bw > float(_A4_HEADER_CONTENT_MAX_W_MM) or bh > float(_A4_HEADER_CONTENT_MAX_H_MM):
        return False
    if _polyline_length(poly) > float(_A4_HEADER_CONTENT_MAX_PERIM_MM):
        return False
    return True


def _detect_a4_header_thumb_divider_x_mm(
    polys_mm: list[list[tuple[float, float]]],
    *,
    src_x0: float,
    src_y0: float,
) -> float:
    candidates: list[float] = []
    for poly in polys_mm:
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        if x1 > (float(src_x0) + float(_A4_HEADER_THUMB_DIVIDER_MAX_X_MM)):
            continue
        if y0 < (float(src_y0) - 1.0) or y1 > (float(src_y0) + float(_A4_HEADER_CONTENT_MAX_Y_MM)):
            continue
        if bw > float(_A4_HEADER_THUMB_DIVIDER_MAX_W_MM) or bh < float(_A4_HEADER_THUMB_DIVIDER_MIN_H_MM):
            continue
        candidates.append((float(x0) + float(x1)) * 0.5)
    if not candidates:
        return 0.0
    return float(max(candidates) - float(src_x0))


def _compute_a4_header_thumb_content_scale_x(
    polys_mm: list[list[tuple[float, float]]],
    *,
    src_x0: float,
    src_y0: float,
    header_text_src_x0: float,
    header_thumb_target_w_mm: float,
    default_scale_x: float,
    right_pad_mm: float = 1.0,
) -> float:
    max_rel_x1 = 0.0
    for poly in polys_mm:
        if not _is_a4_header_content_poly_mm(poly, src_x0=src_x0, src_y0=src_y0):
            continue
        if _header_text_poly_candidate_mm(
            poly,
            src_x0=src_x0,
            src_y0=src_y0,
            header_text_src_x0=header_text_src_x0,
        ):
            continue
        _x0, _y0, x1, _y1 = _poly_bbox_mm(poly)
        max_rel_x1 = max(max_rel_x1, float(x1) - float(src_x0))

    if max_rel_x1 <= 0.0:
        return float(default_scale_x)

    fit_width = max(1.0, float(header_thumb_target_w_mm) - float(right_pad_mm))
    fit_scale = float(fit_width) / float(max_rel_x1)
    return float(min(float(default_scale_x), float(fit_scale)))


def _is_a4_header_thumb_frame_poly_mm(
    poly: list[tuple[float, float]],
    *,
    src_x0: float,
    src_y0: float,
    header_thumb_divider_x: float,
) -> bool:
    if len(poly) < 2 or not _poly_is_axis_aligned_mm(poly, eps=0.18):
        return False
    x0, y0, x1, y1 = _poly_bbox_mm(poly)
    bw = float(x1 - x0)
    bh = float(y1 - y0)
    if max(bw, bh) <= 0.0 or min(bw, bh) > 0.75:
        return False
    divider_abs_x = float(src_x0) + float(header_thumb_divider_x)
    if bw <= 0.85 and bh >= 10.0:
        center_x = (float(x0) + float(x1)) * 0.5
        return abs(center_x - float(src_x0)) <= 1.2 or abs(center_x - float(divider_abs_x)) <= 1.2
    if bh <= 0.85 and bw >= max(8.0, float(header_thumb_divider_x) * 0.60):
        return float(x0) <= (float(src_x0) + 1.2) and float(x1) >= (float(divider_abs_x) - 1.2)
    return False


def _strip_a4_header_thumb_source_content_polys(
    polys_mm: list[list[tuple[float, float]]],
    *,
    src_x0: float,
    src_y0: float,
    header_thumb_divider_x: float,
    header_text_src_x0: float,
) -> tuple[list[list[tuple[float, float]]], int]:
    if not polys_mm or header_thumb_divider_x <= 0.0 or header_text_src_x0 <= 0.0:
        return list(polys_mm), 0
    thumb_limit_abs_x = float(src_x0) + float(header_text_src_x0) + 1.0
    thumb_soft_limit_abs_x = float(thumb_limit_abs_x) + 8.0
    kept: list[list[tuple[float, float]]] = []
    removed = 0
    for poly in polys_mm:
        if not _is_a4_header_content_poly_mm(poly, src_x0=float(src_x0), src_y0=float(src_y0)):
            kept.append(poly)
            continue
        if _is_a4_header_thumb_frame_poly_mm(
            poly,
            src_x0=float(src_x0),
            src_y0=float(src_y0),
            header_thumb_divider_x=float(header_thumb_divider_x),
        ):
            kept.append(poly)
            continue
        _px0, _py0, px1, _py1 = _poly_bbox_mm(poly)
        px0, _py0, px1, _py1 = _poly_bbox_mm(poly)
        if float(px1) <= float(thumb_limit_abs_x) or (
            float(px0) < float(thumb_limit_abs_x) and float(px1) <= float(thumb_soft_limit_abs_x)
        ):
            removed += 1
            continue
        kept.append(poly)
    return kept, removed


def _fit_a4_header_thumb_overlay_polys(
    polys_mm: list[list[tuple[float, float]]],
    *,
    header_thumb_target_w_mm: float,
    header_band_h_mm: float,
    target_w_mm: float,
    target_h_mm: float,
    inset_x_mm: float = 2.5,
    inset_y_mm: float = 2.5,
) -> list[list[tuple[float, float]]]:
    if not polys_mm:
        return []
    ox0, oy0, ox1, oy1 = _polys_bbox_mm(polys_mm)
    src_w = max(1e-9, float(ox1 - ox0))
    src_h = max(1e-9, float(oy1 - oy0))
    avail_w = max(1e-9, float(header_thumb_target_w_mm) - 2.0 * float(inset_x_mm))
    avail_h = max(1e-9, float(header_band_h_mm) - 2.0 * float(inset_y_mm))
    scale = min(float(avail_w) / float(src_w), float(avail_h) / float(src_h))
    scaled_h = float(src_h) * float(scale)
    base_x = float(inset_x_mm)
    base_y = float(inset_y_mm) + max(0.0, (float(avail_h) - float(scaled_h)) * 0.5)

    transformed: list[list[tuple[float, float]]] = []
    for poly in polys_mm:
        if len(poly) < 2:
            continue
        out_poly: list[tuple[float, float]] = []
        for x, y in poly:
            nx = float(base_x) + ((float(x) - float(ox0)) * float(scale))
            ny = float(base_y) + ((float(y) - float(oy0)) * float(scale))
            nx = max(0.0, min(float(target_w_mm), nx))
            ny = max(0.0, min(float(target_h_mm), ny))
            out_poly.append((nx, ny))
        if len(out_poly) >= 2:
            transformed.append(out_poly)
    return transformed


def _compose_a4_hybrid_frame_polylines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
    target_w_mm: float,
    target_h_mm: float,
    extra_frame_polys: list[list[tuple[float, float]]] | None = None,
    header_thumb_target_min_w_mm: float = _A4_HEADER_THUMB_TARGET_MIN_W_MM,
    header_text_gap_mm: float = _A4_HEADER_TEXT_GAP_MM,
    header_text_scale_x: float = _A4_HEADER_TEXT_SCALE,
    header_text_src_min_x_mm: float = _A4_HEADER_TEXT_SRC_MIN_X_MM,
    header_text_src_pad_mm: float = _A4_HEADER_TEXT_SRC_PAD_MM,
    header_thumb_content_scale_x: float | None = None,
    fit_thumb_overlay_to_box: bool = False,
    preserve_header_band_layout: bool = False,
) -> tuple[list[list[tuple[float, float]]], dict[str, float]]:
    if not polys_mm:
        return [], {}

    xs = [float(x) for poly in polys_mm for x, _y in poly]
    ys = [float(y) for poly in polys_mm for _x, y in poly]
    src_x0 = min(xs)
    src_x1 = max(xs)
    src_y0 = min(ys)
    src_y1 = max(ys)
    src_w = max(1e-9, src_x1 - src_x0)
    src_h = max(1e-9, src_y1 - src_y0)
    frame_scale_x = float(target_w_mm) / float(src_w)
    frame_scale_y = float(target_h_mm) / float(src_h)
    if preserve_header_band_layout:
        header_scale_x = min(float(target_w_mm) / max(1e-9, float(page_w_mm)), 1.0)
        header_scale_y = min(float(target_h_mm) / max(1e-9, float(page_h_mm)), 1.0)
    else:
        header_scale_x = min(float(frame_scale_x), 1.0)
        header_scale_y = min(float(frame_scale_y), 1.0)
    header_thumb_divider_x = _detect_a4_header_thumb_divider_x_mm(
        polys_mm,
        src_x0=float(src_x0),
        src_y0=float(src_y0),
    )
    header_thumb_target_w = 0.0
    header_thumb_scale_x = float(header_scale_x)
    header_thumb_content_scale_x = float(header_scale_x if header_thumb_content_scale_x is None else header_thumb_content_scale_x)
    header_text_src_x0 = 0.0
    header_text_dst_x0 = 0.0
    header_text_scale_x = float(header_text_scale_x)
    header_text_scale_y = 1.0

    detail_flags: list[bool] = []
    for poly in polys_mm:
        detail_flags.append(
            _is_detail_polyline_mm(
                poly,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
                crop_left_mm=float(getattr(backend, "PAGE_MARGIN_LEFT_MM", 0.0)),
                crop_right_mm=float(getattr(backend, "PAGE_MARGIN_RIGHT_MM", 0.0)),
                crop_top_mm=float(getattr(backend, "PAGE_MARGIN_TOP_MM", 0.0)),
                crop_bottom_mm=float(getattr(backend, "PAGE_MARGIN_BOTTOM_MM", 0.0)),
            )
        )
    title_box = _detect_a4_title_box_mm(
        polys_mm,
        detail_flags,
        src_x0=float(src_x0),
        src_y0=float(src_y0),
    )
    if extra_frame_polys:
        title_box = {}
    if header_thumb_divider_x > 0.0:
        header_text_src_x0 = max(float(header_thumb_divider_x) + float(header_text_src_pad_mm), float(header_text_src_min_x_mm))
        if preserve_header_band_layout:
            header_thumb_target_w = float(header_thumb_divider_x) * float(header_scale_x)
            header_thumb_scale_x = float(header_scale_x)
            header_text_dst_x0 = float(header_text_src_x0) * float(header_scale_x)
            header_text_scale_x = float(header_scale_x)
        else:
            header_thumb_target_w = max(
                float(header_thumb_divider_x) * float(frame_scale_x),
                float(header_thumb_target_min_w_mm),
            )
            header_thumb_scale_x = float(header_thumb_target_w) / max(1e-9, float(header_thumb_divider_x))
            header_text_dst_x0 = float(header_thumb_target_w) + float(header_text_gap_mm)

    transformed: list[list[tuple[float, float]]] = []
    detail_paths = 0
    frame_paths = 0
    header_content_paths = 0
    header_text_paths = 0
    detail_pts: list[tuple[float, float]] = []
    removed_title_box_paths = 0

    for poly, is_detail in zip(polys_mm, detail_flags):
        px0, py0, px1, py1 = _poly_bbox_mm(poly)
        if title_box and _poly_is_axis_aligned_mm(poly):
            x0, y0, x1, y1 = px0, py0, px1, py1
            bw = float(x1 - x0)
            bh = float(y1 - y0)
            title_w = float(title_box["w"])
            title_h = float(title_box["source_h"])
            if (
                x0 >= (float(src_x0) - 1.0)
                and x1 <= (float(title_box["x1"]) + 2.0)
                and y0 >= (float(src_y0) - 1.0)
                and y1 <= (float(src_y0) + 35.0)
                and (
                    (bw >= (title_w * 0.55) and bh <= (title_h + 4.0))
                    or (bh >= (title_h * 0.55) and bw <= (title_w + 4.0))
                )
            ):
                removed_title_box_paths += 1
                continue
        use_header_scale = _is_a4_header_content_poly_mm(
            poly,
            src_x0=float(src_x0),
            src_y0=float(src_y0),
        )
        header_region = ""
        if not use_header_scale and header_thumb_divider_x > 0.0:
            if _is_a4_header_thumb_frame_poly_mm(
                poly,
                src_x0=float(src_x0),
                src_y0=float(src_y0),
                header_thumb_divider_x=float(header_thumb_divider_x),
            ):
                use_header_scale = True
                if not preserve_header_band_layout:
                    header_region = "thumb_frame"
        if use_header_scale and header_thumb_divider_x > 0.0 and not header_region and not preserve_header_band_layout:
            rel_x0 = float(px0) - float(src_x0)
            rel_x1 = float(px1) - float(src_x0)
            if rel_x1 >= (float(header_text_src_x0) + 1.5):
                header_region = "text"
            elif rel_x1 <= max(float(header_text_src_x0) - 1.0, float(header_thumb_divider_x) + 2.0):
                header_region = (
                    "thumb_frame"
                    if _is_a4_header_thumb_frame_poly_mm(
                        poly,
                        src_x0=float(src_x0),
                        src_y0=float(src_y0),
                        header_thumb_divider_x=float(header_thumb_divider_x),
                    )
                    else "thumb"
                )
        out_poly: list[tuple[float, float]] = []
        for x, y in poly:
            if header_region == "text":
                nx = float(header_text_dst_x0) + ((float(x) - float(src_x0) - float(header_text_src_x0)) * float(header_text_scale_x))
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
            elif header_region == "thumb_frame":
                nx = (float(x) - float(src_x0)) * float(header_thumb_scale_x)
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
            elif header_region == "thumb":
                nx = (float(x) - float(src_x0)) * float(header_thumb_content_scale_x)
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
            elif use_header_scale and preserve_header_band_layout:
                nx = float(x) * float(header_scale_x)
                ny = float(y) * float(header_scale_y)
            elif use_header_scale:
                nx = (float(x) - float(src_x0)) * float(header_scale_x)
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
            elif is_detail:
                nx = float(x) - float(src_x0)
                ny = float(y) - float(src_y0)
            else:
                nx = (float(x) - float(src_x0)) * float(frame_scale_x)
                ny = (float(y) - float(src_y0)) * float(frame_scale_y)
            nx = max(0.0, min(float(target_w_mm), nx))
            ny = max(0.0, min(float(target_h_mm), ny))
            out_poly.append((nx, ny))
            if is_detail:
                detail_pts.append((nx, ny))
        if len(out_poly) < 2:
            continue
        transformed.append(out_poly)
        if is_detail and not use_header_scale:
            detail_paths += 1
        else:
            frame_paths += 1
            if use_header_scale:
                header_content_paths += 1
                if header_region == "text":
                    header_text_paths += 1

    if title_box:
        transformed.append(
            [
                (0.0, float(title_box["target_h"])),
                (float(title_box["w"]), float(title_box["target_h"])),
                (float(title_box["w"]), 0.0),
            ]
        )
        frame_paths += 1

    if fit_thumb_overlay_to_box and extra_frame_polys:
        fitted_overlay_polys = _fit_a4_header_thumb_overlay_polys(
            list(extra_frame_polys),
            header_thumb_target_w_mm=float(header_thumb_target_w or header_thumb_target_min_w_mm),
            header_band_h_mm=float(_A4_HEADER_CONTENT_MAX_Y_MM) * float(header_scale_y),
            target_w_mm=float(target_w_mm),
            target_h_mm=float(target_h_mm),
        )
        transformed.extend(fitted_overlay_polys)
        frame_paths += len(fitted_overlay_polys)
        header_content_paths += len(fitted_overlay_polys)
    else:
        left_overlay_polys: list[list[tuple[float, float]]] = []
        thumb_overlay_polys: list[list[tuple[float, float]]] = []
        regular_overlay_polys: list[list[tuple[float, float]]] = []
        for poly in list(extra_frame_polys or []):
            if len(poly) < 2:
                continue
            px0, _py0, px1, _py1 = _poly_bbox_mm(poly)
            if float(px1) <= (float(src_x0) + 1.0):
                left_overlay_polys.append(poly)
            elif header_thumb_divider_x > 0.0 and float(px1) <= (
                float(src_x0) + max(float(header_text_src_x0) - 1.0, float(header_thumb_divider_x) + 2.0)
            ):
                thumb_overlay_polys.append(poly)
            else:
                regular_overlay_polys.append(poly)

        left_origin_x = float(src_x0)
        left_origin_y = float(src_y0)
        if left_overlay_polys:
            left_origin_x = min(float(x) for poly in left_overlay_polys for x, _y in poly)
            left_origin_y = min(float(y) for poly in left_overlay_polys for _x, y in poly)

        for poly in left_overlay_polys:
            if len(poly) < 2:
                continue
            out_poly: list[tuple[float, float]] = []
            for x, y in poly:
                nx = (float(x) - float(left_origin_x)) * float(header_scale_x)
                ny = (float(y) - float(left_origin_y)) * float(header_scale_y)
                nx = max(0.0, min(float(target_w_mm), nx))
                ny = max(0.0, min(float(target_h_mm), ny))
                out_poly.append((nx, ny))
            if len(out_poly) < 2:
                continue
            transformed.append(out_poly)
            frame_paths += 1
            header_content_paths += 1

        for poly in thumb_overlay_polys:
            if len(poly) < 2:
                continue
            out_poly: list[tuple[float, float]] = []
            for x, y in poly:
                nx = (float(x) - float(src_x0)) * float(header_thumb_content_scale_x)
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
                nx = max(0.0, min(float(target_w_mm), nx))
                ny = max(0.0, min(float(target_h_mm), ny))
                out_poly.append((nx, ny))
            if len(out_poly) < 2:
                continue
            transformed.append(out_poly)
            frame_paths += 1
            header_content_paths += 1

        for poly in regular_overlay_polys:
            if len(poly) < 2:
                continue
            out_poly: list[tuple[float, float]] = []
            for x, y in poly:
                nx = (float(x) - float(src_x0)) * float(header_scale_x)
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
                nx = max(0.0, min(float(target_w_mm), nx))
                ny = max(0.0, min(float(target_h_mm), ny))
                out_poly.append((nx, ny))
            if len(out_poly) < 2:
                continue
            transformed.append(out_poly)
            frame_paths += 1
            header_content_paths += 1

    info: dict[str, float] = {
        "src_x0": float(src_x0),
        "src_x1": float(src_x1),
        "src_y0": float(src_y0),
        "src_y1": float(src_y1),
        "src_w": float(src_w),
        "src_h": float(src_h),
        "frame_scale_x": float(frame_scale_x),
        "frame_scale_y": float(frame_scale_y),
        "header_scale_x": float(header_scale_x),
        "header_scale_y": float(header_scale_y),
        "detail_scale": 1.0,
        "detail_paths": float(detail_paths),
        "frame_paths": float(frame_paths),
        "header_content_paths": float(header_content_paths),
        "header_text_paths": float(header_text_paths),
        "title_box_removed_paths": float(removed_title_box_paths),
    }
    if header_thumb_divider_x > 0.0 and header_text_src_x0 > 0.0:
        info.update(
            {
                "header_thumb_divider_x": float(header_thumb_divider_x),
                "header_thumb_target_w": float(header_thumb_target_w),
                "header_thumb_scale_x": float(header_thumb_scale_x),
                "header_thumb_content_scale_x": float(header_thumb_content_scale_x),
                "header_text_src_x0": float(header_text_src_x0),
                "header_text_dst_x0": float(header_text_dst_x0),
                "header_text_scale_x": float(header_text_scale_x),
                "header_text_scale_y": float(header_text_scale_y),
            }
        )
    if title_box:
        info.update(
            {
                "title_box_w": float(title_box["w"]),
                "title_box_source_h": float(title_box["source_h"]),
                "title_box_target_h": float(title_box["target_h"]),
                "title_box_text_bottom": float(title_box["text_bottom"]),
            }
        )
    if detail_pts:
        dxs = [p[0] for p in detail_pts]
        dys = [p[1] for p in detail_pts]
        info.update(
            {
                "detail_x0": float(min(dxs)),
                "detail_x1": float(max(dxs)),
                "detail_y0": float(min(dys)),
                "detail_y1": float(max(dys)),
                "detail_w": float(max(dxs) - min(dxs)),
                "detail_h": float(max(dys) - min(dys)),
            }
        )
    return transformed, info


def _run_hybrid_svg_to_gcode(
    *,
    input_svg: Path,
    output_nc: Path,
    logs: list[str],
) -> tuple[bool, str]:
    _configure_drawing_method3_backend()
    prev_state = {
        "EMIT_ARCS": bool(getattr(backend, "EMIT_ARCS", True)),
        "PENCIL_NATURAL_STROKES_ENABLED": bool(getattr(backend, "PENCIL_NATURAL_STROKES_ENABLED", True)),
        "PAGE_MARGIN_ENABLED": bool(getattr(backend, "PAGE_MARGIN_ENABLED", True)),
        "HANDWRITING_TEXT_ENABLED": bool(getattr(backend, "HANDWRITING_TEXT_ENABLED", False)),
        "HANDWRITING_STITCH_EPS_MM": float(getattr(backend, "HANDWRITING_STITCH_EPS_MM", 0.22)),
        "HANDWRITING_STITCH_GAP_EPS_MM": float(getattr(backend, "HANDWRITING_STITCH_GAP_EPS_MM", 0.38)),
        "HANDWRITING_STITCH_GAP_MAX_ANGLE_DEG": float(getattr(backend, "HANDWRITING_STITCH_GAP_MAX_ANGLE_DEG", 40.0)),
        "EXACT_GEOMETRY_MODE": bool(getattr(backend, "EXACT_GEOMETRY_MODE", False)),
    }
    try:
        setattr(backend, "EXACT_GEOMETRY_MODE", True)
        setattr(backend, "EMIT_ARCS", False)
        setattr(backend, "PENCIL_NATURAL_STROKES_ENABLED", False)
        setattr(backend, "PAGE_MARGIN_ENABLED", False)
        setattr(backend, "HANDWRITING_TEXT_ENABLED", False)
        setattr(backend, "HANDWRITING_STITCH_EPS_MM", min(prev_state["HANDWRITING_STITCH_EPS_MM"], 0.03))
        setattr(backend, "HANDWRITING_STITCH_GAP_EPS_MM", min(prev_state["HANDWRITING_STITCH_GAP_EPS_MM"], 0.03))
        setattr(backend, "HANDWRITING_STITCH_GAP_MAX_ANGLE_DEG", min(prev_state["HANDWRITING_STITCH_GAP_MAX_ANGLE_DEG"], 14.0))
        with _technical_drawing_backend_precision():
            return backend.run_pipeline(input_svg, logs.append, send_to_plotter=False, output_path=output_nc)
    finally:
        for key, value in prev_state.items():
            setattr(backend, key, value)


def _prepare_a4_hybrid_drawing_candidate(
    source_pdf: Path,
    *,
    variant_name: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    bridge = BackendBridge(PROJECT_ROOT)
    logs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="plotter_a4_hybrid_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        shutil.copy2(source_pdf, ascii_pdf)
        preserve_variant1_header_source = _preserve_nachert_header_source_for_variant(source_pdf)
        variant1_header_cleanup = False

        work_w_mm, work_h_mm = _configure_drawing_method3_backend()
        source_svg = td_path / "method3_source.svg"
        source_preview_pdf = td_path / "method3_source.pdf"
        with _technical_drawing_backend_precision():
            with _preserve_nachert_variant1_header_context(bridge, preserve_variant1_header_source):
                ok, msg = bridge._prepare_method3_page(
                    backend=backend,
                    input_path=ascii_pdf,
                    source_page_index=1,
                    body_font="Marck Script",
                    formula_font="Times New Roman",
                    output_svg=source_svg,
                    output_pdf=source_preview_pdf,
                    output_nc=None,
                    log=logs.append,
                    source_pdf_path=ascii_pdf,
                    source_page_count=1,
                )
        if not ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        if preserve_variant1_header_source:
            extra_frame_polys, recovered = [], []
        else:
            extra_frame_polys, recovered = _extract_small_condition_image_polylines_from_pdf(
                ascii_pdf,
                page_index=0,
                logger=logs.append,
            )
        recovery_meta = {
            "image_count": float(len(recovered)),
            "path_count": float(len(extra_frame_polys)),
        }
        if extra_frame_polys:
            logs.append(
                "Condition image recovery summary: "
                f"{len(recovered)} image(s), {len(extra_frame_polys)} path(s) staged as frame overlay."
            )

        with fitz.open(ascii_pdf) as doc:
            page = doc[0]
            page_w_mm = float(page.rect.width) * 25.4 / 72.0
            page_h_mm = float(page.rect.height) * 25.4 / 72.0
        header_text_lines = _extract_a4_header_text_lines_from_pdf(ascii_pdf, page_index=0)
        prefer_source_header_text = bool(preserve_variant1_header_source)
        preserve_header_band_layout = bool(preserve_variant1_header_source)
        if header_text_lines:
            logs.append(f"A4 header text extraction: {len(header_text_lines)} line(s) from PDF text blocks.")

        source_polys = _parse_method3_svg_polylines(source_svg)
        if not source_polys:
            return {
                "variant": variant_name,
                "ok": False,
                "message": "Method3 source SVG produced no polylines.",
                "logs": logs,
            }
        if _is_nachert_variant4_source(source_pdf):
            source_polys.append(
                [
                    (0.0, 0.0),
                    (float(page_w_mm), 0.0),
                    (float(page_w_mm), float(page_h_mm)),
                    (0.0, float(page_h_mm)),
                    (0.0, 0.0),
                ]
            )
            logs.append("Nachert variant 4 outer frame restore: appended full source-page border polyline.")
        source_polys, point_box_meta = _normalize_technical_point_boxes(
            source_polys,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
            logger=logs.append,
        )
        title_block_meta = {
            "title_block_text_lines": 0.0,
            "title_block_text_removed": 0.0,
            "title_block_text_rendered": 0.0,
        }
        clean_reference_polys = list(source_polys)
        if extra_frame_polys:
            clean_reference_polys.extend(list(extra_frame_polys))
        clean_reference_svg = candidate_dir / f"{variant_name}__method3_source.svg"
        clean_reference_pdf = candidate_dir / f"{variant_name}__method3_source.pdf"
        clean_reference_polys, clean_reference_meta = _center_polylines_on_page_x(
            clean_reference_polys,
            page_w_mm=page_w_mm,
        )
        logs.append(
            "A4 clean source centered on page X: "
            f"offset_x={float(clean_reference_meta.get('offset_x_mm', 0.0)):.3f} mm"
        )
        bridge._write_method3_svg(
            clean_reference_svg,
            clean_reference_polys,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
        )
        _render_polylines_pdf(
            polylines=clean_reference_polys,
            out_pdf=clean_reference_pdf,
            canvas_bounds_mm=(0.0, page_w_mm, 0.0, page_h_mm),
        )
        xs = [float(x) for poly in source_polys for x, _y in poly]
        ys = [float(y) for poly in source_polys for _x, y in poly]
        src_x0 = min(xs)
        src_x1 = max(xs)
        src_y0 = min(ys)
        src_y1 = max(ys)
        frame_scale_x = float(work_w_mm) / max(1e-9, float(src_x1 - src_x0))
        header_thumb_divider_x = _detect_a4_header_thumb_divider_x_mm(
            source_polys,
            src_x0=float(src_x0),
            src_y0=float(src_y0),
        )
        header_text_src_x0 = 0.0
        if header_thumb_divider_x > 0.0:
            header_text_src_min_x_mm = (
                float(_A4_HEADER_VARIANT1_TEXT_SRC_MIN_X_MM)
                if variant1_header_cleanup
                else float(_A4_HEADER_TEXT_SRC_MIN_X_MM)
            )
            header_text_src_pad_mm = (
                float(_A4_HEADER_VARIANT1_TEXT_SRC_PAD_MM)
                if variant1_header_cleanup
                else float(_A4_HEADER_TEXT_SRC_PAD_MM)
            )
            header_text_src_x0 = max(float(header_thumb_divider_x) + float(header_text_src_pad_mm), float(header_text_src_min_x_mm))
        if variant1_header_cleanup and extra_frame_polys and header_text_src_x0 > 0.0:
            source_polys, removed_thumb_source = _strip_a4_header_thumb_source_content_polys(
                source_polys,
                src_x0=float(src_x0),
                src_y0=float(src_y0),
                header_thumb_divider_x=float(header_thumb_divider_x),
                header_text_src_x0=float(header_text_src_x0),
            )
            if removed_thumb_source:
                logs.append(
                    "A4 header thumb reroute: removed "
                    f"{removed_thumb_source} source polyline(s) from the thumbnail block."
                )
        header_text_source_polys: list[list[tuple[float, float]]] = []
        if (header_text_lines or prefer_source_header_text) and header_text_src_x0 > 0.0:
            filtered_source_polys: list[list[tuple[float, float]]] = []
            removed_header_text_paths = 0
            for poly in source_polys:
                if _header_text_poly_candidate_mm(
                    poly,
                    src_x0=float(src_x0),
                    src_y0=float(src_y0),
                    header_text_src_x0=float(header_text_src_x0),
                ):
                    removed_header_text_paths += 1
                    header_text_source_polys.append(poly)
                    continue
                filtered_source_polys.append(poly)
            if removed_header_text_paths:
                source_polys = filtered_source_polys
                logs.append(
                    "A4 header text reroute: removed "
                    f"{removed_header_text_paths} source polyline(s) from the header text band."
                )

        if preserve_variant1_header_source:
            header_thumb_target_min_w_mm = 0.0
            header_text_gap_mm = 1.0
            header_text_scale_x = _A4_HEADER_TEXT_SCALE
        else:
            header_thumb_target_min_w_mm = _A4_HEADER_VARIANT1_THUMB_TARGET_MIN_W_MM if variant1_header_cleanup else _A4_HEADER_THUMB_TARGET_MIN_W_MM
            header_text_gap_mm = _A4_HEADER_VARIANT1_TEXT_GAP_MM if variant1_header_cleanup else _A4_HEADER_TEXT_GAP_MM
            header_text_scale_x = _A4_HEADER_VARIANT1_TEXT_SCALE if variant1_header_cleanup else _A4_HEADER_TEXT_SCALE
        header_thumb_content_scale_x = None
        if variant1_header_cleanup and header_text_src_x0 > 0.0:
            thumb_content_scale_polys = list(extra_frame_polys or source_polys)
            header_thumb_target_w_guess = max(
                float(header_thumb_divider_x) * float(frame_scale_x),
                float(header_thumb_target_min_w_mm),
            )
            header_thumb_content_scale_x = _compute_a4_header_thumb_content_scale_x(
                thumb_content_scale_polys,
                src_x0=float(src_x0),
                src_y0=float(src_y0),
                header_text_src_x0=float(header_text_src_x0),
                header_thumb_target_w_mm=float(header_thumb_target_w_guess),
                default_scale_x=min(float(frame_scale_x), 1.0),
            )
        hybrid_polys, hybrid_info = _compose_a4_hybrid_frame_polylines(
            source_polys,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
            target_w_mm=work_w_mm,
            target_h_mm=work_h_mm,
            extra_frame_polys=extra_frame_polys,
            header_thumb_target_min_w_mm=float(header_thumb_target_min_w_mm),
            header_text_gap_mm=float(header_text_gap_mm),
            header_text_scale_x=float(header_text_scale_x),
            header_text_src_min_x_mm=float(
                _A4_HEADER_VARIANT1_TEXT_SRC_MIN_X_MM if variant1_header_cleanup else _A4_HEADER_TEXT_SRC_MIN_X_MM
            ),
            header_text_src_pad_mm=float(
                _A4_HEADER_VARIANT1_TEXT_SRC_PAD_MM if variant1_header_cleanup else _A4_HEADER_TEXT_SRC_PAD_MM
            ),
            header_thumb_content_scale_x=header_thumb_content_scale_x,
            fit_thumb_overlay_to_box=bool(variant1_header_cleanup and extra_frame_polys),
            preserve_header_band_layout=preserve_header_band_layout,
        )
        if not hybrid_polys:
            return {
                "variant": variant_name,
                "ok": False,
                "message": "Hybrid A4 frame transform produced no polylines.",
                "logs": logs,
            }
        if (
            header_text_lines
            and not prefer_source_header_text
            and float(hybrid_info.get("header_text_dst_x0", 0.0)) > 0.0
        ):
            cleaned_hybrid_polys: list[list[tuple[float, float]]] = []
            removed_hybrid_text = 0
            trimmed_thumb_spill = 0
            header_thumb_x1 = float(hybrid_info.get("header_thumb_target_w", 0.0))
            top_band_y1 = float(_A4_HEADER_CONTENT_MAX_Y_MM) + 1.5
            remove_x0 = max(
                float(header_thumb_x1) * 0.75,
                float(hybrid_info.get("header_text_dst_x0", 0.0)) - 16.0,
            )
            gutter_x0 = 20.0 if variant1_header_cleanup else max(32.0, float(header_thumb_x1) - 18.0)
            gutter_x1 = float(hybrid_info.get("header_text_dst_x0", 0.0)) + 2.0
            for poly in hybrid_polys:
                if len(poly) < 2:
                    continue
                px0, py0, px1, py1 = _poly_bbox_mm(poly)
                bw = float(px1 - px0)
                bh = float(py1 - py0)
                is_top_band = float(py1) <= float(top_band_y1)
                is_axis_line = _poly_is_axis_aligned_mm(poly, eps=0.18) and min(bw, bh) <= 0.60
                keep_header_frame = False
                if is_top_band and is_axis_line:
                    if bw <= 0.75 and bh >= 12.0:
                        if (
                            abs(float(px0)) <= 0.9
                            or abs(float(px0) - float(header_thumb_x1)) <= 1.6
                            or abs(float(px0) - float(work_w_mm)) <= 0.9
                        ):
                            keep_header_frame = True
                    elif bh <= 0.75 and bw >= 12.0:
                        if (
                            abs(float(py0)) <= 0.9
                            or abs(float(py0) - float(_A4_HEADER_CONTENT_MAX_Y_MM)) <= 1.6
                        ):
                            keep_header_frame = True
                if (
                    is_top_band
                    and float(px0) < (float(header_thumb_x1) - 0.5)
                    and float(px1) > (float(header_thumb_x1) + 0.5)
                    and not keep_header_frame
                ):
                    clipped_thumb_polys = _clip_polyline_max_x_mm(poly, float(header_thumb_x1) - 0.6)
                    if clipped_thumb_polys:
                        cleaned_hybrid_polys.extend(clipped_thumb_polys)
                        trimmed_thumb_spill += 1
                    else:
                        removed_hybrid_text += 1
                    continue
                if (
                    is_top_band
                    and float(px0) >= float(gutter_x0)
                    and float(px1) <= float(gutter_x1)
                    and not keep_header_frame
                ):
                    removed_hybrid_text += 1
                    continue
                if (
                    is_top_band
                    and float(px1) >= float(remove_x0)
                    and not keep_header_frame
                ):
                    removed_hybrid_text += 1
                    continue
                cleaned_hybrid_polys.append(poly)
            if removed_hybrid_text or trimmed_thumb_spill:
                hybrid_polys = cleaned_hybrid_polys
                if removed_hybrid_text:
                    logs.append(
                        "A4 header text cleanup: removed "
                        f"{removed_hybrid_text} transformed polyline(s) before rerender."
                    )
                if trimmed_thumb_spill:
                    logs.append(
                        "A4 header thumb cleanup: clipped "
                        f"{trimmed_thumb_spill} spill polyline(s) to the thumbnail box."
                    )
        if (
            header_text_lines
            and not prefer_source_header_text
            and float(hybrid_info.get("header_text_dst_x0", 0.0)) > 0.0
        ):
            header_text_polys = _render_a4_header_text_polylines(
                header_text_lines,
                src_x0=float(hybrid_info.get("src_x0", src_x0)),
                src_y0=float(hybrid_info.get("src_y0", src_y0)),
                header_scale_y=float(hybrid_info.get("header_scale_y", 1.0)),
                header_text_src_x0=float(hybrid_info.get("header_text_src_x0", header_text_src_x0)),
                header_text_dst_x0=float(hybrid_info.get("header_text_dst_x0", 0.0)),
                header_text_scale_x=float(hybrid_info.get("header_text_scale_x", 1.0)),
                tight_layout=bool(preserve_variant1_header_source),
                logger=logs.append,
            )
            if header_text_polys:
                hybrid_polys.extend(header_text_polys)
                logs.append(
                    "A4 header text reroute: rendered "
                    f"{len(header_text_polys)} polyline(s) from PDF text blocks."
                )
        elif header_text_source_polys and float(hybrid_info.get("header_text_dst_x0", 0.0)) > 0.0:
            header_text_polys = _transform_a4_header_text_source_polylines(
                header_text_source_polys,
                src_x0=float(hybrid_info.get("src_x0", src_x0)),
                src_y0=float(hybrid_info.get("src_y0", src_y0)),
                header_scale_y=float(hybrid_info.get("header_scale_y", 1.0)),
                header_text_src_x0=float(hybrid_info.get("header_text_src_x0", header_text_src_x0)),
                header_text_dst_x0=float(hybrid_info.get("header_text_dst_x0", 0.0)),
                header_text_scale_x=float(hybrid_info.get("header_text_scale_x", 1.0)),
                target_w_mm=float(work_w_mm),
                target_h_mm=float(work_h_mm),
            )
            if header_text_polys:
                hybrid_polys.extend(header_text_polys)
                logs.append(
                    "A4 header text reroute: restored "
                    f"{len(header_text_polys)} transformed source polyline(s)."
                )

        if float(hybrid_info.get("header_text_dst_x0", 0.0)) > 0.0:
            hybrid_polys, removed_gutter_artifacts = _cleanup_a4_header_gutter_artifacts(
                hybrid_polys,
                header_thumb_x1_mm=float(hybrid_info.get("header_thumb_target_w", 0.0)),
                header_text_x0_mm=float(hybrid_info.get("header_text_dst_x0", 0.0)),
                top_band_y1_mm=float(_A4_HEADER_CONTENT_MAX_Y_MM) + 1.5,
            )
            if removed_gutter_artifacts:
                logs.append(
                    "A4 header gutter cleanup: removed "
                    f"{removed_gutter_artifacts} tiny artifact polyline(s) from the thumb/text gap."
                )

        restored_header_separator = False
        if not preserve_variant1_header_source:
            hybrid_polys, restored_header_separator = _ensure_a4_header_bottom_separator(
                hybrid_polys,
                header_lines=header_text_lines,
                src_y0=float(hybrid_info.get("src_y0", src_y0)),
                header_scale_y=float(hybrid_info.get("header_scale_y", 1.0)),
                target_w_mm=float(work_w_mm),
            )
            if restored_header_separator:
                logs.append("A4 header separator restore: added clean bottom separator under the text band.")
                text_bottom_y = 0.0
                for line in header_text_lines:
                    bbox_mm = tuple(line.get("bbox_mm", ()) or ())
                    if len(bbox_mm) < 4:
                        continue
                    text_bottom_y = max(
                        text_bottom_y,
                        (float(bbox_mm[3]) - float(hybrid_info.get("src_y0", src_y0))) * float(hybrid_info.get("header_scale_y", 1.0)),
                    )
                separator_y = min(float(_A4_HEADER_CONTENT_MAX_Y_MM), float(text_bottom_y) + 4.0)
                hybrid_polys, removed_thumb_dup = _remove_a4_header_thumb_full_width_duplicate(
                    hybrid_polys,
                    header_thumb_x1_mm=float(hybrid_info.get("header_text_dst_x0", hybrid_info.get("header_thumb_target_w", 0.0))),
                    separator_y_mm=float(separator_y),
                )
                if removed_thumb_dup:
                    logs.append(
                        "A4 header thumb cleanup: removed "
                        f"{removed_thumb_dup} full-width duplicate line(s) below the thumbnail."
                    )
        else:
            hybrid_polys, removed_header_dup = _dedupe_a4_header_band_axis_lines(
                hybrid_polys,
                top_band_y1_mm=float(_A4_HEADER_CONTENT_MAX_Y_MM) + 2.0,
            )
            if removed_header_dup:
                logs.append(
                    "A4 header cleanup: removed "
                    f"{removed_header_dup} duplicate axis-aligned frame line(s) in the preserved top band."
                )
            hybrid_polys, restored_outer_edges = _ensure_a4_outer_top_right_frame_lines(
                hybrid_polys,
                target_w_mm=float(work_w_mm),
                target_h_mm=float(work_h_mm),
            )
            if restored_outer_edges:
                logs.append(
                    "A4 outer frame restore: added "
                    f"{restored_outer_edges} missing top/right border line(s)."
                )

        prefix = candidate_dir / variant_name
        target_svg = td_path / "hybrid_target.svg"
        bridge._write_method3_svg(target_svg, hybrid_polys, page_w_mm=work_w_mm, page_h_mm=work_h_mm)

        nc_path = prefix.with_suffix(".nc")
        gcode_path = prefix.with_suffix(".gcode")
        svg_path = prefix.with_suffix(".svg")
        pdf_path = prefix.with_suffix(".pdf")

        logs.append("--- hybrid fit: detail=1:1, frame=fit-to-work-area ---")
        ok_nc, msg_nc = _run_hybrid_svg_to_gcode(input_svg=target_svg, output_nc=nc_path, logs=logs)
        if not ok_nc:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg_nc,
                "logs": logs,
            }

        preview_ok, preview_err = _build_sheet_preview_from_gcode(
            gcode_path=nc_path,
            reference_pdf=source_pdf,
            out_svg=svg_path,
            out_pdf=pdf_path,
            logs=logs,
        )
        if not preview_ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": preview_err,
                "logs": logs,
            }

        _copy_file(nc_path, gcode_path)
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(clean_reference_pdf, pdf_path, source_page_index=0)
        notes = (
            "detail_scale=1.0; "
            f"frame_scale_x={float(hybrid_info.get('frame_scale_x', 1.0)):.4f}; "
            f"frame_scale_y={float(hybrid_info.get('frame_scale_y', 1.0)):.4f}; "
            f"header_scale_x={float(hybrid_info.get('header_scale_x', 1.0)):.4f}; "
            f"header_scale_y={float(hybrid_info.get('header_scale_y', 1.0)):.4f}; "
            f"header_content_paths={int(hybrid_info.get('header_content_paths', 0.0))}; "
            f"header_text_paths={int(hybrid_info.get('header_text_paths', 0.0))}; "
            f"header_thumb_target_w={float(hybrid_info.get('header_thumb_target_w', 0.0)):.2f}; "
            f"header_text_scale={float(hybrid_info.get('header_text_scale_x', 1.0)):.4f}; "
            f"detail_bbox={float(hybrid_info.get('detail_w', 0.0)):.2f}x{float(hybrid_info.get('detail_h', 0.0)):.2f} mm; "
            f"condition_images_recovered={int(recovery_meta.get('image_count', 0.0))}; "
            f"point_boxes_replaced={int(point_box_meta.get('point_boxes_replaced', 0.0))}; "
            f"title_block_text_lines={int(title_block_meta.get('title_block_text_lines', 0.0))}; "
            f"title_block_text_rendered={int(title_block_meta.get('title_block_text_rendered', 0.0))}; "
            "left_strip_removed=True; outer_border_removed=True"
        )
        return {
            "variant": variant_name,
            "ok": True,
            "message": msg_nc,
            "logs": logs,
            "fit_scale": 1.0,
            "clipping_warning": False,
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "reference_source": str(clean_reference_pdf),
            "reference_source_svg": str(clean_reference_svg),
            "notes": notes,
        }


def _prepare_drawing_candidate(
    source_pdf: Path,
    *,
    variant_name: str,
    exact_geometry_mode: bool,
    strict_one_to_one: bool,
    candidate_dir: Path,
    image_contours_mode: str = "off",
    disable_small_lineart_circle_recovery: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_drawing_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        shutil.copy2(source_pdf, ascii_pdf)
        ctx = _ctx(f"preview-{time.time_ns()}")
        prev_circle_param2 = float(getattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2", 10.0))
        try:
            if disable_small_lineart_circle_recovery:
                setattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2", 9999.0)
            with _backend_override_context(_kompas_text_join_backend_overrides(source_pdf)):
                ok, msg, logs = _bridge_run_preview(
                    ctx=ctx,
                    input_path=ascii_pdf,
                    sheet=SheetConfig(sheet_format="a4", anchor="lower_left"),
                    tool_mode="pen",
                    render_mode="drawing",
                    quality_profile="high",
                    force_text_to_path=True,
                    handwriting_enabled=False,
                    handwriting_font="Marck Script",
                    handwriting_formula_font="Times New Roman",
                    image_contours_mode=image_contours_mode,
                    source_page_index=1,
                    source_all_pages=False,
                    exact_geometry_mode=exact_geometry_mode,
                    safe_travel_lift=True,
                    strict_one_to_one=strict_one_to_one,
                )
        finally:
            setattr(backend, "IMAGE_CONTOUR_SMALL_LINEART_CIRCLE_PARAM2", prev_circle_param2)
        if not ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        prefix = candidate_dir / variant_name
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
        preview_ok, preview_err = _build_sheet_preview_from_gcode(
            gcode_path=nc_path,
            reference_pdf=source_pdf,
            out_svg=svg_path,
            out_pdf=pdf_path,
            logs=logs,
        )
        if not preview_ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": preview_err,
                "logs": logs,
            }
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=0)
        return {
            "variant": variant_name,
            "ok": True,
            "message": msg,
            "logs": logs,
            "fit_scale": _parse_fit_scale(logs),
            "clipping_warning": _has_clipping_warning(logs),
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
        }


def _prepare_compact_source_overlay_candidate(
    source_pdf: Path,
    *,
    variant_name: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_drawing_compact_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        source_svg = td_path / "source.svg"
        shutil.copy2(source_pdf, ascii_pdf)
        logs: list[str] = []
        try:
            page_w_mm, page_h_mm = _export_pdf_page_to_mupdf_svg(
                ascii_pdf,
                0,
                source_svg,
                text_as_path=False,
            )
            header_lines = _extract_a4_header_text_lines_from_pdf(ascii_pdf, page_index=0)
            if header_lines:
                line_boxes = [
                    tuple(line.get("bbox_mm", ()) or ())
                    for line in header_lines
                    if len(tuple(line.get("bbox_mm", ()) or ())) >= 4
                ]
                if line_boxes:
                    region_mm = (
                        min(float(b[0]) for b in line_boxes) - 1.0,
                        min(float(b[1]) for b in line_boxes) - 1.0,
                        max(float(b[2]) for b in line_boxes) + 1.0,
                        max(float(b[3]) for b in line_boxes) + 1.0,
                    )
                    removed_nodes = _remove_svg_text_nodes_in_region(
                        source_svg,
                        region_mm=region_mm,
                        page_w_mm=float(page_w_mm),
                        page_h_mm=float(page_h_mm),
                    )
                    rerendered = _render_pdf_text_lines_polylines_in_place(
                        header_lines,
                        tight_layout=True,
                        ttf_backend="skeleton",
                        logger=logs.append,
                    )
                    appended_text = _append_overlay_polylines_to_existing_svg(
                        source_svg,
                        rerendered,
                        page_w_mm=float(page_w_mm),
                        page_h_mm=float(page_h_mm),
                    )
                    logs.append(
                        "A4 compact header text reroute: "
                        f"removed {int(removed_nodes)} SVG text node(s), appended {int(appended_text)} single-line path(s)."
                    )
            extra_polys, recovered = _extract_small_condition_image_polylines_from_pdf(
                ascii_pdf,
                page_index=0,
                logger=logs.append,
            )
            appended = 0
            if extra_polys:
                appended = _append_overlay_polylines_to_existing_svg(
                    source_svg,
                    extra_polys,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                )
            logs.append(
                "A4 compact source route: direct PDF vector SVG export with miniature recovery "
                f"(images={len(recovered)}, paths={len(extra_polys)}, appended={int(appended)})."
            )
        except Exception as exc:
            return {
                "variant": variant_name,
                "ok": False,
                "message": str(exc),
                "logs": [f"A4 compact source route failed: {exc}"],
            }

        ctx = _ctx(f"preview-{time.time_ns()}")
        ok, msg, bridge_logs = _bridge_run_preview(
            ctx=ctx,
            input_path=source_svg,
            sheet=SheetConfig(sheet_format="a4", anchor="lower_left"),
            tool_mode="pen",
            render_mode="drawing",
            quality_profile="high",
            force_text_to_path=True,
            handwriting_enabled=False,
            handwriting_font="Marck Script",
            handwriting_formula_font="Times New Roman",
            image_contours_mode="off",
            source_page_index=1,
            source_all_pages=False,
            exact_geometry_mode=False,
            safe_travel_lift=True,
            strict_one_to_one=False,
        )
        logs.extend(bridge_logs)
        if not ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        prefix = candidate_dir / variant_name
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
        preview_ok, preview_err = _build_sheet_preview_from_gcode(
            gcode_path=nc_path,
            reference_pdf=source_pdf,
            out_svg=svg_path,
            out_pdf=pdf_path,
            logs=logs,
        )
        if not preview_ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": preview_err,
                "logs": logs,
            }
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=0)
        return {
            "variant": variant_name,
            "ok": True,
            "message": msg,
            "logs": logs,
            "fit_scale": _parse_fit_scale(logs),
            "clipping_warning": _has_clipping_warning(logs),
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "notes": "source_cleanup=direct_pdf_svg; compact_miniature_overlay=True",
        }


def _is_computer_graphics_source(source_pdf: Path) -> bool:
    try:
        return "компьютерная графика" in str(source_pdf).casefold()
    except Exception:
        return False


def _cleanup_mupdf_a4_source_polylines(
    polylines: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
) -> tuple[list[list[tuple[float, float]]], dict[str, int]]:
    if not polylines:
        return [], {"left_strip_removed": 0, "footer_removed": 0, "outer_frame_removed": 0}
    kept: list[list[tuple[float, float]]] = []
    left_strip_removed = 0
    footer_removed = 0
    outer_frame_removed = 0
    cutoff_x = min(32.0, max(24.0, float(page_w_mm) * 0.145))
    footer_y = float(page_h_mm) - 6.0
    for poly in polylines:
        if len(poly) < 2:
            continue
        x0, y0, x1, y1 = _poly_bbox_mm(poly)
        bw = float(x1 - x0)
        bh = float(y1 - y0)
        axis = _poly_is_axis_aligned_mm(poly, eps=0.18)
        if axis:
            if (
                (bh <= 0.18 and bw >= (float(page_w_mm) - 8.0) and (float(y0) <= 1.2 or float(y0) >= float(page_h_mm) - 1.2))
                or (bw <= 0.18 and bh >= (float(page_h_mm) - 8.0) and (float(x0) <= 1.2 or float(x0) >= float(page_w_mm) - 1.2))
            ):
                outer_frame_removed += 1
                continue
        if float(x1) <= float(cutoff_x):
            left_strip_removed += 1
            continue
        if float(y0) >= float(footer_y):
            if (not axis) or max(bw, bh) < 20.0:
                footer_removed += 1
                continue
        kept.append(poly)
    if not kept:
        return list(polylines), {"left_strip_removed": 0, "footer_removed": 0, "outer_frame_removed": 0}
    return kept, {
        "left_strip_removed": int(left_strip_removed),
        "footer_removed": int(footer_removed),
        "outer_frame_removed": int(outer_frame_removed),
    }


def _prepare_mupdf_svg_paths_candidate(
    source_pdf: Path,
    *,
    variant_name: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_drawing_mupdf_paths_") as td:
        td_path = Path(td)
        source_svg = td_path / "source.svg"
        source_pdf_preview = td_path / "source.pdf"
        logs: list[str] = []
        try:
            page_w_mm, page_h_mm, kompas_centerline_text_nodes, kompas_centerline_text_ok = (
                _export_pdf_page_to_svg_for_kompas_text_centerline(
                    source_pdf,
                    0,
                    source_svg,
                    logger=logs.append,
                )
            )
            with fitz.open(str(source_pdf)) as src_doc:
                out_doc = fitz.open()
                try:
                    out_doc.insert_pdf(src_doc, from_page=0, to_page=0)
                    out_doc.save(str(source_pdf_preview))
                finally:
                    out_doc.close()
            bridge = BackendBridge(PROJECT_ROOT)
            path_items = backend.extract_polylines(source_svg)
            page_items, _unit_scale = backend.normalize_path_units_to_page(
                path_items,
                float(page_w_mm),
                float(page_h_mm),
                logger=lambda *_args, **_kwargs: None,
            )
            frame_class = _drawing_frame_class(source_pdf)
            source_polys = (
                _kompas_source_to_drawing_polylines(page_items, source_pdf=source_pdf, page_index=0)
                if frame_class == "kompas_full_frame"
                else backend.to_drawing_polylines(page_items)
            )
            cleanup_meta = {"left_strip_removed": 0, "footer_removed": 0, "outer_frame_removed": 0}
            kompas_cleanup_meta = {"archive_strip_removed": 0, "under_frame_removed": 0}
            kompas_text_meta = _empty_kompas_text_meta()
            kompas_stamp_text_meta = _empty_kompas_stamp_text_meta()
            title_block_meta = {"title_block_text_removed": 0.0, "title_block_text_rendered": 0.0}
            if frame_class == "kompas_full_frame":
                source_polys, kompas_cleanup_meta = _cleanup_kompas_archive_strip_polylines(
                    source_polys,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                    specification_table=_is_kompas_specification_table_source(source_pdf),
                    service_regions_mm=_kompas_service_regions_from_pdf(source_pdf, page_index=0),
                )
                if _should_reroute_kompas_text(source_pdf):
                    source_polys, kompas_text_meta = _reroute_kompas_text_polylines(
                        source_polys,
                        source_pdf=source_pdf,
                        page_index=0,
                        logger=logs.append,
                    )
                else:
                    logs.append("KOMPAS source text preserved: single-line text reroute disabled for production.")
                if _should_repair_kompas_stamp_title_text(source_pdf):
                    source_polys, kompas_stamp_text_meta = _reroute_kompas_stamp_title_text_polylines(
                        source_polys,
                        source_pdf=source_pdf,
                        page_index=0,
                        logger=logs.append,
                    )
                else:
                    logs.append(
                        "KOMPAS stamp/title text preserved: single-line stamp repair disabled for production."
                    )
            else:
                source_polys, cleanup_meta = _cleanup_mupdf_a4_source_polylines(
                    source_polys,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                )
                source_polys, title_block_meta = _reroute_title_block_text_polylines(
                    source_polys,
                    source_pdf=source_pdf,
                    page_index=0,
                    ttf_backend="skeleton",
                    tight_layout=False,
                    logger=logs.append,
                )
            bridge._write_method3_svg(
                source_svg,
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            _render_polylines_pdf(
                polylines=source_polys,
                out_pdf=source_pdf_preview,
                canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)),
            )
            if _drawing_frame_class(source_pdf) == "kompas_full_frame":
                logs.append(
                    f"A4 MuPDF source route: direct PDF vector SVG export with text_as_path={'False' if kompas_centerline_text_ok else 'True'}; "
                    f"kompas_archive_strip_removed={kompas_cleanup_meta['archive_strip_removed']}; "
                    f"kompas_service_region_removed={kompas_cleanup_meta['service_region_removed']}; "
                    f"kompas_under_frame_removed={kompas_cleanup_meta['under_frame_removed']}; "
                    f"kompas_top_outer_frame_removed={kompas_cleanup_meta['top_outer_frame_removed']}; "
                    f"kompas_text_lines={int(kompas_text_meta.get('kompas_text_lines', 0.0))}; "
                    f"kompas_text_removed={int(kompas_text_meta.get('kompas_text_removed', 0.0))}; "
                    f"kompas_text_rendered={int(kompas_text_meta.get('kompas_text_rendered', 0.0))}; "
                    f"kompas_stamp_text_lines={int(kompas_stamp_text_meta.get('kompas_stamp_text_lines', 0.0))}; "
                    f"kompas_stamp_text_removed={int(kompas_stamp_text_meta.get('kompas_stamp_text_removed', 0.0))}; "
                    f"kompas_stamp_text_rendered={int(kompas_stamp_text_meta.get('kompas_stamp_text_rendered', 0.0))}; "
                    f"kompas_text_centerline_averaging={'True' if kompas_centerline_text_ok else 'False'}; "
                    f"kompas_text_centerline_nodes={int(kompas_centerline_text_nodes)}; "
                    "source text preserved outside stamp/title repair regions."
                )
            else:
                logs.append(
                    "A4 MuPDF source route: direct PDF vector SVG export with text_as_path=True; "
                    f"left_strip_removed={cleanup_meta['left_strip_removed']}, "
                    f"footer_removed={cleanup_meta['footer_removed']}, "
                    f"outer_frame_removed={cleanup_meta['outer_frame_removed']}, "
                    f"title_block_text_removed={int(title_block_meta.get('title_block_text_removed', 0.0))}, "
                    f"title_block_text_rendered={int(title_block_meta.get('title_block_text_rendered', 0.0))}."
                )
        except Exception as exc:
            return {
                "variant": variant_name,
                "ok": False,
                "message": str(exc),
                "logs": [f"A4 MuPDF source route failed: {exc}"],
            }

        if _drawing_frame_class(source_pdf) == "kompas_full_frame":
            prefix = candidate_dir / variant_name
            svg_path, pdf_path, nc_path, gcode_path = _bridge_preview_copy_targets(prefix)
            try:
                clean_bbox_polys, clean_bbox_meta = _prepare_kompas_a4_clean_bbox_fit_polylines(
                    source_polys,
                    logs=logs,
                )
                if bool(clean_bbox_meta.get("applied")):
                    _rewrite_final_gcode_from_polylines(
                        clean_bbox_polys,
                        dst_nc=nc_path,
                        dst_gcode=gcode_path,
                    )
                    preview_ok, preview_err = _rewrite_preview_on_work_area_canvas_from_gcode(
                        gcode_path=nc_path,
                        out_svg=svg_path,
                        out_pdf=pdf_path,
                        logs=logs,
                    )
                    if not preview_ok:
                        raise RuntimeError(preview_err)
                    ref_prefix = candidate_dir / f"{variant_name}__clean_source"
                    ref_svg = ref_prefix.with_suffix(".svg")
                    ref_pdf = ref_prefix.with_suffix(".pdf")
                    _copy_file(source_svg, ref_svg)
                    _copy_file(source_pdf_preview, ref_pdf)
                    metrics = _analyze_gcode(nc_path)
                    similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=0)
                    return {
                        "variant": variant_name,
                        "ok": True,
                        "message": "kompas_a4_clean_bbox_fit",
                        "logs": logs,
                        "fit_scale": float(clean_bbox_meta.get("content_scale", 1.0) or 1.0),
                        "clipping_warning": int(clean_bbox_meta.get("clipped_segments", 0) or 0) > 0,
                        "layout_similarity": similarity,
                        "metrics": metrics,
                        "svg": str(svg_path),
                        "pdf": str(pdf_path),
                        "nc": str(nc_path),
                        "gcode": str(gcode_path),
                        "reference_source": str(ref_pdf),
                        "reference_source_svg": str(ref_svg),
                        "clean_bbox_fit_meta": clean_bbox_meta,
                        "notes": (
                            "source_cleanup=direct_pdf_svg; mupdf_svg_paths=True; "
                            "kompas_source_page_fit_disabled=True; work_area_frame=full; "
                            + (
                                "kompas_text_reroute=True; "
                                if int(kompas_text_meta.get("kompas_text_rendered", 0.0)) > 0
                                else "kompas_source_text_preserved=True; "
                            )
                            + (
                                "kompas_stamp_text_repair=True; "
                                if int(kompas_stamp_text_meta.get("kompas_stamp_text_rendered", 0.0)) > 0
                                else ""
                            )
                            + f"kompas_text_lines={int(kompas_text_meta.get('kompas_text_lines', 0.0))}; "
                            f"kompas_text_rendered={int(kompas_text_meta.get('kompas_text_rendered', 0.0))}; "
                            f"kompas_stamp_text_rendered={int(kompas_stamp_text_meta.get('kompas_stamp_text_rendered', 0.0))}; "
                            f"kompas_clean_bbox_scale={float(clean_bbox_meta.get('content_scale', 1.0) or 1.0):.6f}; "
                            f"clipped_segments={int(clean_bbox_meta.get('clipped_segments', 0) or 0)}"
                        ),
                    }
                logs.append(
                    "KOMPAS A4 clean-bbox route skipped: "
                    f"{clean_bbox_meta.get('reason', 'unknown')}."
                )
            except Exception as exc:
                logs.append(f"KOMPAS A4 clean-bbox route failed, falling back to backend preview: {exc}")

        ctx = _ctx(f"preview-{time.time_ns()}")
        backend_overrides: dict[str, Any] = {
            "SEGMENT_DEDUP_ENABLED": True,
            "ARROWHEAD_OPT_ENABLED": False,
        }
        backend_overrides.update(_kompas_text_join_backend_overrides(source_pdf))
        with _backend_override_context(backend_overrides):
            ok, msg, bridge_logs = _bridge_run_preview(
                ctx=ctx,
                input_path=source_svg,
                sheet=SheetConfig(sheet_format="a4", anchor="lower_left"),
                tool_mode="pen",
                render_mode="drawing",
                quality_profile="high",
                force_text_to_path=False,
                handwriting_enabled=False,
                handwriting_font="Marck Script",
                handwriting_formula_font="Times New Roman",
                image_contours_mode="off",
                source_page_index=1,
                source_all_pages=False,
                exact_geometry_mode=True,
                safe_travel_lift=True,
                strict_one_to_one=False,
            )
        logs.extend(bridge_logs)
        if not ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        prefix = candidate_dir / variant_name
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
        preview_ok, preview_err = _build_sheet_preview_from_gcode(
            gcode_path=nc_path,
            reference_pdf=source_pdf,
            out_svg=svg_path,
            out_pdf=pdf_path,
            logs=logs,
        )
        if not preview_ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": preview_err,
                "logs": logs,
            }
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=0)
        return {
            "variant": variant_name,
            "ok": True,
            "message": msg,
            "logs": logs,
            "fit_scale": _parse_fit_scale(logs),
            "clipping_warning": _has_clipping_warning(logs),
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "notes": "source_cleanup=direct_pdf_svg; mupdf_svg_paths=True",
        }


def _prepare_forced_a4_candidate(
    source_pdf: Path,
    *,
    variant_name: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_drawing_a4_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        clean_svg = td_path / "forced_a4_source.svg"
        shutil.copy2(source_pdf, ascii_pdf)
        prep_logs: list[str] = []
        removed_nodes = 0
        appended = 0
        kompas_text_meta = _empty_kompas_text_meta()
        try:
            if _drawing_frame_class(source_pdf) == "kompas_full_frame":
                page_w_mm, page_h_mm, kompas_centerline_text_nodes, kompas_centerline_text_ok = (
                    _export_pdf_page_to_svg_for_kompas_text_centerline(
                        source_pdf,
                        0,
                        clean_svg,
                        logger=prep_logs.append,
                    )
                )
                bridge = BackendBridge(PROJECT_ROOT)
                path_items = backend.extract_polylines(clean_svg)
                page_items, _unit_scale = backend.normalize_path_units_to_page(
                    path_items,
                    float(page_w_mm),
                    float(page_h_mm),
                    logger=lambda *_args, **_kwargs: None,
                )
                source_polys = _kompas_source_to_drawing_polylines(page_items, source_pdf=source_pdf, page_index=0)
                source_polys, kompas_cleanup_meta = _cleanup_kompas_archive_strip_polylines(
                    source_polys,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                    specification_table=_is_kompas_specification_table_source(source_pdf),
                    service_regions_mm=_kompas_service_regions_from_pdf(source_pdf, page_index=0),
                )
                if _should_reroute_kompas_text(source_pdf):
                    source_polys, kompas_text_meta = _reroute_kompas_text_polylines(
                        source_polys,
                        source_pdf=source_pdf,
                        page_index=0,
                        logger=prep_logs.append,
                    )
                else:
                    prep_logs.append("KOMPAS source text preserved: single-line text reroute disabled for production.")
                bridge._write_method3_svg(
                    clean_svg,
                    source_polys,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                )
                prep_logs.append(
                    "Forced A4 KOMPAS cleanup: "
                    f"archive_strip_removed={kompas_cleanup_meta['archive_strip_removed']}; "
                    f"service_region_removed={kompas_cleanup_meta['service_region_removed']}; "
                    f"under_frame_removed={kompas_cleanup_meta['under_frame_removed']}; "
                    f"top_outer_frame_removed={kompas_cleanup_meta['top_outer_frame_removed']}; "
                    f"kompas_text_lines={int(kompas_text_meta.get('kompas_text_lines', 0.0))}; "
                    f"kompas_text_removed={int(kompas_text_meta.get('kompas_text_removed', 0.0))}; "
                    f"kompas_text_rendered={int(kompas_text_meta.get('kompas_text_rendered', 0.0))}; "
                    f"kompas_text_centerline_averaging={'True' if kompas_centerline_text_ok else 'False'}; "
                    f"kompas_text_centerline_nodes={int(kompas_centerline_text_nodes)}."
                )
            else:
                page_w_mm, page_h_mm = _export_pdf_page_to_mupdf_svg(
                    ascii_pdf,
                    0,
                    clean_svg,
                    text_as_path=False,
                )
                title_lines = _extract_title_block_text_lines_from_pdf(ascii_pdf, page_index=0)
                region_mm = _svg_title_block_region_from_pdf_lines(title_lines)
                if region_mm is not None:
                    removed_nodes = _remove_svg_text_nodes_in_region(
                        clean_svg,
                        region_mm=region_mm,
                        page_w_mm=float(page_w_mm),
                        page_h_mm=float(page_h_mm),
                    )
                    rerendered = _render_pdf_text_lines_polylines_in_place(
                        title_lines,
                        tight_layout=True,
                        ttf_backend="skeleton",
                        logger=lambda _msg: None,
                    )
                    appended = _append_overlay_polylines_to_existing_svg(
                        clean_svg,
                        rerendered,
                        page_w_mm=float(page_w_mm),
                        page_h_mm=float(page_h_mm),
                    )
        except Exception:
            clean_svg = ascii_pdf
        ctx = _ctx(f"preview-{time.time_ns()}")
        with _backend_override_context(_kompas_text_join_backend_overrides(source_pdf)):
            ok, msg, logs = _bridge_run_preview(
                ctx=ctx,
                input_path=clean_svg,
                sheet=SheetConfig(sheet_format="a4", anchor="center"),
                tool_mode="pen",
                render_mode="drawing",
                quality_profile="high",
                force_text_to_path=True,
                handwriting_enabled=False,
                handwriting_font="Marck Script",
                handwriting_formula_font="Times New Roman",
                image_contours_mode="off",
                source_page_index=1,
                source_all_pages=False,
                exact_geometry_mode=False,
                safe_travel_lift=True,
                strict_one_to_one=False,
            )
        if prep_logs:
            logs = [*prep_logs, *logs]
        if clean_svg != ascii_pdf:
            logs.insert(0, "Forced A4 direct vector scale: source PDF exported to SVG for A4 fit.")
        if removed_nodes > 0 or appended > 0:
            logs.insert(
                1 if clean_svg != ascii_pdf else 0,
                "Forced A4 title block single-line reroute: "
                f"removed {int(removed_nodes)} SVG text node(s), appended {int(appended)} single-line path(s).",
            )
        if not ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        prefix = candidate_dir / variant_name
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
        preview_ok, preview_err = _build_fixed_canvas_preview_from_gcode(
            gcode_path=nc_path,
            out_svg=svg_path,
            out_pdf=pdf_path,
            page_w_mm=210.0,
            page_h_mm=297.0,
            logs=logs,
        )
        if not preview_ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": preview_err,
                "logs": logs,
            }
        _copy_file(nc_path, gcode_path)
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=0)
        return {
            "variant": variant_name,
            "ok": True,
            "message": msg,
            "logs": logs,
            "fit_scale": _parse_fit_scale(logs),
            "clipping_warning": _has_clipping_warning(logs),
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "reference_source": str(pdf_path),
            "reference_source_svg": str(svg_path),
            "notes": (
                "forced_a4_single_page=True"
                + (
                    (
                        "; "
                        + (
                            "kompas_text_reroute=True; "
                            if int(kompas_text_meta.get("kompas_text_rendered", 0.0)) > 0
                            else "kompas_source_text_preserved=True; "
                        )
                        + f"kompas_text_lines={int(kompas_text_meta.get('kompas_text_lines', 0.0))}; "
                        + f"kompas_text_rendered={int(kompas_text_meta.get('kompas_text_rendered', 0.0))}"
                    )
                    if _drawing_frame_class(source_pdf) == "kompas_full_frame"
                    else ""
                )
            ),
        }


def _is_specification_like_drawing(source_pdf: Path) -> bool:
    try:
        name = source_pdf.stem.casefold()
    except Exception:
        return False
    return "спецификация" in name


def _prepare_reference_pdf_candidate(
    input_pdf: Path,
    *,
    reference_pdf: Path,
    variant_name: str,
    candidate_dir: Path,
    reference_svg: Path | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_drawing_ref_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        shutil.copy2(input_pdf, ascii_pdf)
        ctx = _ctx(f"preview-{time.time_ns()}")
        ok, msg, logs = _bridge_run_preview(
            ctx=ctx,
            input_path=ascii_pdf,
            sheet=SheetConfig(sheet_format="a4", anchor="center"),
            tool_mode="pen",
            render_mode="drawing",
            quality_profile="high",
            force_text_to_path=True,
            handwriting_enabled=False,
            handwriting_font="Marck Script",
            handwriting_formula_font="Times New Roman",
            image_contours_mode="off",
            source_page_index=1,
            source_all_pages=False,
            exact_geometry_mode=False,
            safe_travel_lift=True,
            strict_one_to_one=False,
        )
        if not ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        prefix = candidate_dir / variant_name
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
        preview_ok, preview_err = _build_sheet_preview_from_gcode(
            gcode_path=nc_path,
            reference_pdf=reference_pdf,
            out_svg=svg_path,
            out_pdf=pdf_path,
            logs=logs,
        )
        if not preview_ok:
            return {
                "variant": variant_name,
                "ok": False,
                "message": preview_err,
                "logs": logs,
            }
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(reference_pdf, pdf_path, source_page_index=0)
        result = {
            "variant": variant_name,
            "ok": True,
            "message": msg,
            "logs": logs,
            "fit_scale": _parse_fit_scale(logs),
            "clipping_warning": _has_clipping_warning(logs),
            "layout_similarity": similarity,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "reference_source": str(reference_pdf),
        }
        if reference_svg is not None and reference_svg.exists():
            result["reference_source_svg"] = str(reference_svg)
        return result


def _prepare_a3_pass(
    source_pdf: Path,
    *,
    pass_index: int,
    prefix: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_a3_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        shutil.copy2(source_pdf, ascii_pdf)
        pass_notes = []
        if int(pass_index) == 2:
            pass_notes.append("pass_02_rotated_180_for_sheet_flip=True")
        ctx = _ctx(f"preview-{time.time_ns()}")
        ok, msg, logs = _bridge_run_preview(
            ctx=ctx,
            input_path=ascii_pdf,
            sheet=SheetConfig(sheet_format="a3", anchor="lower_left", pass_cols=2, pass_rows=1, pass_col=pass_index, pass_row=1),
            tool_mode="pen",
            render_mode="drawing",
            quality_profile="high",
            force_text_to_path=True,
            handwriting_enabled=False,
            handwriting_font="Marck Script",
            handwriting_formula_font="Times New Roman",
            image_contours_mode="off",
            source_page_index=1,
            source_all_pages=False,
            exact_geometry_mode=False,
            safe_travel_lift=True,
            strict_one_to_one=False,
        )
        if not ok:
            return {
                "item": f"pass_{pass_index}",
                "ok": False,
                "message": msg,
                "logs": logs,
            }
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
        metrics = _analyze_gcode(nc_path)
        return {
            "item": f"pass_{pass_index}",
            "ok": True,
            "message": msg,
            "logs": ([*pass_notes, *logs] if pass_notes else logs),
            "fit_scale": _parse_fit_scale(logs),
            "clipping_warning": _has_clipping_warning(logs),
            "layout_similarity": None,
            "metrics": metrics,
            "svg": str(svg_path),
            "pdf": str(pdf_path),
            "nc": str(nc_path),
            "gcode": str(gcode_path),
            "notes": "; ".join(pass_notes),
        }


def _prepare_a3_clean_source_svg(
    source_pdf: Path,
    *,
    source_svg: Path,
    source_preview_pdf: Path,
) -> tuple[bool, str, list[str]]:
    logs: list[str] = []
    try:
        reroute_title_block = _should_reroute_title_block_text(source_pdf)
        kompas_centerline_text_nodes = 0
        kompas_centerline_text_ok = False
        if _drawing_frame_class(source_pdf) == "kompas_full_frame":
            page_w_mm, page_h_mm, kompas_centerline_text_nodes, kompas_centerline_text_ok = (
                _export_pdf_page_to_svg_for_kompas_text_centerline(
                    source_pdf,
                    0,
                    source_svg,
                    logger=logs.append,
                )
            )
        else:
            page_w_mm, page_h_mm = _export_pdf_page_to_mupdf_svg(
                source_pdf,
                0,
                source_svg,
                text_as_path=not reroute_title_block,
            )
        with fitz.open(str(source_pdf)) as src_doc:
            if int(src_doc.page_count) < 1:
                return False, "Source A3 PDF has no pages.", logs
            out_doc = fitz.open()
            try:
                out_doc.insert_pdf(src_doc, from_page=0, to_page=0)
                out_doc.save(str(source_preview_pdf))
            finally:
                out_doc.close()
        if reroute_title_block:
            title_lines = _extract_title_block_text_lines_from_pdf(source_pdf, page_index=0)
            region_mm = _svg_title_block_region_from_pdf_lines(title_lines)
            if region_mm is not None:
                removed_nodes = _remove_svg_text_nodes_in_region(
                    source_svg,
                    region_mm=region_mm,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                )
                rerendered = _render_pdf_text_lines_polylines_in_place(
                    title_lines,
                    tight_layout=True,
                    ttf_backend="skeleton",
                    logger=logs.append,
                )
                appended = _append_overlay_polylines_to_existing_svg(
                    source_svg,
                    rerendered,
                    page_w_mm=float(page_w_mm),
                    page_h_mm=float(page_h_mm),
                )
                logs.append(
                    "A3 title block text reroute: "
                    f"removed {int(removed_nodes)} SVG text node(s), appended {int(appended)} single-line path(s)."
                )
        extra_polys, recovered = _extract_small_condition_image_polylines_from_pdf(
            source_pdf,
            page_index=0,
            logger=logs.append,
        )
        if extra_polys:
            appended = _append_overlay_polylines_to_existing_svg(
                source_svg,
                extra_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            logs.append(
                "A3 condition image recovery summary: "
                f"{len(recovered)} image(s), {len(extra_polys)} path(s), appended={int(appended)}."
            )
        if _drawing_frame_class(source_pdf) == "kompas_full_frame":
            bridge = BackendBridge(PROJECT_ROOT)
            path_items = backend.extract_polylines(source_svg)
            page_items, _unit_scale = backend.normalize_path_units_to_page(
                path_items,
                float(page_w_mm),
                float(page_h_mm),
                logger=lambda *_args, **_kwargs: None,
            )
            source_polys = _kompas_source_to_drawing_polylines(page_items, source_pdf=source_pdf, page_index=0)
            source_polys, kompas_cleanup_meta = _cleanup_kompas_archive_strip_polylines(
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
                specification_table=_is_kompas_specification_table_source(source_pdf),
                service_regions_mm=_kompas_service_regions_from_pdf(source_pdf, page_index=0),
            )
            source_polys, kompas_a3_frame_meta = _strip_kompas_a3_outer_sheet_frame_polylines(
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            kompas_text_meta = _empty_kompas_text_meta()
            kompas_stamp_text_meta = _empty_kompas_stamp_text_meta()
            if _should_reroute_kompas_text(source_pdf):
                source_polys, kompas_text_meta = _reroute_kompas_text_polylines(
                    source_polys,
                    source_pdf=source_pdf,
                    page_index=0,
                    logger=logs.append,
                )
            else:
                logs.append("KOMPAS source text preserved: single-line text reroute disabled for production.")
            if _should_repair_kompas_stamp_title_text(source_pdf):
                source_polys, kompas_stamp_text_meta = _reroute_kompas_stamp_title_text_polylines(
                    source_polys,
                    source_pdf=source_pdf,
                    page_index=0,
                    logger=logs.append,
                )
            else:
                logs.append("KOMPAS stamp/title text preserved: single-line stamp repair disabled for production.")
            bridge._write_method3_svg(
                source_svg,
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            _render_polylines_pdf(
                polylines=source_polys,
                out_pdf=source_preview_pdf,
                canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)),
            )
            logs.append(
                "A3 clean source KOMPAS cleanup: "
                f"archive_strip_removed={kompas_cleanup_meta['archive_strip_removed']}; "
                f"service_region_removed={kompas_cleanup_meta['service_region_removed']}; "
                f"under_frame_removed={kompas_cleanup_meta['under_frame_removed']}; "
                f"top_outer_frame_removed={kompas_cleanup_meta['top_outer_frame_removed']}; "
                f"a3_outer_sheet_frame_removed={kompas_a3_frame_meta['removed_segments']}; "
                f"a3_outer_sheet_frame_kept_stamp_edges={kompas_a3_frame_meta['kept_stamp_segments']}; "
                f"kompas_text_lines={int(kompas_text_meta.get('kompas_text_lines', 0.0))}; "
                f"kompas_text_removed={int(kompas_text_meta.get('kompas_text_removed', 0.0))}; "
                f"kompas_text_rendered={int(kompas_text_meta.get('kompas_text_rendered', 0.0))}; "
                f"kompas_stamp_text_lines={int(kompas_stamp_text_meta.get('kompas_stamp_text_lines', 0.0))}; "
                f"kompas_stamp_text_removed={int(kompas_stamp_text_meta.get('kompas_stamp_text_removed', 0.0))}; "
                f"kompas_stamp_text_rendered={int(kompas_stamp_text_meta.get('kompas_stamp_text_rendered', 0.0))}; "
                f"kompas_text_centerline_averaging={'True' if kompas_centerline_text_ok else 'False'}; "
                f"kompas_text_centerline_nodes={int(kompas_centerline_text_nodes)}."
            )
        logs.append(
            "A3 clean source route: direct PDF vector SVG export "
            f"(text_as_path={'False' if reroute_title_block else 'True'})."
        )
        return True, "A3 clean source prepared from direct PDF vector export.", logs
    except Exception as exc:
        logs.append(f"A3 direct PDF vector export failed, falling back to Method3: {exc}")

    bridge = BackendBridge(PROJECT_ROOT)
    _configure_drawing_method3_backend(sheet_format="a3", pass_cols=2, pass_rows=1, pass_col=1, pass_row=1)
    with _technical_drawing_backend_precision():
        ok, msg = bridge._prepare_method3_page(
            backend=backend,
            input_path=source_pdf,
            source_page_index=1,
            body_font="Marck Script",
            formula_font="Times New Roman",
            output_svg=source_svg,
            output_pdf=source_preview_pdf,
            output_nc=None,
            log=logs.append,
            source_pdf_path=source_pdf,
            source_page_count=1,
        )
    if ok:
        _augment_method3_svg_with_condition_images(
            source_pdf,
            source_svg=source_svg,
            source_preview_pdf=source_preview_pdf,
            page_index=0,
            logger=logs.append,
            preserve_source_bounds=True,
        )
        with fitz.open(str(source_pdf)) as doc:
            page = doc[0]
            page_w_mm = float(page.rect.width) * 25.4 / 72.0
            page_h_mm = float(page.rect.height) * 25.4 / 72.0
        source_polys = _parse_method3_svg_polylines(source_svg)
        source_polys, _point_box_meta = _normalize_technical_point_boxes(
            source_polys,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
            logger=logs.append,
        )
        source_polys, _ = _maybe_reanchor_a3_clean_source_polylines(
            source_polys,
            ref_bbox_mm=_pdf_visible_bbox_mm(source_pdf),
            logger=logs.append,
        )
        bridge._write_method3_svg(source_svg, source_polys, page_w_mm=page_w_mm, page_h_mm=page_h_mm)
        _render_polylines_pdf(
            polylines=source_polys,
            out_pdf=source_preview_pdf,
            canvas_bounds_mm=(0.0, page_w_mm, 0.0, page_h_mm),
        )
    return ok, msg, logs


def _prepare_a3_pass_from_clean_svg(
    clean_svg: Path,
    *,
    source_pdf: Path,
    pass_index: int,
    prefix: Path,
    prep_logs: list[str] | None = None,
) -> dict[str, Any]:
    bridge = BackendBridge(PROJECT_ROOT)
    logs: list[str] = []
    pass_notes: list[str] = []
    if int(pass_index) == 2:
        pass_notes.append("pass_02_rotated_180_for_sheet_flip=True")
    ctx = _ctx(f"a3-clean-pass-{pass_index}-{time.time_ns()}")
    with _technical_drawing_backend_precision(), _backend_override_context(_kompas_text_join_backend_overrides(source_pdf)):
        ok, msg = bridge.run_preview(
            ctx=ctx,
            input_path=clean_svg,
            sheet=SheetConfig(sheet_format="a3", anchor="lower_left", pass_cols=2, pass_rows=1, pass_col=pass_index, pass_row=1),
            tool_mode="pen",
            render_mode="drawing",
            quality_profile="high",
            force_text_to_path=True,
            handwriting_enabled=False,
            handwriting_font="Marck Script",
            handwriting_formula_font="Times New Roman",
            image_contours_mode="off",
            source_page_index=1,
            source_all_pages=False,
            exact_geometry_mode=False,
            safe_travel_lift=True,
            strict_one_to_one=False,
            log=logs.append,
        )
    if not ok:
        return {
            "item": f"pass_{pass_index:02d}",
            "ok": False,
            "message": msg,
            "logs": [*(prep_logs or []), *pass_notes, "--- a3 clean pass ---", *logs],
        }
    svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
    preview_ok, preview_err = _build_sheet_preview_from_gcode(
        gcode_path=nc_path,
        reference_pdf=source_pdf,
        out_svg=svg_path,
        out_pdf=pdf_path,
        logs=logs,
    )
    if not preview_ok:
        return {
            "item": f"pass_{pass_index:02d}",
            "ok": False,
            "message": preview_err,
            "logs": [*(prep_logs or []), *pass_notes, "--- a3 clean pass ---", *logs],
        }
    metrics = _analyze_gcode(nc_path)
    source_route = "direct_pdf_svg" if any(
        "direct PDF vector SVG export" in str(line) for line in (prep_logs or [])
    ) else "method3"
    kompas_text_reroute = _logs_indicate_kompas_text_reroute(prep_logs)
    kompas_stamp_text_repair = _logs_indicate_kompas_stamp_text_repair(prep_logs)
    return {
        "item": f"pass_{pass_index:02d}",
        "ok": True,
        "message": msg,
        "logs": [*(prep_logs or []), *pass_notes, "--- a3 clean pass ---", *logs],
        "fit_scale": _parse_fit_scale(logs),
        "clipping_warning": _has_clipping_warning(logs),
        "layout_similarity": None,
        "metrics": metrics,
        "svg": str(svg_path),
        "pdf": str(pdf_path),
        "nc": str(nc_path),
        "gcode": str(gcode_path),
        "notes": "; ".join(
            part
            for part in [
                f"source_cleanup={source_route}",
                "left_strip_removed=True",
                "outer_border_removed=True",
                "kompas_text_reroute=True" if kompas_text_reroute else "",
                "kompas_stamp_text_repair=True" if kompas_stamp_text_repair else "",
                *pass_notes,
            ]
            if part
        ),
    }


def _prepare_literal_clean_source_svg(
    source_pdf: Path,
    *,
    source_svg: Path,
    source_preview_pdf: Path,
    rotate_90: bool = False,
) -> tuple[bool, str, list[str]]:
    logs: list[str] = []
    try:
        export_pdf = source_pdf
        if rotate_90:
            with fitz.open(str(source_pdf)) as src_doc:
                if int(src_doc.page_count) < 1:
                    return False, "Source PDF has no pages.", logs
                src_page = src_doc[0]
                out_doc = fitz.open()
                try:
                    rotated_page = out_doc.new_page(width=float(src_page.rect.height), height=float(src_page.rect.width))
                    rotated_page.show_pdf_page(rotated_page.rect, src_doc, 0, rotate=90)
                    out_doc.save(str(source_preview_pdf))
                finally:
                    out_doc.close()
            export_pdf = source_preview_pdf
        else:
            with fitz.open(str(source_pdf)) as src_doc:
                if int(src_doc.page_count) < 1:
                    return False, "Source PDF has no pages.", logs
                out_doc = fitz.open()
                try:
                    out_doc.insert_pdf(src_doc, from_page=0, to_page=0)
                    out_doc.save(str(source_preview_pdf))
                finally:
                    out_doc.close()
        kompas_centerline_text_nodes = 0
        kompas_centerline_text_ok = False
        if _drawing_frame_class(source_pdf) == "kompas_full_frame":
            page_w_mm, page_h_mm, kompas_centerline_text_nodes, kompas_centerline_text_ok = (
                _export_pdf_page_to_svg_for_kompas_text_centerline(
                    export_pdf,
                    0,
                    source_svg,
                    logger=logs.append,
                    frame_source_pdf=source_pdf,
                )
            )
        else:
            page_w_mm, page_h_mm = _export_pdf_page_to_mupdf_svg(
                export_pdf,
                0,
                source_svg,
                text_as_path=True,
            )
        if _drawing_frame_class(source_pdf) == "kompas_full_frame":
            bridge = BackendBridge(PROJECT_ROOT)
            path_items = backend.extract_polylines(source_svg)
            page_items, _unit_scale = backend.normalize_path_units_to_page(
                path_items,
                float(page_w_mm),
                float(page_h_mm),
                logger=lambda *_args, **_kwargs: None,
            )
            source_polys = _kompas_source_to_drawing_polylines(page_items, source_pdf=source_pdf, page_index=0)
            source_polys, kompas_cleanup_meta = _cleanup_kompas_archive_strip_polylines(
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
                specification_table=_is_kompas_specification_table_source(source_pdf),
                service_regions_mm=_kompas_service_regions_from_pdf(source_pdf, page_index=0),
            )
            source_polys, kompas_a3_frame_meta = _strip_kompas_a3_outer_sheet_frame_polylines(
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            kompas_text_meta = _empty_kompas_text_meta()
            kompas_stamp_text_meta = _empty_kompas_stamp_text_meta()
            if _should_reroute_kompas_text(source_pdf):
                source_polys, kompas_text_meta = _reroute_kompas_text_polylines(
                    source_polys,
                    source_pdf=source_pdf,
                    page_index=0,
                    logger=logs.append,
                )
            else:
                logs.append("KOMPAS source text preserved: single-line text reroute disabled for production.")
            if _should_repair_kompas_stamp_title_text(source_pdf):
                source_polys, kompas_stamp_text_meta = _reroute_kompas_stamp_title_text_polylines(
                    source_polys,
                    source_pdf=source_pdf,
                    page_index=0,
                    logger=logs.append,
                )
            else:
                logs.append("KOMPAS stamp/title text preserved: single-line stamp repair disabled for production.")
            bridge._write_method3_svg(
                source_svg,
                source_polys,
                page_w_mm=float(page_w_mm),
                page_h_mm=float(page_h_mm),
            )
            _render_polylines_pdf(
                polylines=source_polys,
                out_pdf=source_preview_pdf,
                canvas_bounds_mm=(0.0, float(page_w_mm), 0.0, float(page_h_mm)),
            )
            logs.append(
                "Literal clean source KOMPAS cleanup: "
                f"archive_strip_removed={kompas_cleanup_meta['archive_strip_removed']}; "
                f"service_region_removed={kompas_cleanup_meta['service_region_removed']}; "
                f"under_frame_removed={kompas_cleanup_meta['under_frame_removed']}; "
                f"top_outer_frame_removed={kompas_cleanup_meta['top_outer_frame_removed']}; "
                f"a3_outer_sheet_frame_removed={kompas_a3_frame_meta['removed_segments']}; "
                f"a3_outer_sheet_frame_kept_stamp_edges={kompas_a3_frame_meta['kept_stamp_segments']}; "
                f"kompas_text_lines={int(kompas_text_meta.get('kompas_text_lines', 0.0))}; "
                f"kompas_text_removed={int(kompas_text_meta.get('kompas_text_removed', 0.0))}; "
                f"kompas_text_rendered={int(kompas_text_meta.get('kompas_text_rendered', 0.0))}; "
                f"kompas_stamp_text_lines={int(kompas_stamp_text_meta.get('kompas_stamp_text_lines', 0.0))}; "
                f"kompas_stamp_text_removed={int(kompas_stamp_text_meta.get('kompas_stamp_text_removed', 0.0))}; "
                f"kompas_stamp_text_rendered={int(kompas_stamp_text_meta.get('kompas_stamp_text_rendered', 0.0))}; "
                f"kompas_text_centerline_averaging={'True' if kompas_centerline_text_ok else 'False'}; "
                f"kompas_text_centerline_nodes={int(kompas_centerline_text_nodes)}."
            )
        logs.append(
            "Literal clean source route: direct PDF vector SVG export "
            f"(text_as_path={'False' if _drawing_frame_class(source_pdf) == 'kompas_full_frame' and kompas_centerline_text_ok else 'True'}, "
            f"page={float(page_w_mm):.3f}x{float(page_h_mm):.3f} mm, rotated_90={'yes' if rotate_90 else 'no'})."
        )
        return True, "Literal clean source prepared from direct PDF vector export.", logs
    except Exception as exc:
        logs.append(f"Literal clean source export failed: {exc}")
        return False, f"Literal clean source export failed: {exc}", logs


def _prepare_tiled_pass_from_clean_svg(
    clean_svg: Path,
    *,
    source_pdf: Path | None = None,
    pass_index: int,
    pass_cols: int,
    pass_rows: int,
    pass_col: int,
    pass_row: int,
    sheet_w_mm: float,
    sheet_h_mm: float,
    prefix: Path,
    prep_logs: list[str] | None = None,
) -> dict[str, Any]:
    bridge = BackendBridge(PROJECT_ROOT)
    logs: list[str] = []
    pass_notes = [
        f"tile_cols={int(pass_cols)}",
        f"tile_rows={int(pass_rows)}",
        f"tile_col={int(pass_col)}",
        f"tile_row={int(pass_row)}",
    ]
    ctx = _ctx(f"tiled-clean-pass-{pass_index}-{time.time_ns()}")
    with _technical_drawing_backend_precision(), _backend_override_context(_kompas_text_join_backend_overrides(source_pdf)):
        ok, msg = bridge.run_preview(
            ctx=ctx,
            input_path=clean_svg,
            sheet=SheetConfig(
                sheet_format="custom",
                width_mm=float(sheet_w_mm),
                height_mm=float(sheet_h_mm),
                anchor="lower_left",
                pass_cols=int(pass_cols),
                pass_rows=int(pass_rows),
                pass_col=int(pass_col),
                pass_row=int(pass_row),
            ),
            tool_mode="pen",
            render_mode="drawing",
            quality_profile="high",
            force_text_to_path=True,
            handwriting_enabled=False,
            handwriting_font="Marck Script",
            handwriting_formula_font="Times New Roman",
            image_contours_mode="off",
            source_page_index=1,
            source_all_pages=False,
            exact_geometry_mode=True,
            safe_travel_lift=True,
            strict_one_to_one=True,
            log=logs.append,
        )
    if not ok:
        return {
            "item": f"pass_{pass_index:02d}",
            "ok": False,
            "message": msg,
            "logs": [*(prep_logs or []), *pass_notes, "--- tiled clean pass ---", *logs],
        }
    svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix, op_id=ctx.op_id)
    metrics = _analyze_gcode(nc_path)
    source_route = "direct_pdf_svg" if any(
        "direct PDF vector SVG export" in str(line) for line in (prep_logs or [])
    ) else "method3"
    kompas_text_reroute = _logs_indicate_kompas_text_reroute(prep_logs)
    return {
        "item": f"pass_{pass_index:02d}",
        "ok": True,
        "message": msg,
        "logs": [*(prep_logs or []), *pass_notes, "--- tiled clean pass ---", *logs],
        "fit_scale": _parse_fit_scale(logs),
        "clipping_warning": _has_clipping_warning(logs),
        "layout_similarity": None,
        "metrics": metrics,
        "svg": str(svg_path),
        "pdf": str(pdf_path),
        "nc": str(nc_path),
        "gcode": str(gcode_path),
        "notes": "; ".join(
            part
            for part in [
                f"source_cleanup={source_route}",
                "left_strip_removed=True",
                "outer_border_removed=True",
                "kompas_text_reroute=True" if kompas_text_reroute else "",
                *pass_notes,
            ]
            if part
        ),
    }


def _export_pdf_page_to_mupdf_svg(
    pdf_path: Path,
    page_index: int,
    out_svg: Path,
    *,
    text_as_path: bool = False,
) -> tuple[float, float]:
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    svg_text = page.get_svg_image(text_as_path=bool(text_as_path))
    page_w_mm = float(page.rect.width) * 25.4 / 72.0
    page_h_mm = float(page.rect.height) * 25.4 / 72.0
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.write_text(svg_text, encoding="utf-8")
    tree = ET.parse(out_svg)
    root = tree.getroot()
    root.set("width", f"{page_w_mm:.3f}mm")
    root.set("height", f"{page_h_mm:.3f}mm")
    tree.write(out_svg, encoding="utf-8", xml_declaration=True)
    doc.close()
    return float(page_w_mm), float(page_h_mm)


def _append_overlay_polylines_to_existing_svg(
    svg_path: Path,
    polylines_mm: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
) -> int:
    if not polylines_mm:
        return 0
    tree = ET.parse(svg_path)
    root = tree.getroot()
    view_box = str(root.get("viewBox", "") or "").strip().replace(",", " ").split()
    if len(view_box) != 4:
        return 0
    try:
        vb_x = float(view_box[0])
        vb_y = float(view_box[1])
        vb_w = float(view_box[2])
        vb_h = float(view_box[3])
    except Exception:
        return 0
    sx = float(vb_w) / max(1e-9, float(page_w_mm))
    sy = float(vb_h) / max(1e-9, float(page_h_mm))
    ns_svg = "{http://www.w3.org/2000/svg}"
    appended = 0
    for poly in polylines_mm:
        if len(poly) < 2:
            continue
        cmds: list[str] = []
        for idx, (x_mm, y_mm) in enumerate(poly):
            x_u = float(vb_x) + (float(x_mm) * float(sx))
            y_u = float(vb_y) + (float(y_mm) * float(sy))
            prefix = "M" if idx == 0 else "L"
            cmds.append(f"{prefix} {x_u:.4f} {y_u:.4f}")
        path_el = ET.Element(
            f"{ns_svg}path",
            {
                "d": " ".join(cmds),
                "fill": "none",
                "stroke": "#000000",
                "stroke-width": "1",
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            },
        )
        root.append(path_el)
        appended += 1
    if appended:
        tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    return int(appended)


def _configure_toe_backend(font_path: Path, *, backend_overrides: dict[str, Any] | None = None) -> None:
    policy = toe_font_policy.toe_font_first_policy()
    for key, value in policy.backend_settings(font_path).items():
        if hasattr(backend, key):
            setattr(backend, key, value)
    backend.apply_quality_profile("high", force_text_to_path=False)
    backend.configure_active_work_area(
        sheet_format="a4",
        sheet_width_mm=None,
        sheet_height_mm=None,
        anchor="lower_left",
        offset_x_mm=0.0,
        offset_y_mm=0.0,
        logger=lambda *_args, **_kwargs: None,
    )
    for key, value in dict(backend_overrides or {}).items():
        if hasattr(backend, key):
            setattr(backend, key, value)


def _prepare_toe_page(
    *,
    source_pdf: Path,
    page_index: int,
    page_svg: Path,
    font_label: str,
    font_path: Path,
    prefix: Path,
    backend_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _configure_toe_backend(font_path, backend_overrides=backend_overrides)
    logs: list[str] = []
    nc_path = prefix.with_suffix(".nc")
    ok, msg = backend.run_pipeline(page_svg, logs.append, send_to_plotter=False, output_path=nc_path)
    if not ok:
        return {
            "item": f"page_{page_index:02d}",
            "ok": False,
            "message": msg,
            "logs": logs,
            "font_label": font_label,
            "font_path": str(font_path),
        }

    bridge = BackendBridge(PROJECT_ROOT)
    svg_path = prefix.with_suffix(".svg")
    pdf_path = prefix.with_suffix(".pdf")
    preview_ok, preview_err = bridge._build_vector_preview_from_gcode(
        nc_path,
        svg_path,
        pdf_path,
        backend=backend,
        log=logs.append,
    )
    if not preview_ok:
        return {
            "item": f"page_{page_index:02d}",
            "ok": False,
            "message": preview_err,
            "logs": logs,
            "font_label": font_label,
            "font_path": str(font_path),
        }

    gcode_path = prefix.with_suffix(".gcode")
    _copy_file(nc_path, gcode_path)
    metrics = _analyze_gcode(nc_path)
    similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1)
    result = {
        "item": f"page_{page_index:02d}",
        "ok": True,
        "message": msg,
        "logs": logs,
        "font_label": font_label,
        "font_path": str(font_path),
        "layout_similarity": similarity,
        "metrics": metrics,
        "svg": str(svg_path),
        "pdf": str(pdf_path),
        "nc": str(nc_path),
        "gcode": str(gcode_path),
        "notes": "",
    }
    if float(similarity) < float(TOE_FALLBACK_LAYOUT_THRESHOLD):
        fallback = _prepare_toe_raster_fallback(
            source_pdf=source_pdf,
            page_index=page_index,
            page_svg=page_svg,
            prefix=prefix,
            font_label=font_label,
            font_path=font_path,
            backend_overrides=backend_overrides,
        )
        if bool(fallback.get("ok")) and float(fallback.get("layout_similarity", 0.0)) > float(similarity):
            for src_key, dst_path in zip(
                ["svg", "pdf", "nc", "gcode"],
                _bridge_preview_copy_targets(prefix),
            ):
                _copy_file(Path(str(fallback[src_key])), dst_path)
                try:
                    Path(str(fallback[src_key])).unlink()
                except Exception:
                    pass
            result = {
                "item": f"page_{page_index:02d}",
                "ok": True,
                "message": str(fallback.get("message", "")),
                "logs": list(logs) + ["--- raster rewrite fallback selected ---"] + list(fallback.get("logs", [])),
                "font_label": font_label,
                "font_path": str(font_path),
                "layout_similarity": float(fallback.get("layout_similarity", 0.0)),
                "metrics": dict(fallback.get("metrics", {})),
                "svg": str(prefix.with_suffix(".svg")),
                "pdf": str(prefix.with_suffix(".pdf")),
                "nc": str(prefix.with_suffix(".nc")),
                "gcode": str(prefix.with_suffix(".gcode")),
                "notes": str(fallback.get("notes", "")),
            }
        else:
            for src_key in ("svg", "pdf", "nc", "gcode"):
                path_val = fallback.get(src_key)
                if not path_val:
                    continue
                try:
                    Path(str(path_val)).unlink()
                except Exception:
                    pass
    return result

def _prepare_drawing_package(source_pdf: Path, package_dir: Path) -> tuple[dict[str, Any], list[ArtifactRow]]:
    pages_dir = package_dir / "pages"
    logs_dir = package_dir / "logs"
    _ensure_clean_dir(package_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(source_pdf)
    page = doc[0]
    page_w_mm = float(page.rect.width) * 25.4 / 72.0
    page_h_mm = float(page.rect.height) * 25.4 / 72.0
    forced_a4_single_page = _force_a4_single_page_for_drawing(source_pdf)
    forced_a3_two_pass = _force_a3_two_pass_for_large_sheet(source_pdf) or _force_variant_a3_two_pass_for_large_sheet(
        source_pdf,
        page_w_mm,
        page_h_mm,
    )
    literal_one_to_one_tiled = (
        _is_computer_graphics_source(source_pdf)
        and not forced_a4_single_page
        and not forced_a3_two_pass
        and max(float(page_w_mm), float(page_h_mm)) > 300.0
    )
    is_large_custom = (max(page_w_mm, page_h_mm) > 430.0) and not forced_a3_two_pass and not forced_a4_single_page
    is_a3 = (max(page_w_mm, page_h_mm) > 300.0) and not is_large_custom and not forced_a4_single_page

    rows: list[ArtifactRow] = []
    report: dict[str, Any] = {
        "source_pdf": str(source_pdf),
        "kind": "drawing",
        "frame_class": _drawing_frame_class(source_pdf),
        "page_count": int(doc.page_count),
        "page_size_mm": [round(page_w_mm, 3), round(page_h_mm, 3)],
        "a3_two_pass": bool(is_a3),
        "custom_tiled": bool(is_large_custom or literal_one_to_one_tiled),
        "forced_a3_two_pass": bool(forced_a3_two_pass),
        "forced_a4_single_page": bool(forced_a4_single_page),
        "selected_variant": "",
        "selected_layout_similarity": None,
        "selection_reason": "",
        "source_fidelity_score": None,
        "fragmentation_score": None,
        "title_block_strategy": "",
        "route_class": "",
        "compare_generated": False,
        "items": [],
    }

    if forced_a4_single_page:
        candidate_root = package_dir / "_candidates"
        candidate_root.mkdir(parents=True, exist_ok=True)
        candidates = [
            _prepare_forced_a4_candidate(
                source_pdf,
                variant_name="forced_a4_single_page",
                candidate_dir=candidate_root,
            )
        ]
        successful = [row for row in candidates if bool(row.get("ok"))]
        if not successful:
            report["items"] = candidates
            doc.close()
            return report, rows
        best = successful[0]
        decision = _build_a4_selection_decision(source_pdf, best, selection_reason="forced_a4_single_page")
        best_prefix = pages_dir / "page_01"
        for src_key, dst_path in zip(
            ["svg", "pdf", "nc", "gcode"],
            _bridge_preview_copy_targets(best_prefix),
        ):
            _copy_file(Path(str(best[src_key])), dst_path)
        chosen_logs = list(best.get("logs", []))
        preview_ok, preview_err = _rewrite_preview_on_work_area_canvas_from_gcode(
            gcode_path=best_prefix.with_suffix(".nc"),
            out_svg=best_prefix.with_suffix(".svg"),
            out_pdf=best_prefix.with_suffix(".pdf"),
            logs=chosen_logs,
        )
        if not preview_ok:
            report["items"] = candidates
            report.update(decision)
            report["selected_layout_similarity"] = best.get("layout_similarity")
            doc.close()
            return report, rows
        _write_text(logs_dir / "page_01.log.txt", "\n".join(chosen_logs) + ("\n" if chosen_logs else ""))
        report["items"] = candidates
        report.update(decision)
        report["selected_layout_similarity"] = best.get("layout_similarity")
        ref_pdf_raw = str(best.get("reference_source", "") or best.get("pdf", "") or "").strip()
        ref_svg_raw = str(best.get("reference_source_svg", "") or best.get("svg", "") or "").strip()
        if ref_pdf_raw:
            ref_pdf_dst = package_dir / "a4_clean_source.pdf"
            ref_svg_dst = package_dir / "a4_clean_source.svg"
            _copy_file(Path(ref_pdf_raw), ref_pdf_dst)
            if ref_svg_raw:
                _copy_file(Path(ref_svg_raw), ref_svg_dst)
            report["a4_clean_source"] = {
                "pdf": str(ref_pdf_dst),
                "svg": str(ref_svg_dst),
            }
        metrics = dict(best.get("metrics", {}))
        rows.append(
            ArtifactRow(
                source_pdf=str(source_pdf),
                package_dir=str(package_dir),
                kind="drawing",
                item="page_01",
                ok=True,
                layout_similarity=float(best.get("layout_similarity", 0.0)),
                selected_variant=str(best.get("variant", "") or ""),
                source_fidelity_score=float(decision["source_fidelity_score"]),
                fragmentation_score=float(decision["fragmentation_score"]),
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
                pen_down_strokes=int(metrics.get("pen_down_strokes", 0)),
                tiny_strokes_lt_08_mm=int(metrics.get("tiny_strokes_lt_08_mm", 0)),
                point_like_strokes=int(metrics.get("point_like_strokes", 0)),
                bounds=_bounds_text(metrics),
                nc=str(best_prefix.with_suffix(".nc")),
                gcode=str(best_prefix.with_suffix(".gcode")),
                preview_pdf=str(best_prefix.with_suffix(".pdf")),
                preview_svg=str(best_prefix.with_suffix(".svg")),
                notes="; ".join(
                    part
                    for part in [
                        f"variant={best.get('variant')}",
                        f"scale={best.get('fit_scale')}",
                        f"clipping={bool(best.get('clipping_warning'))}",
                        str(best.get("notes", "")),
                    ]
                    if part
                ),
            )
        )
        shutil.rmtree(candidate_root, ignore_errors=True)
        _mirror_package_root_artifacts(package_dir, rows)
        doc.close()
        return report, rows

    if not is_a3 and not is_large_custom and not literal_one_to_one_tiled:
        frame_class = _drawing_frame_class(source_pdf)
        candidate_root = package_dir / "_candidates"
        candidate_root.mkdir(parents=True, exist_ok=True)
        candidates: list[dict[str, Any]] = []
        candidate_builders: list[tuple[str, Callable[[], dict[str, Any]]]] = []
        if frame_class == "standard_frame":
            if _prefer_direct_fit_full_for_nachert_a4(source_pdf):
                candidate_builders.extend(
                    [
                        (
                            "fit_full",
                            lambda: _prepare_compact_source_overlay_candidate(
                                source_pdf,
                                variant_name="fit_full",
                                candidate_dir=candidate_root,
                            ),
                        ),
                        (
                            "mupdf_svg_paths",
                            lambda: _prepare_mupdf_svg_paths_candidate(
                                source_pdf,
                                variant_name="mupdf_svg_paths",
                                candidate_dir=candidate_root,
                            ),
                        ),
                    ]
                )
            else:
                candidate_builders.append(
                    (
                        "a4_hybrid_frame",
                        lambda: _prepare_a4_hybrid_drawing_candidate(
                            source_pdf,
                            variant_name="a4_hybrid_frame",
                            candidate_dir=candidate_root,
                        ),
                    )
                )
        elif frame_class == "kompas_full_frame":
            candidate_builders.extend(
                [
                    (
                        "fit_full",
                        lambda: _prepare_drawing_candidate(
                            source_pdf,
                            variant_name="fit_full",
                            exact_geometry_mode=False,
                            strict_one_to_one=False,
                            candidate_dir=candidate_root,
                            image_contours_mode="off",
                            disable_small_lineart_circle_recovery=False,
                        ),
                    ),
                    (
                        "mupdf_svg_paths",
                        lambda: _prepare_mupdf_svg_paths_candidate(
                            source_pdf,
                            variant_name="mupdf_svg_paths",
                            candidate_dir=candidate_root,
                        ),
                    ),
                ]
            )
        else:
            candidate_builders.extend(
                [
                    (
                        "a4_hybrid_frame",
                        lambda: _prepare_a4_hybrid_drawing_candidate(
                            source_pdf,
                            variant_name="a4_hybrid_frame",
                            candidate_dir=candidate_root,
                        ),
                    ),
                    (
                        "fit_full",
                        lambda: _prepare_compact_source_overlay_candidate(
                            source_pdf,
                            variant_name="fit_full",
                            candidate_dir=candidate_root,
                        )
                        if _prefer_direct_fit_full_for_nachert_variant4_a4(source_pdf)
                        else _prepare_drawing_candidate(
                            source_pdf,
                            variant_name="fit_full",
                            exact_geometry_mode=False,
                            strict_one_to_one=False,
                            candidate_dir=candidate_root,
                            image_contours_mode="off",
                            disable_small_lineart_circle_recovery=False,
                        ),
                    ),
                    (
                        "mupdf_svg_paths",
                        lambda: _prepare_mupdf_svg_paths_candidate(
                            source_pdf,
                            variant_name="mupdf_svg_paths",
                            candidate_dir=candidate_root,
                        ),
                    ),
                ]
            )
        if frame_class != "kompas_full_frame":
            candidate_builders.append(
                (
                    "strict_1to1_clip",
                    lambda: _prepare_drawing_candidate(
                        source_pdf,
                        variant_name="strict_1to1_clip",
                        exact_geometry_mode=True,
                        strict_one_to_one=True,
                        candidate_dir=candidate_root,
                    ),
                )
            )
        for variant_name, fn in candidate_builders:
            try:
                candidates.append(fn())
            except Exception as exc:
                candidates.append(
                    {
                        "variant": variant_name,
                        "ok": False,
                        "message": str(exc),
                        "logs": [f"A4 candidate failed: {variant_name}: {exc}"],
                    }
                )
        successful = [row for row in candidates if bool(row.get("ok"))]
        if not successful:
            report["items"] = candidates
            doc.close()
            return report, rows

        if _is_specification_like_drawing(source_pdf):
            hybrid_ref_pdf: Path | None = None
            hybrid_ref_svg: Path | None = None
            for row in successful:
                if str(row.get("variant", "")) != "a4_hybrid_frame":
                    continue
                ref_pdf_raw = str(row.get("reference_source", "") or "").strip()
                ref_svg_raw = str(row.get("reference_source_svg", "") or "").strip()
                if ref_pdf_raw:
                    hybrid_ref_pdf = Path(ref_pdf_raw)
                if ref_svg_raw:
                    hybrid_ref_svg = Path(ref_svg_raw)
                break
            if hybrid_ref_pdf is not None and hybrid_ref_pdf.exists():
                try:
                    candidates.append(
                        _prepare_reference_pdf_candidate(
                            hybrid_ref_pdf,
                            reference_pdf=hybrid_ref_pdf,
                            reference_svg=hybrid_ref_svg,
                            variant_name="clean_source_direct",
                            candidate_dir=candidate_root,
                        )
                    )
                except Exception as exc:
                    candidates.append(
                        {
                            "variant": "clean_source_direct",
                            "ok": False,
                            "message": str(exc),
                            "logs": [f"A4 candidate failed: clean_source_direct: {exc}"],
                        }
                    )
                successful = [row for row in candidates if bool(row.get("ok"))]

        for row in successful:
            try:
                crop_metrics = _source_crop_alignment_metrics(
                    source_pdf,
                    Path(str(row.get("pdf", ""))),
                    source_page_index=0,
                )
            except Exception:
                crop_metrics = {
                    "source_crop_corr": 0.0,
                    "source_crop_iou": 0.0,
                    "source_crop_x_px": 0.0,
                    "source_crop_y_px": 0.0,
                }
            row.update(crop_metrics)

        best, decision = _select_best_a4_drawing_candidate(source_pdf, successful)
        best_prefix = pages_dir / "page_01"
        for src_key, dst_path in zip(
            ["svg", "pdf", "nc", "gcode"],
            _bridge_preview_copy_targets(best_prefix),
        ):
            _copy_file(Path(str(best[src_key])), dst_path)
        chosen_logs = list(best.get("logs", []))
        preview_ok, preview_err = _rewrite_preview_on_work_area_canvas_from_gcode(
            gcode_path=best_prefix.with_suffix(".nc"),
            out_svg=best_prefix.with_suffix(".svg"),
            out_pdf=best_prefix.with_suffix(".pdf"),
            logs=chosen_logs,
        )
        if not preview_ok:
            report["items"] = candidates
            report.update(decision)
            report["selected_layout_similarity"] = best.get("layout_similarity")
            doc.close()
            return report, rows
        _write_text(logs_dir / "page_01.log.txt", "\n".join(chosen_logs) + ("\n" if chosen_logs else ""))
        report["items"] = candidates
        report.update(decision)
        report["selected_layout_similarity"] = best.get("layout_similarity")
        ref_pdf_raw = str(best.get("reference_source", "") or best.get("pdf", "") or "").strip()
        ref_svg_raw = str(best.get("reference_source_svg", "") or best.get("svg", "") or "").strip()
        if ref_pdf_raw:
            ref_pdf_dst = package_dir / "a4_clean_source.pdf"
            ref_svg_dst = package_dir / "a4_clean_source.svg"
            _copy_file(Path(ref_pdf_raw), ref_pdf_dst)
            if ref_svg_raw:
                _copy_file(Path(ref_svg_raw), ref_svg_dst)
            report["a4_clean_source"] = {
                "pdf": str(ref_pdf_dst),
                "svg": str(ref_svg_dst),
            }
        metrics = dict(best.get("metrics", {}))
        rows.append(
            ArtifactRow(
                source_pdf=str(source_pdf),
                package_dir=str(package_dir),
                kind="drawing",
                item="page_01",
                ok=True,
                layout_similarity=float(best.get("layout_similarity", 0.0)),
                selected_variant=str(best.get("variant", "") or ""),
                source_fidelity_score=float(decision["source_fidelity_score"]),
                fragmentation_score=float(decision["fragmentation_score"]),
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
                pen_down_strokes=int(metrics.get("pen_down_strokes", 0)),
                tiny_strokes_lt_08_mm=int(metrics.get("tiny_strokes_lt_08_mm", 0)),
                point_like_strokes=int(metrics.get("point_like_strokes", 0)),
                bounds=_bounds_text(metrics),
                nc=str(best_prefix.with_suffix(".nc")),
                gcode=str(best_prefix.with_suffix(".gcode")),
                preview_pdf=str(best_prefix.with_suffix(".pdf")),
                preview_svg=str(best_prefix.with_suffix(".svg")),
                notes="; ".join(
                    part
                    for part in [
                        f"variant={best.get('variant')}",
                        f"scale={best.get('fit_scale')}",
                        f"clipping={bool(best.get('clipping_warning'))}",
                        f"source_crop_iou={float(best.get('source_crop_iou', 0.0) or 0.0):.6f}",
                        f"source_crop_corr={float(best.get('source_crop_corr', 0.0) or 0.0):.6f}",
                        str(best.get("notes", "")),
                    ]
                    if part
                ),
            )
        )
        shutil.rmtree(candidate_root, ignore_errors=True)
        _mirror_package_root_artifacts(package_dir, rows)
        doc.close()
        return report, rows

    a3_clean_logs: list[str] = []
    clean_svg = package_dir / "_candidates" / "a3_clean_source.svg"
    clean_preview_pdf = package_dir / "_candidates" / "a3_clean_source.pdf"
    clean_svg.parent.mkdir(parents=True, exist_ok=True)
    literal_tiling: dict[str, Any] | None = None
    if literal_one_to_one_tiled:
        literal_tiling = plan_tiled_passes_for_sheet(
            page_w_mm,
            page_h_mm,
            area_w_mm=180.0,
            area_h_mm=280.0,
        )
        ok_clean, msg_clean, clean_logs = _prepare_literal_clean_source_svg(
            source_pdf,
            source_svg=clean_svg,
            source_preview_pdf=clean_preview_pdf,
            rotate_90=bool(literal_tiling.get("rotated")),
        )
    else:
        ok_clean, msg_clean, clean_logs = _prepare_a3_clean_source_svg(
            source_pdf,
            source_svg=clean_svg,
            source_preview_pdf=clean_preview_pdf,
        )
    if ok_clean:
        a3_clean_logs = list(clean_logs)
        report["a3_clean_source"] = {
            "ok": True,
            "svg": str(clean_svg),
            "pdf": str(clean_preview_pdf),
        }
    else:
        report["a3_clean_source"] = {
            "ok": False,
            "message": msg_clean,
            "logs": clean_logs,
        }

    a3_selected_variant = "a3_two_pass_clean_source" if ok_clean else "a3_two_pass_direct"
    a3_selection_reason = "forced_a3_two_pass" if forced_a3_two_pass else ("a3_two_pass_clean_source" if ok_clean else "a3_two_pass_direct")
    a3_title_block_strategy = (
        "source_vector_with_stamp_title_text_repair"
        if _logs_indicate_kompas_stamp_text_repair(a3_clean_logs)
        else "source_vector_as_path"
    )
    a3_route_notes = "kompas_stamp_text_repair=True" if _logs_indicate_kompas_stamp_text_repair(a3_clean_logs) else ""
    a3_route_class = _candidate_route_class(
        source_pdf,
        {"variant": a3_selected_variant, "notes": a3_route_notes},
        is_a3=True,
        forced_a3_two_pass=forced_a3_two_pass,
    )

    if is_large_custom or literal_one_to_one_tiled:
        a3_selected_variant = "custom_tiled_clean_source" if ok_clean else "custom_tiled_direct"
        a3_selection_reason = "literal_one_to_one_tiled" if literal_one_to_one_tiled else "custom_tiled_large_sheet"
        a3_route_class = "A3 tiled drawing"
        tiling = literal_tiling if literal_tiling is not None else plan_tiled_passes_for_sheet(
            page_w_mm,
            page_h_mm,
            area_w_mm=180.0,
            area_h_mm=280.0,
        )
        report["sheet_tiling"] = dict(tiling)
        pass_cols = int(tiling.get("nx", 1) or 1)
        pass_rows = int(tiling.get("ny", 1) or 1)
        tiled_sheet_w_mm = float(tiling.get("sheet_w_mm", page_w_mm) or page_w_mm)
        tiled_sheet_h_mm = float(tiling.get("sheet_h_mm", page_h_mm) or page_h_mm)
        pass_index = 0
        for pass_row in range(1, pass_rows + 1):
            for pass_col in range(1, pass_cols + 1):
                pass_index += 1
                prefix = pages_dir / f"pass_{pass_index:02d}"
                row = _prepare_tiled_pass_from_clean_svg(
                    clean_svg,
                    source_pdf=source_pdf,
                    pass_index=pass_index,
                    pass_cols=pass_cols,
                    pass_rows=pass_rows,
                    pass_col=pass_col,
                    pass_row=pass_row,
                    sheet_w_mm=tiled_sheet_w_mm,
                    sheet_h_mm=tiled_sheet_h_mm,
                    prefix=prefix,
                    prep_logs=a3_clean_logs,
                ) if ok_clean else {
                    "item": f"pass_{pass_index:02d}",
                    "ok": False,
                    "message": "Clean source preparation failed for tiled large-sheet route.",
                    "logs": [*clean_logs],
                }
                report["items"].append(row)
                logs = list(row.get("logs", []))
                _write_text(logs_dir / f"pass_{pass_index:02d}.log.txt", "\n".join(logs) + ("\n" if logs else ""))
                if not bool(row.get("ok")):
                    rows.append(
                        ArtifactRow(
                            source_pdf=str(source_pdf),
                            package_dir=str(package_dir),
                            kind="drawing",
                            item=f"pass_{pass_index:02d}",
                            ok=False,
                            layout_similarity=None,
                            selected_variant=a3_selected_variant,
                            source_fidelity_score=None,
                            fragmentation_score=None,
                            draw_length_m=None,
                            segments_total=None,
                            pen_down_strokes=None,
                            tiny_strokes_lt_08_mm=None,
                            point_like_strokes=None,
                            bounds="",
                            nc="",
                            gcode="",
                            preview_pdf="",
                            preview_svg="",
                            notes=str(row.get("message", "")),
                        )
                    )
                    continue
                metrics = dict(row.get("metrics", {}))
                rows.append(
                    ArtifactRow(
                        source_pdf=str(source_pdf),
                        package_dir=str(package_dir),
                        kind="drawing",
                        item=f"pass_{pass_index:02d}",
                        ok=True,
                        layout_similarity=None,
                        selected_variant=a3_selected_variant,
                        source_fidelity_score=None,
                        fragmentation_score=None,
                        draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                        segments_total=int(metrics.get("segments_total", 0)),
                        pen_down_strokes=int(metrics.get("pen_down_strokes", 0)),
                        tiny_strokes_lt_08_mm=int(metrics.get("tiny_strokes_lt_08_mm", 0)),
                        point_like_strokes=int(metrics.get("point_like_strokes", 0)),
                        bounds=_bounds_text(metrics),
                        nc=str(prefix.with_suffix(".nc")),
                        gcode=str(prefix.with_suffix(".gcode")),
                        preview_pdf=str(prefix.with_suffix(".pdf")),
                        preview_svg=str(prefix.with_suffix(".svg")),
                        notes="; ".join(
                            part
                            for part in [
                                f"scale={row.get('fit_scale')}",
                                f"clipping={bool(row.get('clipping_warning'))}",
                                str(row.get("notes", "")),
                            ]
                            if part
                        ),
                    )
                )
        combined_preview = _build_tiled_combined_preview(
            source_pdf=source_pdf,
            package_dir=package_dir,
            report=report,
        )
        if combined_preview:
            report["combined_preview"] = combined_preview
            source_fidelity_score = round(float(combined_preview.get("layout_similarity", 0.0) or 0.0), 6)
        else:
            source_fidelity_score = None
        aggregate_metrics, fragmentation_score = _aggregate_row_fragmentation(rows)
        report.update(
            {
                "selected_variant": a3_selected_variant,
                "selected_layout_similarity": source_fidelity_score,
                "selection_reason": a3_selection_reason,
                "source_fidelity_score": source_fidelity_score,
                "fragmentation_score": fragmentation_score,
                "title_block_strategy": a3_title_block_strategy,
                "route_class": a3_route_class,
            }
        )
        for row in rows:
            if str(row.package_dir) != str(package_dir):
                continue
            row.source_fidelity_score = source_fidelity_score
            row.fragmentation_score = fragmentation_score
        _mirror_package_root_artifacts(package_dir, rows)
        if combined_preview:
            for artifact_key in ("pdf", "svg"):
                artifact_path = Path(str(combined_preview[artifact_key]))
                if artifact_path.exists() and artifact_path.is_file():
                    dst_path = package_dir / artifact_path.name
                    if artifact_path.resolve() != dst_path.resolve():
                        _copy_file(artifact_path, dst_path)
        doc.close()
        return report, rows

    for pass_index in (1, 2):
        prefix = pages_dir / f"pass_{pass_index:02d}"
        if ok_clean:
            row = _prepare_a3_pass_from_clean_svg(
                clean_svg,
                source_pdf=source_pdf,
                pass_index=pass_index,
                prefix=prefix,
                prep_logs=a3_clean_logs,
            )
        else:
            row = _prepare_a3_pass(source_pdf, pass_index=pass_index, prefix=prefix)
        report["items"].append(row)
        logs = list(row.get("logs", []))
        _write_text(logs_dir / f"pass_{pass_index:02d}.log.txt", "\n".join(logs) + ("\n" if logs else ""))
        if not bool(row.get("ok")):
            rows.append(
                ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="drawing",
                    item=f"pass_{pass_index:02d}",
                    ok=False,
                    layout_similarity=None,
                    selected_variant=a3_selected_variant,
                    source_fidelity_score=None,
                    fragmentation_score=None,
                    draw_length_m=None,
                    segments_total=None,
                    pen_down_strokes=None,
                    tiny_strokes_lt_08_mm=None,
                    point_like_strokes=None,
                    bounds="",
                    nc="",
                    gcode="",
                    preview_pdf="",
                    preview_svg="",
                    notes=str(row.get("message", "")),
                )
            )
            continue
        metrics = dict(row.get("metrics", {}))
        rows.append(
            ArtifactRow(
                source_pdf=str(source_pdf),
                package_dir=str(package_dir),
                kind="drawing",
                item=f"pass_{pass_index:02d}",
                ok=True,
                layout_similarity=None,
                selected_variant=a3_selected_variant,
                source_fidelity_score=None,
                fragmentation_score=None,
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
                pen_down_strokes=int(metrics.get("pen_down_strokes", 0)),
                tiny_strokes_lt_08_mm=int(metrics.get("tiny_strokes_lt_08_mm", 0)),
                point_like_strokes=int(metrics.get("point_like_strokes", 0)),
                bounds=_bounds_text(metrics),
                nc=str(prefix.with_suffix(".nc")),
                gcode=str(prefix.with_suffix(".gcode")),
                preview_pdf=str(prefix.with_suffix(".pdf")),
                preview_svg=str(prefix.with_suffix(".svg")),
                notes="; ".join(
                    part
                    for part in [
                        f"scale={row.get('fit_scale')}",
                        f"clipping={bool(row.get('clipping_warning'))}",
                        str(row.get("notes", "")),
                    ]
                    if part
                ),
            )
        )
    combined_preview = _build_a3_combined_preview(
        source_pdf=source_pdf,
        package_dir=package_dir,
        report=report,
    )
    if combined_preview:
        report["combined_preview"] = combined_preview
        source_fidelity_score = round(float(combined_preview.get("layout_similarity", 0.0) or 0.0), 6)
    else:
        source_fidelity_score = None
    aggregate_metrics, fragmentation_score = _aggregate_row_fragmentation(rows)
    report.update(
        {
            "selected_variant": a3_selected_variant,
            "selected_layout_similarity": source_fidelity_score,
            "selection_reason": a3_selection_reason,
            "source_fidelity_score": source_fidelity_score,
            "fragmentation_score": fragmentation_score,
            "title_block_strategy": a3_title_block_strategy,
            "route_class": a3_route_class,
        }
    )
    for row in rows:
        if str(row.package_dir) != str(package_dir):
            continue
        row.source_fidelity_score = source_fidelity_score
        row.fragmentation_score = fragmentation_score
    _mirror_package_root_artifacts(package_dir, rows)
    if combined_preview:
        for artifact_key in ("pdf", "svg"):
            artifact_path = Path(str(combined_preview[artifact_key]))
            if artifact_path.exists() and artifact_path.is_file():
                dst_path = package_dir / artifact_path.name
                if artifact_path.resolve() != dst_path.resolve():
                    _copy_file(artifact_path, dst_path)
    doc.close()
    return report, rows


def _prepare_toe_package(source_pdf: Path, package_dir: Path) -> tuple[dict[str, Any], list[ArtifactRow]]:
    pages_dir = package_dir / "pages"
    logs_dir = package_dir / "logs"
    temp_svg_dir = package_dir / "_page_svg"
    _ensure_clean_dir(package_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    temp_svg_dir.mkdir(parents=True, exist_ok=True)

    profile = toe_font_policy.toe_profile_for_source_stem(source_pdf.stem)
    font_label, font_filename = profile.label, profile.filename
    font_path = PROJECT_ROOT / "data" / "fonts" / font_filename
    doc = fitz.open(source_pdf)
    rows: list[ArtifactRow] = []
    report: dict[str, Any] = {
        "source_pdf": str(source_pdf),
        "kind": "toe_handwriting",
        "page_count": int(doc.page_count),
        "font_label": font_label,
        "font_path": str(font_path),
        "items": [],
    }

    for page_index in range(1, int(doc.page_count) + 1):
        page_svg = temp_svg_dir / f"page_{page_index:02d}.svg"
        _export_pdf_page_to_mupdf_svg(source_pdf, page_index - 1, page_svg)
        prefix = pages_dir / f"page_{page_index:02d}"
        row = _prepare_toe_page(
            source_pdf=source_pdf,
            page_index=page_index,
            page_svg=page_svg,
            font_label=font_label,
            font_path=font_path,
            prefix=prefix,
        )
        report["items"].append(row)
        logs = list(row.get("logs", []))
        _write_text(logs_dir / f"page_{page_index:02d}.log.txt", "\n".join(logs) + ("\n" if logs else ""))
        if not bool(row.get("ok")):
            rows.append(
                ArtifactRow(
                    source_pdf=str(source_pdf),
                    package_dir=str(package_dir),
                    kind="toe_handwriting",
                    item=f"page_{page_index:02d}",
                    ok=False,
                    layout_similarity=None,
                    selected_variant="",
                    source_fidelity_score=None,
                    fragmentation_score=None,
                    draw_length_m=None,
                    segments_total=None,
                    pen_down_strokes=None,
                    tiny_strokes_lt_08_mm=None,
                    point_like_strokes=None,
                    bounds="",
                    nc="",
                    gcode="",
                    preview_pdf="",
                    preview_svg="",
                    notes=str(row.get("message", "")),
                )
            )
            continue
        metrics = dict(row.get("metrics", {}))
        rows.append(
            ArtifactRow(
                source_pdf=str(source_pdf),
                package_dir=str(package_dir),
                kind="toe_handwriting",
                item=f"page_{page_index:02d}",
                ok=True,
                layout_similarity=float(row.get("layout_similarity", 0.0)),
                selected_variant="toe_font_first",
                source_fidelity_score=float(row.get("layout_similarity", 0.0)),
                fragmentation_score=_candidate_fragmentation_score(metrics),
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
                pen_down_strokes=int(metrics.get("pen_down_strokes", 0)),
                tiny_strokes_lt_08_mm=int(metrics.get("tiny_strokes_lt_08_mm", 0)),
                point_like_strokes=int(metrics.get("point_like_strokes", 0)),
                bounds=_bounds_text(metrics),
                nc=str(prefix.with_suffix(".nc")),
                gcode=str(prefix.with_suffix(".gcode")),
                preview_pdf=str(prefix.with_suffix(".pdf")),
                preview_svg=str(prefix.with_suffix(".svg")),
                notes="; ".join(part for part in [f"font={font_label}", str(row.get("notes", ""))] if part),
            )
        )

    _mirror_package_root_artifacts(package_dir, rows)
    doc.close()
    return report, rows


def _iter_source_pdfs(folder: Path, only_filters: list[str]) -> list[Path]:
    pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.name.lower())
    if not only_filters:
        return pdfs
    out: list[Path] = []
    filters = [item.lower() for item in only_filters]
    for pdf in pdfs:
        name = pdf.name.lower()
        if any(token in name for token in filters):
            out.append(pdf)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare preview/G-code packages for PDFs in folder 1.")
    parser.add_argument("--folder", default="1", help="Folder with source PDFs, relative to project root.")
    parser.add_argument("--only", nargs="*", default=[], help="Optional substrings to filter source PDF names.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip package dirs that already exist.")
    args = parser.parse_args()

    folder = (PROJECT_ROOT / args.folder).resolve()
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    pdfs = _iter_source_pdfs(folder, list(args.only or []))
    if not pdfs:
        print("No PDF files matched.")
        return 0

    started_at = time.time()
    all_rows: list[ArtifactRow] = []
    all_reports: list[dict[str, Any]] = []

    for idx, pdf_path in enumerate(pdfs, start=1):
        package_dir = pdf_path.parent / f"{pdf_path.stem}_pack"
        if args.skip_existing and package_dir.exists():
            print(f"[{idx}/{len(pdfs)}] skip existing: {pdf_path.name}")
            all_rows.extend(_read_rows_from_csv(package_dir / "summary.csv"))
            report_path = package_dir / "report.json"
            if report_path.exists():
                existing_report = json.loads(report_path.read_text(encoding="utf-8"))
                existing_report.setdefault("package_dir", str(package_dir))
                all_reports.append(existing_report)
            continue

        print(f"[{idx}/{len(pdfs)}] processing: {pdf_path.name}")
        if pdf_path.name.startswith("TOE_"):
            report, rows = _prepare_toe_package(pdf_path, package_dir)
        else:
            report, rows = _prepare_drawing_package(pdf_path, package_dir)

        report["package_dir"] = str(package_dir)
        compare_meta = _generate_package_compare_artifacts(package_dir, report, rows)
        report["compare_generated"] = bool(compare_meta.get("compare_generated"))
        if "compare" in compare_meta:
            report["compare"] = dict(compare_meta.get("compare", {}) or {})
        if str(compare_meta.get("compare_error", "")).strip():
            report["compare_error"] = str(compare_meta.get("compare_error", ""))
        _write_json(package_dir / "report.json", report)
        if rows:
            _write_csv(package_dir / "summary.csv", rows)
        all_rows.extend(rows)
        all_reports.append(report)
        ok_count = sum(1 for row in rows if row.ok)
        print(f"    items ok: {ok_count}/{len(rows)}")

    summary_path = folder / "_prepared_summary.csv"
    reports_path = folder / "_prepared_reports.json"
    if args.only:
        touched_pdfs = {str(row.source_pdf) for row in all_rows}
        touched_pdfs.update(str(report.get("source_pdf", "")) for report in all_reports if str(report.get("source_pdf", "")).strip())
        if summary_path.exists():
            existing_rows = _read_rows_from_csv(summary_path)
            all_rows = [row for row in existing_rows if str(row.source_pdf) not in touched_pdfs] + all_rows
        if reports_path.exists():
            try:
                existing_reports = list((json.loads(reports_path.read_text(encoding="utf-8")) or {}).get("reports", []) or [])
            except Exception:
                existing_reports = []
            all_reports = [report for report in existing_reports if str(report.get("source_pdf", "")).strip() not in touched_pdfs] + all_reports
    if all_rows:
        _write_csv(summary_path, all_rows)
    _write_root_drawing_audit(folder, all_rows, all_reports)
    _write_json(reports_path, {"generated_at_epoch": started_at, "reports": all_reports})
    elapsed = time.time() - started_at
    print(f"done in {elapsed / 60.0:.1f} min")
    print(f"summary: {summary_path}")
    print(f"reports: {reports_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
