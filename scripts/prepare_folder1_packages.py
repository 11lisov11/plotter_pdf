from __future__ import annotations

import argparse
import csv
import json
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

from plotter_studio.core.protocol import BackendBridge, SheetConfig, _gcode_to_polylines, _is_detail_polyline_mm
from plotter_studio.core.serial_worker import OperationContext
from src import plotter_pdf_drawer as backend


TOE_FONT_MAP = {
    "TOE_Zadachi_1_2_Variant_14": ("Marck Script", "MarckScript-Regular.ttf"),
    "TOE_Zadachi_1_2_Variant_25": ("Bad Script", "BadScript-Regular.ttf"),
    "TOE_Zadachi_1_2_Variant_26": ("Caveat", "Caveat-wght.ttf"),
}
TOE_FALLBACK_LAYOUT_THRESHOLD = 0.93


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


def _copy_latest_preview_artifacts(prefix: Path) -> tuple[Path, Path, Path, Path]:
    tmp = PROJECT_ROOT / "_tmp"
    src_svg = tmp / "latest_preview_vector.svg"
    src_pdf = tmp / "latest_preview_vector.pdf"
    src_nc = tmp / "latest_preview.nc"
    dst_svg, dst_pdf, dst_nc, dst_gcode = _bridge_preview_copy_targets(prefix)
    _copy_file(src_svg, dst_svg)
    _copy_file(src_pdf, dst_pdf)
    _copy_nc_and_gcode(src_nc, dst_nc, dst_gcode)
    return dst_svg, dst_pdf, dst_nc, dst_gcode


def _mirror_package_root_artifacts(package_dir: Path, rows: list[ArtifactRow]) -> None:
    for row in rows:
        if not bool(row.ok):
            continue
        for src_text in (row.preview_pdf, row.nc, row.gcode):
            if not src_text:
                continue
            src = Path(str(src_text))
            if not src.exists() or not src.is_file():
                continue
            _copy_file(src, package_dir / src.name)


def _rewrite_pdf_page_text_to_handwritten_pdf(
    *,
    source_pdf: Path,
    page_index: int,
    font_path: Path,
    out_pdf: Path,
    render_dpi: int = 450,
) -> None:
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
            line_bbox = line.get("bbox")
            if not line_bbox:
                continue
            lx0, ly0, lx1, ly1 = [float(v) * scale for v in line_bbox]
            target_h = max(12, int((ly1 - ly0) * 0.92))
            target_w = max(12, int((lx1 - lx0) * 0.98))
            size = target_h
            font = ImageFont.truetype(str(font_path), size=size)
            while size > 8:
                font = ImageFont.truetype(str(font_path), size=size)
                bb = draw.textbbox((0, 0), text, font=font)
                text_w = bb[2] - bb[0]
                text_h = bb[3] - bb[1]
                if text_w <= target_w and text_h <= max(12, int((ly1 - ly0) * 1.05)):
                    break
                size -= 1
            draw.text((lx0, ly0), text, font=font, fill=(25, 25, 25))

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
    prefix: Path,
    font_label: str,
    font_path: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="toe_raster_fallback_") as td:
        td_path = Path(td)
        rewritten_pdf = td_path / "rewritten.pdf"
        candidate_prefix = prefix.parent / f"{prefix.name}__fallback_candidate"
        _rewrite_pdf_page_text_to_handwritten_pdf(
            source_pdf=source_pdf,
            page_index=page_index - 1,
            font_path=font_path,
            out_pdf=rewritten_pdf,
        )
        ok, msg, logs = _bridge_run_preview(
            input_path=rewritten_pdf,
            sheet=SheetConfig(sheet_format="a4", anchor="lower_left"),
            tool_mode="pencil",
            render_mode="handwriting",
            quality_profile="high",
            force_text_to_path=False,
            handwriting_enabled=True,
            handwriting_font=str(font_path),
            handwriting_formula_font="Times New Roman",
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
                "logs": logs,
                "font_label": font_label,
                "font_path": str(font_path),
            }
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(candidate_prefix)
        metrics = _analyze_gcode(nc_path)
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=page_index - 1)
        return {
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
            "notes": "fallback=raster_rewrite_handdraw",
        }


