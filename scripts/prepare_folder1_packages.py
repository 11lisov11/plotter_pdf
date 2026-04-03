from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
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
from typing import Any

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
_TECH_POINT_BOX_MIN_MM = 0.75
_TECH_POINT_BOX_MAX_MM = 2.40
_TECH_POINT_BOX_MAX_ASPECT = 1.35
_TECH_POINT_BOX_CLOSURE_EPS_MM = 0.20
_TECH_POINT_BOX_AXIS_EPS_MM = 0.18
_TECH_POINT_BOX_DOT_MIN_R_MM = 0.20
_TECH_POINT_BOX_DOT_MAX_R_MM = 0.34
_TECH_POINT_BOX_DOT_SEGMENTS = 10
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
_A4_HEADER_TEXT_GAP_MM = 4.0
_A4_HEADER_TEXT_SCALE = 0.92
_A4_HEADER_VARIANT1_THUMB_TARGET_MIN_W_MM = _A4_HEADER_THUMB_TARGET_MIN_W_MM
_A4_HEADER_VARIANT1_TEXT_GAP_MM = _A4_HEADER_TEXT_GAP_MM
_A4_HEADER_VARIANT1_TEXT_SCALE = _A4_HEADER_TEXT_SCALE


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
    draw_length_m: float | None
    segments_total: int | None
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
                    draw_length_m=None
                    if str(raw.get("draw_length_m", "")).strip() in {"", "None"}
                    else float(str(raw.get("draw_length_m", "0"))),
                    segments_total=None
                    if str(raw.get("segments_total", "")).strip() in {"", "None"}
                    else int(str(raw.get("segments_total", "0"))),
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


def _render_pdf_page_gray(pdf_path: Path, page_index: int = 0, dpi: int = 140) -> np.ndarray:
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    zoom = float(dpi) / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


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


def _layout_similarity_pdf(source_pdf: Path, preview_pdf: Path, source_page_index: int = 0) -> float:
    src = _crop_content(_render_pdf_page_gray(source_pdf, page_index=source_page_index))
    cur = _crop_content(_render_pdf_page_gray(preview_pdf, page_index=0))
    size = (512, 512)
    src = cv2.resize(src, size, interpolation=cv2.INTER_AREA)
    cur = cv2.resize(cur, size, interpolation=cv2.INTER_AREA)
    src = cv2.GaussianBlur(src, (0, 0), 1.2)
    cur = cv2.GaussianBlur(cur, (0, 0), 1.2)
    score = 1.0 - float(np.mean(np.abs(src.astype(np.float32) - cur.astype(np.float32))) / 255.0)
    return round(score, 6)


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
    logger,
) -> list[list[tuple[float, float]]]:
    if not header_lines:
        return []
    resolve_ttf = getattr(backend, "_resolve_handwriting_ttf_path", lambda _font: None)
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
            fit_scale = min((float(target_w) * 0.985) / actual_w, (float(target_h) * 0.94) / actual_h, 1.0)
            if abs(float(fit_scale) - 1.0) > 1e-6:
                line_polys = [
                    [((float(x) - float(ax0)) * float(fit_scale), (float(y) - float(ay0)) * float(fit_scale)) for x, y in poly]
                    for poly in line_polys
                ]
                ax0, ay0, ax1, ay1 = _polys_bbox_mm(line_polys)
                actual_w = max(1e-6, float(ax1 - ax0))
                actual_h = max(1e-6, float(ay1 - ay0))
            pad_x_u = max(0.0, (float(target_w) - actual_w) * 0.03)
            pad_y_u = max(0.0, (float(target_h) - actual_h) * 0.06)
            shift_x = float(target_x0) - float(ax0) + float(pad_x_u)
            shift_y = float(target_y0) - float(ay0) + float(pad_y_u)
            line_polys = [[(float(x) + float(shift_x), float(y) + float(shift_y)) for x, y in poly] for poly in line_polys]
            for poly in line_polys:
                if len(poly) >= 2:
                    out.append(poly)
        return out
    finally:
        setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", prev_ttf_backend)


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
    xs: list[float] = []
    ys: list[float] = []
    seen: dict[tuple[tuple[float, float], tuple[float, float]], int] = {}
    for poly in polylines:
        if len(poly) < 2:
            continue
        total_draw_len += _polyline_length(poly)
        for idx in range(1, len(poly)):
            a = poly[idx - 1]
            b = poly[idx]
            total_segments += 1
            seen[_segment_key(a, b)] = seen.get(_segment_key(a, b), 0) + 1
            xs.extend([float(a[0]), float(b[0])])
            ys.extend([float(a[1]), float(b[1])])
    duplicate_segments = sum(max(0, cnt - 1) for cnt in seen.values())
    return {
        "draw_length_mm": round(total_draw_len, 3),
        "segments_total": int(total_segments),
        "segments_duplicate": int(duplicate_segments),
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
    if fit_match is None or pass_match is None:
        raise ValueError(f"Cannot parse A3 pass transform from log: {log_path}")
    area_match = _A3_AREA_RE.search(text)
    if area_match is not None:
        area_min_x, area_max_x, area_min_y, area_max_y = [float(area_match.group(i)) for i in range(1, 5)]
    else:
        area_min_x, area_max_x, area_min_y, area_max_y = backend.work_area_bounds()
    translate_match = _A3_POST_TRANSLATE_RE.search(text)
    post_tx = float(translate_match.group(1)) if translate_match is not None else 0.0
    post_ty = float(translate_match.group(2)) if translate_match is not None else 0.0
    return {
        "scale": float(fit_match.group(1)),
        "fit_tx": float(fit_match.group(2)),
        "fit_ty": float(fit_match.group(3)),
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


def _build_a3_combined_preview(
    *,
    source_pdf: Path,
    package_dir: Path,
    report: dict[str, Any],
) -> dict[str, Any] | None:
    pass01_nc = package_dir / "pages" / "pass_01.nc"
    pass02_nc = package_dir / "pages" / "pass_02.nc"
    pass01_log = package_dir / "logs" / "pass_01.log.txt"
    pass02_log = package_dir / "logs" / "pass_02.log.txt"
    if not all(path.exists() for path in (pass01_nc, pass02_nc, pass01_log, pass02_log)):
        return None

    reference_pdf = source_pdf
    clean_meta = dict(report.get("a3_clean_source", {}) or {})
    clean_pdf_str = str(clean_meta.get("pdf", "") or "").strip()
    if clean_pdf_str:
        clean_pdf = Path(clean_pdf_str)
        if clean_pdf.exists() and clean_pdf.is_file():
            reference_pdf = clean_pdf

    polylines = [
        *_inverse_a3_pass_polylines_to_sheet(nc_path=pass01_nc, log_path=pass01_log),
        *_inverse_a3_pass_polylines_to_sheet(nc_path=pass02_nc, log_path=pass02_log),
    ]
    if not polylines:
        return None

    ref_w_mm, ref_h_mm = _pdf_first_page_size_mm(reference_pdf)
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
        }
        try:
            setattr(backend, "HANDWRITING_TEXT_ENABLED", True)
            setattr(backend, "HANDWRITING_SINGLELINE_TTF_BACKEND", "autotrace3")
            setattr(backend, "IMAGE_CONTOUR_ENABLED", True)
            setattr(backend, "IMAGE_CONTOUR_WORD_ONLY", False)
            setattr(backend, "IMAGE_CONTOUR_MODE", "always")
            setattr(backend, "IMAGE_CONTOUR_VECTORIZE_MODE", "centerline")
            setattr(backend, "IMAGE_CONTOUR_FORMULA_VECTORIZE_MODE", "centerline")
            with tempfile.TemporaryDirectory(prefix="plotter_condimg_") as td:
                td_path = Path(td)
                for img_idx, img in enumerate(page.get_images(full=True)):
                    xref = int(img[0])
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
                        if not _is_small_condition_image_rect_mm(x0_mm, y0_mm, x1_mm, y1_mm):
                            continue

                        png_path = td_path / f"condimg_{img_idx}_{rect_idx}.png"
                        svg_path = td_path / f"condimg_{img_idx}_{rect_idx}.svg"
                        page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), clip=rect, alpha=False).save(png_path)
                        svg_path.write_text(
                            "\n".join(
                                [
                                    '<?xml version="1.0" encoding="UTF-8"?>',
                                    '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"',
                                    f'     width="{page_w_mm:.3f}mm" height="{page_h_mm:.3f}mm" viewBox="0 0 {page_w_mm:.6f} {page_h_mm:.6f}">',
                                    f'  <image href="{png_path.name}" x="{x0_mm:.4f}" y="{y0_mm:.4f}" width="{(x1_mm - x0_mm):.4f}" height="{(y1_mm - y0_mm):.4f}" preserveAspectRatio="none" />',
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


def _is_technical_point_box_poly(poly: list[tuple[float, float]]) -> bool:
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
    if w < float(_TECH_POINT_BOX_MIN_MM) or h < float(_TECH_POINT_BOX_MIN_MM):
        return False
    if w > float(_TECH_POINT_BOX_MAX_MM) or h > float(_TECH_POINT_BOX_MAX_MM):
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
        if _is_technical_point_box_poly(poly) and _is_detail_polyline_mm(
            poly,
            page_w_mm=float(page_w_mm),
            page_h_mm=float(page_h_mm),
            crop_left_mm=float(getattr(backend, "PAGE_MARGIN_LEFT_MM", 0.0)),
            crop_right_mm=float(getattr(backend, "PAGE_MARGIN_RIGHT_MM", 0.0)),
            crop_top_mm=float(getattr(backend, "PAGE_MARGIN_TOP_MM", 0.0)),
            crop_bottom_mm=float(getattr(backend, "PAGE_MARGIN_BOTTOM_MM", 0.0)),
        ):
            out.append(_technical_point_dot_poly_from_box(poly))
            replaced += 1
            continue
        if idx in candidate_info and _is_detail_polyline_mm(
            poly,
            page_w_mm=float(page_w_mm),
            page_h_mm=float(page_h_mm),
            crop_left_mm=float(getattr(backend, "PAGE_MARGIN_LEFT_MM", 0.0)),
            crop_right_mm=float(getattr(backend, "PAGE_MARGIN_RIGHT_MM", 0.0)),
            crop_top_mm=float(getattr(backend, "PAGE_MARGIN_TOP_MM", 0.0)),
            crop_bottom_mm=float(getattr(backend, "PAGE_MARGIN_BOTTOM_MM", 0.0)),
        ):
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
    header_thumb_content_scale_x: float | None = None,
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
        header_text_src_x0 = max(float(header_thumb_divider_x) + 4.0, float(_A4_HEADER_TEXT_SRC_MIN_X_MM))
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
        if use_header_scale and header_thumb_divider_x > 0.0:
            rel_x0 = float(px0) - float(src_x0)
            rel_x1 = float(px1) - float(src_x0)
            if rel_x1 >= (float(header_text_src_x0) + 1.5):
                header_region = "text"
            elif rel_x1 <= max(float(header_text_src_x0) - 1.0, float(header_thumb_divider_x) + 2.0):
                header_region = "thumb"
        out_poly: list[tuple[float, float]] = []
        for x, y in poly:
            if header_region == "text":
                nx = float(header_text_dst_x0) + ((float(x) - float(src_x0) - float(header_text_src_x0)) * float(header_text_scale_x))
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
            elif header_region == "thumb":
                nx = (float(x) - float(src_x0)) * float(header_thumb_content_scale_x)
                ny = (float(y) - float(src_y0)) * float(header_scale_y)
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

    left_overlay_polys: list[list[tuple[float, float]]] = []
    regular_overlay_polys: list[list[tuple[float, float]]] = []
    for poly in list(extra_frame_polys or []):
        if len(poly) < 2:
            continue
        px0, _py0, px1, _py1 = _poly_bbox_mm(poly)
        if float(px1) <= (float(src_x0) + 1.0):
            left_overlay_polys.append(poly)
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
    if header_thumb_divider_x > 0.0:
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
        variant1_header_cleanup = "1 вариант" in str(source_pdf).casefold()

        work_w_mm, work_h_mm = _configure_drawing_method3_backend()
        source_svg = td_path / "method3_source.svg"
        source_preview_pdf = td_path / "method3_source.pdf"
        with _technical_drawing_backend_precision():
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
        source_polys, point_box_meta = _normalize_technical_point_boxes(
            source_polys,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
            logger=logs.append,
        )
        clean_reference_polys = list(source_polys)
        if extra_frame_polys:
            clean_reference_polys.extend(list(extra_frame_polys))
        clean_reference_svg = candidate_dir / f"{variant_name}__method3_source.svg"
        clean_reference_pdf = candidate_dir / f"{variant_name}__method3_source.pdf"
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
            header_text_src_x0 = max(float(header_thumb_divider_x) + 4.0, float(_A4_HEADER_TEXT_SRC_MIN_X_MM))
        header_text_source_polys: list[list[tuple[float, float]]] = []
        if header_text_lines and header_text_src_x0 > 0.0:
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

        header_thumb_target_min_w_mm = _A4_HEADER_VARIANT1_THUMB_TARGET_MIN_W_MM if variant1_header_cleanup else _A4_HEADER_THUMB_TARGET_MIN_W_MM
        header_text_gap_mm = _A4_HEADER_VARIANT1_TEXT_GAP_MM if variant1_header_cleanup else _A4_HEADER_TEXT_GAP_MM
        header_text_scale_x = _A4_HEADER_VARIANT1_TEXT_SCALE if variant1_header_cleanup else _A4_HEADER_TEXT_SCALE
        header_thumb_content_scale_x = None
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
            header_thumb_content_scale_x=header_thumb_content_scale_x,
        )
        if not hybrid_polys:
            return {
                "variant": variant_name,
                "ok": False,
                "message": "Hybrid A4 frame transform produced no polylines.",
                "logs": logs,
            }
        if header_text_lines and float(hybrid_info.get("header_text_dst_x0", 0.0)) > 0.0:
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
        if header_text_lines and float(hybrid_info.get("header_text_dst_x0", 0.0)) > 0.0:
            header_text_polys = _render_a4_header_text_polylines(
                header_text_lines,
                src_x0=float(hybrid_info.get("src_x0", src_x0)),
                src_y0=float(hybrid_info.get("src_y0", src_y0)),
                header_scale_y=float(hybrid_info.get("header_scale_y", 1.0)),
                header_text_src_x0=float(hybrid_info.get("header_text_src_x0", header_text_src_x0)),
                header_text_dst_x0=float(hybrid_info.get("header_text_dst_x0", 0.0)),
                header_text_scale_x=float(hybrid_info.get("header_text_scale_x", 1.0)),
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

        preview_ok, preview_err = bridge._build_vector_preview_from_gcode(
            nc_path,
            svg_path,
            pdf_path,
            backend=backend,
            log=logs.append,
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
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="plotter_ascii_drawing_") as td:
        td_path = Path(td)
        ascii_pdf = td_path / "input.pdf"
        shutil.copy2(source_pdf, ascii_pdf)
        ctx = _ctx(f"preview-{time.time_ns()}")
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
            image_contours_mode="off",
            source_page_index=1,
            source_all_pages=False,
            exact_geometry_mode=exact_geometry_mode,
            safe_travel_lift=True,
            strict_one_to_one=strict_one_to_one,
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
    bridge = BackendBridge(PROJECT_ROOT)
    logs: list[str] = []
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
    with _technical_drawing_backend_precision():
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
    metrics = _analyze_gcode(nc_path)
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
                "source_cleanup=method3",
                "left_strip_removed=True",
                "outer_border_removed=True",
                *pass_notes,
            ]
            if part
        ),
    }