def _bridge_run_preview(
    *,
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
            ctx=_ctx(f"preview-{time.time_ns()}"),
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


def _poly_bbox_mm(poly: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [float(x) for x, _y in poly]
    ys = [float(y) for _x, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


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


def _compose_a4_hybrid_frame_polylines(
    polys_mm: list[list[tuple[float, float]]],
    *,
    page_w_mm: float,
    page_h_mm: float,
    target_w_mm: float,
    target_h_mm: float,
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

    transformed: list[list[tuple[float, float]]] = []
    detail_paths = 0
    frame_paths = 0
    detail_pts: list[tuple[float, float]] = []
    removed_title_box_paths = 0

    for poly, is_detail in zip(polys_mm, detail_flags):
        if title_box and _poly_is_axis_aligned_mm(poly):
            x0, y0, x1, y1 = _poly_bbox_mm(poly)
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
        out_poly: list[tuple[float, float]] = []
        for x, y in poly:
            if is_detail:
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
        if is_detail:
            detail_paths += 1
        else:
            frame_paths += 1

    if title_box:
        transformed.append(
            [
                (0.0, float(title_box["target_h"])),
                (float(title_box["w"]), float(title_box["target_h"])),
                (float(title_box["w"]), 0.0),
            ]
        )
        frame_paths += 1

    info: dict[str, float] = {
        "src_x0": float(src_x0),
        "src_x1": float(src_x1),
        "src_y0": float(src_y0),
        "src_y1": float(src_y1),
        "src_w": float(src_w),
        "src_h": float(src_h),
        "frame_scale_x": float(frame_scale_x),
        "frame_scale_y": float(frame_scale_y),
        "detail_scale": 1.0,
        "detail_paths": float(detail_paths),
        "frame_paths": float(frame_paths),
        "title_box_removed_paths": float(removed_title_box_paths),
    }
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
        setattr(backend, "HANDWRITING_TEXT_ENABLED", True)
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

        with fitz.open(ascii_pdf) as doc:
            page = doc[0]
            page_w_mm = float(page.rect.width) * 25.4 / 72.0
            page_h_mm = float(page.rect.height) * 25.4 / 72.0

        source_polys = _parse_method3_svg_polylines(source_svg)
        if not source_polys:
            return {
                "variant": variant_name,
                "ok": False,
                "message": "Method3 source SVG produced no polylines.",
                "logs": logs,
            }

        hybrid_polys, hybrid_info = _compose_a4_hybrid_frame_polylines(
            source_polys,
            page_w_mm=page_w_mm,
            page_h_mm=page_h_mm,
            target_w_mm=work_w_mm,
            target_h_mm=work_h_mm,
        )
        if not hybrid_polys:
            return {
                "variant": variant_name,
                "ok": False,
                "message": "Hybrid A4 frame transform produced no polylines.",
                "logs": logs,
            }

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
        similarity = _layout_similarity_pdf(source_pdf, pdf_path, source_page_index=0)
        notes = (
            "detail_scale=1.0; "
            f"frame_scale_x={float(hybrid_info.get('frame_scale_x', 1.0)):.4f}; "
            f"frame_scale_y={float(hybrid_info.get('frame_scale_y', 1.0)):.4f}; "
            f"detail_bbox={float(hybrid_info.get('detail_w', 0.0)):.2f}x{float(hybrid_info.get('detail_h', 0.0)):.2f} mm; "
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
        ok, msg, logs = _bridge_run_preview(
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
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix)
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
        ok, msg, logs = _bridge_run_preview(
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
        svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix)
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
    with _technical_drawing_backend_precision():
        ok, msg = bridge.run_preview(
            ctx=_ctx(f"a3-clean-pass-{pass_index}-{time.time_ns()}"),
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
    svg_path, pdf_path, nc_path, gcode_path = _copy_latest_preview_artifacts(prefix)
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


def _configure_toe_backend(font_path: Path) -> None:
    backend.HANDWRITING_TEXT_ENABLED = True
    backend.HANDWRITING_FONT_FAMILY = str(font_path)
    backend.HANDWRITING_CYRILLIC_FONT_FAMILY = str(font_path)
    backend.HANDWRITING_SINGLELINE_TTF_BACKEND = "autotrace3"
    backend.HANDWRITING_DIRECT_VECTOR_TEXT_ENABLED = True
    backend.IMAGE_CONTOUR_MODE = "always"
    backend.IMAGE_CONTOUR_ENABLED = True
    backend.IMAGE_CONTOUR_WORD_ONLY = False
    backend.FORCE_TEXT_TO_PATH = False
    backend.USE_INKSCAPE_PDF_IMPORT = False
    backend.EXACT_GEOMETRY_MODE = False
    backend.MIN_FIT_SCALE_FOR_DIMENSIONAL_DRAW = 0.0
    backend.SAFE_PEN_TRAVEL_UP = False
    backend.TOOL_MODE = "pencil"
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


def _prepare_toe_page(
    *,
    source_pdf: Path,
    page_index: int,
    page_svg: Path,
    font_label: str,
    font_path: Path,
    prefix: Path,
) -> dict[str, Any]:
    _configure_toe_backend(font_path)
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
            prefix=prefix,
            font_label=font_label,
            font_path=font_path,
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
    _mirror_package_root_artifacts(package_dir, rows)
    return report, rows


def _prepare_toe_package(source_pdf: Path, package_dir: Path) -> tuple[dict[str, Any], list[ArtifactRow]]:
    pages_dir = package_dir / "pages"
    logs_dir = package_dir / "logs"
    temp_svg_dir = package_dir / "_page_svg"
    _ensure_clean_dir(package_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    temp_svg_dir.mkdir(parents=True, exist_ok=True)

    font_label, font_filename = TOE_FONT_MAP.get(source_pdf.stem, ("Marck Script", "MarckScript-Regular.ttf"))
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