def _export_pdf_page_to_mupdf_svg(pdf_path: Path, page_index: int, out_svg: Path) -> None:
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    svg_text = page.get_svg_image(text_as_path=False)
    page_w_mm = float(page.rect.width) * 25.4 / 72.0
    page_h_mm = float(page.rect.height) * 25.4 / 72.0
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.write_text(svg_text, encoding="utf-8")
    tree = ET.parse(out_svg)
    root = tree.getroot()
    root.set("width", f"{page_w_mm:.3f}mm")
    root.set("height", f"{page_h_mm:.3f}mm")
    tree.write(out_svg, encoding="utf-8", xml_declaration=True)


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
    is_a3 = max(page_w_mm, page_h_mm) > 300.0

    rows: list[ArtifactRow] = []
    report: dict[str, Any] = {
        "source_pdf": str(source_pdf),
        "kind": "drawing",
        "page_count": int(doc.page_count),
        "page_size_mm": [round(page_w_mm, 3), round(page_h_mm, 3)],
        "a3_two_pass": bool(is_a3),
        "items": [],
    }

    if not is_a3:
        candidate_root = package_dir / "_candidates"
        candidate_root.mkdir(parents=True, exist_ok=True)
        hybrid_candidate = _prepare_a4_hybrid_drawing_candidate(
            source_pdf,
            variant_name="a4_hybrid_frame",
            candidate_dir=candidate_root,
        )
        candidates = [hybrid_candidate]
        if not bool(hybrid_candidate.get("ok")):
            candidates.extend(
                [
                    _prepare_drawing_candidate(
                        source_pdf,
                        variant_name="fit_full",
                        exact_geometry_mode=False,
                        strict_one_to_one=False,
                        candidate_dir=candidate_root,
                    ),
                    _prepare_drawing_candidate(
                        source_pdf,
                        variant_name="strict_1to1_clip",
                        exact_geometry_mode=True,
                        strict_one_to_one=True,
                        candidate_dir=candidate_root,
                    ),
                ]
            )
        successful = [row for row in candidates if bool(row.get("ok"))]
        if not successful:
            report["items"] = candidates
            return report, rows

        best = next((row for row in successful if str(row.get("variant", "")) == "a4_hybrid_frame"), None)
        if best is None:
            best = max(successful, key=lambda row: float(row.get("layout_similarity", 0.0) or 0.0))
        best_prefix = pages_dir / "page_01"
        for src_key, dst_path in zip(
            ["svg", "pdf", "nc", "gcode"],
            _bridge_preview_copy_targets(best_prefix),
        ):
            _copy_file(Path(str(best[src_key])), dst_path)
        chosen_logs = list(best.get("logs", []))
        _write_text(logs_dir / "page_01.log.txt", "\n".join(chosen_logs) + ("\n" if chosen_logs else ""))
        report["items"] = candidates
        report["selected_variant"] = str(best.get("variant", ""))
        report["selected_layout_similarity"] = best.get("layout_similarity")
        if str(best.get("reference_source", "")).strip():
            ref_pdf_dst = package_dir / "a4_clean_source.pdf"
            ref_svg_dst = package_dir / "a4_clean_source.svg"
            _copy_file(Path(str(best.get("reference_source", ""))), ref_pdf_dst)
            if str(best.get("reference_source_svg", "")).strip():
                _copy_file(Path(str(best.get("reference_source_svg", ""))), ref_svg_dst)
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
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
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
        return report, rows

    a3_clean_logs: list[str] = []
    clean_svg = package_dir / "_candidates" / "a3_clean_source.svg"
    clean_preview_pdf = package_dir / "_candidates" / "a3_clean_source.pdf"
    clean_svg.parent.mkdir(parents=True, exist_ok=True)
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

    for pass_index in (1, 2):
        prefix = pages_dir / f"pass_{pass_index:02d}"
        if ok_clean:
            row = _prepare_a3_pass_from_clean_svg(
                clean_svg,
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
                    draw_length_m=None,
                    segments_total=None,
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
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
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
    _mirror_package_root_artifacts(package_dir, rows)
    if combined_preview:
        for artifact_key in ("pdf", "svg"):
            artifact_path = Path(str(combined_preview[artifact_key]))
            if artifact_path.exists() and artifact_path.is_file():
                dst_path = package_dir / artifact_path.name
                if artifact_path.resolve() != dst_path.resolve():
                    _copy_file(artifact_path, dst_path)
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
                    draw_length_m=None,
                    segments_total=None,
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
                draw_length_m=round(float(metrics.get("draw_length_mm", 0.0)) / 1000.0, 3),
                segments_total=int(metrics.get("segments_total", 0)),
                bounds=_bounds_text(metrics),
                nc=str(prefix.with_suffix(".nc")),
                gcode=str(prefix.with_suffix(".gcode")),
                preview_pdf=str(prefix.with_suffix(".pdf")),
                preview_svg=str(prefix.with_suffix(".svg")),
                notes="; ".join(part for part in [f"font={font_label}", str(row.get("notes", ""))] if part),
            )
        )

    _mirror_package_root_artifacts(package_dir, rows)
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
                all_reports.append(json.loads(report_path.read_text(encoding="utf-8")))
            continue

        print(f"[{idx}/{len(pdfs)}] processing: {pdf_path.name}")
        if pdf_path.name.startswith("TOE_"):
            report, rows = _prepare_toe_package(pdf_path, package_dir)
        else:
            report, rows = _prepare_drawing_package(pdf_path, package_dir)

        _write_json(package_dir / "report.json", report)
        if rows:
            _write_csv(package_dir / "summary.csv", rows)
        all_rows.extend(rows)
        all_reports.append(report)
        ok_count = sum(1 for row in rows if row.ok)
        print(f"    items ok: {ok_count}/{len(rows)}")

    summary_path = folder / "_prepared_summary.csv"
    reports_path = folder / "_prepared_reports.json"
    if all_rows:
        _write_csv(summary_path, all_rows)
    _write_json(reports_path, {"generated_at_epoch": started_at, "reports": all_reports})
    elapsed = time.time() - started_at
    print(f"done in {elapsed / 60.0:.1f} min")
    print(f"summary: {summary_path}")
    print(f"reports: {reports_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
