from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import sys
from typing import Any

import fitz  # type: ignore
from fontTools.pens.recordingPen import RecordingPen  # type: ignore
from fontTools.ttLib import TTFont  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.legacy_generation_experiments import prepare_mahoviki_dxf2gcode as base

FONT_PATH = Path(r"C:\Windows\Fonts\GOST_AU.ttf")
OUT_DIR = base.MAHOVIKI_DIR / "dwg2gcode" / "text_variants"
PUBLISH_DIR = base.MAHOVIKI_DIR / "dwg2gcode"

Point = tuple[float, float]
Polyline = list[Point]
BBox = tuple[float, float, float, float]

ARCHIVE_STRIP_MAX_X_MM = 42.0
PAGE_EDGE_FRAME_BAND_MM = 8.0
OUTER_FRAME_LEFT_MM = 20.0
OUTER_FRAME_OTHER_MM = 5.0


def _pt_to_mm(v: float) -> float:
    return float(v) * 25.4 / 72.0


def _text_spans(pdf_path: Path) -> tuple[list[dict[str, Any]], tuple[float, float]]:
    doc = fitz.open(str(pdf_path))
    spans: list[dict[str, Any]] = []
    try:
        page = doc[0]
        page_w_mm = _pt_to_mm(float(page.rect.width))
        page_h_mm = _pt_to_mm(float(page.rect.height))
        raw = page.get_text("rawdict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_dir = tuple(line.get("dir", (1.0, 0.0)))
                for span in line.get("spans", []):
                    chars = []
                    text = ""
                    for ch in span.get("chars", []):
                        c = str(ch.get("c", "") or "")
                        if not c:
                            continue
                        ox, oy = ch.get("origin", (0.0, 0.0))
                        chars.append({"c": c, "origin_pt": (float(ox), float(oy))})
                        text += c
                    if not text.strip():
                        continue
                    x0, y0, x1, y1 = [float(v) for v in span.get("bbox", (0, 0, 0, 0))]
                    spans.append(
                        {
                            "text": text,
                            "size_pt": float(span.get("size", 0.0) or 0.0),
                            "font": str(span.get("font", "") or ""),
                            "bbox_mm": (
                                _pt_to_mm(x0),
                                page_h_mm - _pt_to_mm(y1),
                                _pt_to_mm(x1),
                                page_h_mm - _pt_to_mm(y0),
                            ),
                            "dir": (float(line_dir[0]), float(line_dir[1])),
                            "chars": chars,
                            "page_h_mm": page_h_mm,
                        }
                    )
        return spans, (page_w_mm, page_h_mm)
    finally:
        doc.close()


def _bbox(poly: Polyline) -> BBox:
    xs = [float(x) for x, _ in poly]
    ys = [float(y) for _, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _is_source_clean_artifact(poly: Polyline, page_size_mm: tuple[float, float]) -> bool:
    if len(poly) < 2:
        return False
    page_w_mm, page_h_mm = [float(v) for v in page_size_mm]
    x0, y0, x1, y1 = _bbox(poly)
    w = x1 - x0
    h = y1 - y0

    if x1 <= ARCHIVE_STRIP_MAX_X_MM:
        return True

    if x0 <= PAGE_EDGE_FRAME_BAND_MM and (h >= page_h_mm * 0.45 or x1 <= ARCHIVE_STRIP_MAX_X_MM + 18.0):
        return True
    if y0 <= PAGE_EDGE_FRAME_BAND_MM and w >= page_w_mm * 0.45:
        return True
    if x1 >= page_w_mm - PAGE_EDGE_FRAME_BAND_MM and h >= page_h_mm * 0.45:
        return True
    if y1 >= page_h_mm - PAGE_EDGE_FRAME_BAND_MM and w >= page_w_mm * 0.45:
        return True

    return False


def _filter_source_clean_artifacts(polylines: list[Polyline], page_size_mm: tuple[float, float]) -> list[Polyline]:
    return [poly for poly in polylines if not _is_source_clean_artifact(poly, page_size_mm)]


def _has_outer_frame_side(polylines: list[Polyline], *, side: str, page_size_mm: tuple[float, float], tol: float = 1.2) -> bool:
    page_w_mm, page_h_mm = [float(v) for v in page_size_mm]
    left = OUTER_FRAME_LEFT_MM
    right = page_w_mm - OUTER_FRAME_OTHER_MM
    bottom = OUTER_FRAME_OTHER_MM
    top = page_h_mm - OUTER_FRAME_OTHER_MM
    for poly in polylines:
        for a, b in zip(poly, poly[1:]):
            ax, ay = [float(v) for v in a]
            bx, by = [float(v) for v in b]
            min_x, max_x = min(ax, bx), max(ax, bx)
            min_y, max_y = min(ay, by), max(ay, by)
            if side == "top" and abs(ay - by) <= tol and abs(((ay + by) * 0.5) - top) <= tol:
                if min_x <= left + tol and max_x >= right - tol:
                    return True
            if side == "bottom" and abs(ay - by) <= tol and abs(((ay + by) * 0.5) - bottom) <= tol:
                if min_x <= left + tol and max_x >= right - tol:
                    return True
            if side == "left" and abs(ax - bx) <= tol and abs(((ax + bx) * 0.5) - left) <= tol:
                if min_y <= bottom + tol and max_y >= top - tol:
                    return True
            if side == "right" and abs(ax - bx) <= tol and abs(((ax + bx) * 0.5) - right) <= tol:
                if min_y <= bottom + tol and max_y >= top - tol:
                    return True
    return False


def _with_outer_sheet_frame(polylines: list[Polyline], page_size_mm: tuple[float, float]) -> list[Polyline]:
    page_w_mm, page_h_mm = [float(v) for v in page_size_mm]
    left = OUTER_FRAME_LEFT_MM
    right = page_w_mm - OUTER_FRAME_OTHER_MM
    bottom = OUTER_FRAME_OTHER_MM
    top = page_h_mm - OUTER_FRAME_OTHER_MM
    out = list(polylines)
    sides = {
        "bottom": [(left, bottom), (right, bottom)],
        "right": [(right, bottom), (right, top)],
        "top": [(right, top), (left, top)],
        "left": [(left, top), (left, bottom)],
    }
    for side, poly in sides.items():
        if not _has_outer_frame_side(out, side=side, page_size_mm=page_size_mm):
            out.append(poly)
    return out


def _stamp_completion_rule_lines() -> list[Polyline]:
    return [
        [(155.53, 40.64), (170.52, 40.64)],
        [(155.53, 15.58), (205.49, 15.58)],
        [(155.53, 20.57), (205.49, 20.57)],
        [(170.52, 15.58), (170.52, 25.57)],
        [(187.54, 15.58), (187.54, 25.57)],
    ]


def _transform_polylines(polylines: list[Polyline], transform: tuple[float, float, float, float, float]) -> list[Polyline]:
    return [[_apply_transform(pt, transform) for pt in poly] for poly in polylines]


def _filter_source_clean_spans(spans: list[dict[str, Any]], page_size_mm: tuple[float, float]) -> list[dict[str, Any]]:
    page_w_mm, page_h_mm = [float(v) for v in page_size_mm]
    out: list[dict[str, Any]] = []
    for span in spans:
        text = str(span.get("text", "") or "").strip().casefold()
        x0, y0, x1, y1 = [float(v) for v in span.get("bbox_mm", (0, 0, 0, 0))]
        if x1 <= ARCHIVE_STRIP_MAX_X_MM:
            continue
        if text in {"a4", "Р°4", "a3", "Р°3"}:
            if x0 <= PAGE_EDGE_FRAME_BAND_MM * 2 or y0 <= PAGE_EDGE_FRAME_BAND_MM * 2:
                continue
            if x1 >= page_w_mm - PAGE_EDGE_FRAME_BAND_MM * 2 or y1 >= page_h_mm - PAGE_EDGE_FRAME_BAND_MM * 2:
                continue
        out.append(span)
    return out


def _inside_any_text_box(poly: Polyline, boxes: list[BBox], pad: float = 1.0, center_match: bool = False) -> bool:
    if len(poly) < 2:
        return False
    x0, y0, x1, y1 = _bbox(poly)
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    for tx0, ty0, tx1, ty1 in boxes:
        if x0 >= tx0 - pad and x1 <= tx1 + pad and y0 >= ty0 - pad and y1 <= ty1 + pad:
            return True
        if center_match and tx0 - pad <= cx <= tx1 + pad and ty0 - pad <= cy <= ty1 + pad:
            text_w = max(1.0, tx1 - tx0)
            text_h = max(1.0, ty1 - ty0)
            if (x1 - x0) <= max(16.0, text_w * 1.80) and (y1 - y0) <= max(12.0, text_h * 1.80):
                return True
    return False


def _filter_text_garbage(
    polylines: list[Polyline],
    spans: list[dict[str, Any]],
    *,
    pad: float = 1.0,
    center_match: bool = False,
) -> list[Polyline]:
    boxes = [tuple(span["bbox_mm"]) for span in spans]
    return [poly for poly in polylines if not _inside_any_text_box(poly, boxes, pad=pad, center_match=center_match)]


def _is_stamp_rule_line(poly: Polyline) -> bool:
    if len(poly) != 2:
        return False
    x0, y0, x1, y1 = _bbox(poly)
    w = x1 - x0
    h = y1 - y0
    return (w <= 0.20 and h >= 4.0) or (h <= 0.20 and w >= 4.0)


def _filter_pack_layout_text_garbage(polylines: list[Polyline], spans: list[dict[str, Any]]) -> list[Polyline]:
    boxes = [tuple(span["bbox_mm"]) for span in spans]
    out: list[Polyline] = []
    for poly in polylines:
        if _is_stamp_rule_line(poly):
            out.append(poly)
            continue
        if _inside_any_text_box(poly, boxes, pad=1.2, center_match=False):
            continue
        out.append(poly)
    return out


def _plot_text_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    skip_markers = (
        "РєРѕРјРїР°СЃ",
        "СѓС‡РµР±РЅР°СЏ",
        "РєРѕРјРјРµСЂС‡РµСЃРє",
        "РїРѕРґРїРёСЃР°РЅ",
        "С„РѕСЂРјР°С‚",
        "РєРѕРїРёСЂРѕРІР°Р»",
    )
    out: list[dict[str, Any]] = []
    for span in spans:
        text = str(span.get("text", "") or "").casefold()
        bbox = tuple(span.get("bbox_mm", (0, 0, 0, 0)))
        x0, y0, x1, y1 = [float(v) for v in bbox]
        if any(marker in text for marker in skip_markers):
            continue
        if x1 <= 22.0 and len(text.strip()) > 5:
            continue
        if y1 <= 8.0 and len(text.strip()) > 5:
            continue
        out.append(span)
    return out


def _fit_transform(polylines: list[Polyline]) -> tuple[list[Polyline], tuple[float, float, float, float]]:
    x0, y0, x1, y1 = base._bbox(polylines)
    width = max(1e-9, x1 - x0)
    height = max(1e-9, y1 - y0)
    target_w = base.PLOTTER_W_MM - (2.0 * base.PLOTTER_MARGIN_MM)
    target_h = base.PLOTTER_H_MM - (2.0 * base.PLOTTER_MARGIN_MM)
    scale = min(target_w / width, target_h / height)
    used_w = width * scale
    used_h = height * scale
    ox = base.PLOTTER_MARGIN_MM + (target_w - used_w) * 0.5
    oy = base.PLOTTER_MARGIN_MM + (target_h - used_h) * 0.5

    def tr(pt: Point) -> Point:
        return ox + (float(pt[0]) - x0) * scale, -(oy + (float(pt[1]) - y0) * scale)

    return [[tr(pt) for pt in poly] for poly in polylines], (x0, y0, scale, ox, oy)


def _apply_transform(pt: Point, transform: tuple[float, float, float, float, float]) -> Point:
    x0, y0, scale, ox, oy = transform
    return ox + (float(pt[0]) - x0) * scale, -(oy + (float(pt[1]) - y0) * scale)


class GostOutlineRenderer:
    def __init__(self, font_path: Path) -> None:
        self.font = TTFont(str(font_path))
        self.glyf = self.font["glyf"]
        self.hmtx = self.font["hmtx"]
        self.units_per_em = float(self.font["head"].unitsPerEm)
        self.cmap: dict[int, str] = {}
        for table in self.font["cmap"].tables:
            self.cmap.update(table.cmap)

    def glyph_name(self, ch: str) -> str | None:
        fallbacks = {
            "вЊЂ": "Г",
            "в„–": "N",
        }
        direct = self.cmap.get(ord(ch))
        if direct is not None:
            return direct
        fallback = fallbacks.get(ch)
        if fallback:
            return self.cmap.get(ord(fallback))
        return None

    def _recording_to_polys(self, glyph_name: str) -> list[Polyline]:
        pen = RecordingPen()
        self.glyf[glyph_name].draw(pen, self.glyf)
        polys: list[Polyline] = []
        current: Polyline = []
        last: Point | None = None

        def add(pt: Point) -> None:
            nonlocal last
            if last is None or math.hypot(pt[0] - last[0], pt[1] - last[1]) >= 1.0:
                current.append(pt)
                last = pt

        for op, args in pen.value:
            if op == "moveTo":
                if len(current) >= 2:
                    polys.append(current)
                current = []
                pt = tuple(args[0])
                last = None
                add((float(pt[0]), float(pt[1])))
            elif op == "lineTo":
                pt = tuple(args[0])
                add((float(pt[0]), float(pt[1])))
            elif op == "qCurveTo":
                pts = [tuple(p) for p in args]
                if last is None or len(pts) < 2:
                    continue
                p0 = last
                for control, end in zip(pts, pts[1:]):
                    c = (float(control[0]), float(control[1]))
                    e = (float(end[0]), float(end[1]))
                    for step in range(1, 9):
                        t = step / 8.0
                        u = 1.0 - t
                        add((u * u * p0[0] + 2 * u * t * c[0] + t * t * e[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * e[1]))
                    p0 = e
            elif op == "curveTo":
                pts = [tuple(p) for p in args]
                if last is None or len(pts) != 3:
                    continue
                p0 = last
                p1 = (float(pts[0][0]), float(pts[0][1]))
                p2 = (float(pts[1][0]), float(pts[1][1]))
                p3 = (float(pts[2][0]), float(pts[2][1]))
                for step in range(1, 13):
                    t = step / 12.0
                    add(base._cubic(p0, p1, p2, p3, t))
            elif op == "closePath":
                if len(current) >= 2 and math.hypot(current[0][0] - current[-1][0], current[0][1] - current[-1][1]) >= 1.0:
                    current.append(current[0])
                if len(current) >= 2:
                    polys.append(current)
                current = []
                last = None
        if len(current) >= 2:
            polys.append(current)
        return polys

    def render_spans(self, spans: list[dict[str, Any]], transform: tuple[float, float, float, float, float]) -> list[Polyline]:
        out: list[Polyline] = []
        for span in spans:
            size_pt = float(span["size_pt"])
            if size_pt <= 0:
                continue
            scale_pt = size_pt / self.units_per_em
            dx, dy = span.get("dir", (1.0, 0.0))
            norm = (float(dy), -float(dx))
            page_h_mm = float(span["page_h_mm"])
            for ch in span["chars"]:
                char = str(ch["c"])
                if char.isspace():
                    continue
                glyph = self.glyph_name(char)
                if glyph is None:
                    continue
                ox_pt, oy_pt = ch["origin_pt"]
                for glyph_poly in self._recording_to_polys(glyph):
                    poly_mm: Polyline = []
                    for gx, gy in glyph_poly:
                        px = float(ox_pt) + float(dx) * gx * scale_pt + norm[0] * gy * scale_pt
                        py = float(oy_pt) + float(dy) * gx * scale_pt + norm[1] * gy * scale_pt
                        poly_mm.append((_pt_to_mm(px), page_h_mm - _pt_to_mm(py)))
                    out.append([_apply_transform(pt, transform) for pt in poly_mm])
        return out

    def render_spans_source_mm(self, spans: list[dict[str, Any]]) -> list[Polyline]:
        out: list[Polyline] = []
        for span in spans:
            size_pt = float(span["size_pt"])
            if size_pt <= 0:
                continue
            scale_pt = size_pt / self.units_per_em
            dx, dy = span.get("dir", (1.0, 0.0))
            norm = (float(dy), -float(dx))
            page_h_mm = float(span["page_h_mm"])
            for ch in span["chars"]:
                char = str(ch["c"])
                if char.isspace():
                    continue
                glyph = self.glyph_name(char)
                if glyph is None:
                    continue
                ox_pt, oy_pt = ch["origin_pt"]
                for glyph_poly in self._recording_to_polys(glyph):
                    poly_mm: Polyline = []
                    for gx, gy in glyph_poly:
                        px = float(ox_pt) + float(dx) * gx * scale_pt + norm[0] * gy * scale_pt
                        py = float(oy_pt) + float(dy) * gx * scale_pt + norm[1] * gy * scale_pt
                        poly_mm.append((_pt_to_mm(px), page_h_mm - _pt_to_mm(py)))
                    out.append(poly_mm)
        return out

    def render_text_source_mm(self, text: str, *, x_mm: float, y_mm: float, size_mm: float, angle_deg: float = 0.0) -> list[Polyline]:
        out: list[Polyline] = []
        angle = math.radians(angle_deg)
        dx = math.cos(angle)
        dy = math.sin(angle)
        norm = (-dy, dx)
        scale = float(size_mm) / self.units_per_em
        cursor = 0.0
        for ch in text:
            if ch.isspace():
                cursor += self.units_per_em * 0.42
                continue
            glyph = self.glyph_name(ch)
            if glyph is None:
                cursor += self.units_per_em * 0.42
                continue
            for glyph_poly in self._recording_to_polys(glyph):
                poly_mm: Polyline = []
                for gx, gy in glyph_poly:
                    px = float(x_mm) + dx * (cursor + gx) * scale + norm[0] * gy * scale
                    py = float(y_mm) + dy * (cursor + gx) * scale + norm[1] * gy * scale
                    poly_mm.append((px, py))
                out.append(poly_mm)
            advance, _ = self.hmtx[glyph]
            cursor += float(advance)
        return out

    def render_stamp_completion_source_mm(self) -> list[Polyline]:
        out: list[Polyline] = []
        out.extend(_stamp_completion_rule_lines())
        labels = [
            ("РР·Рј.", 21.20, 57.10, 2.25),
            ("Р›РёСЃС‚", 30.60, 57.10, 2.25),
            ("Р Р°Р·СЂР°Р±.", 21.30, 52.20, 2.25),
            ("РџСЂРѕРІ.", 21.30, 47.20, 2.25),
            ("Рў.РєРѕРЅС‚СЂ.", 21.30, 42.20, 2.25),
            ("Рќ.РєРѕРЅС‚СЂ.", 21.30, 37.20, 2.25),
            ("РЈС‚РІ.", 21.30, 32.20, 2.25),
            ("Р›РёС‚.", 157.00, 42.20, 2.25),
            ("РњР°СЃСЃР°", 173.20, 42.20, 2.25),
            ("РњР°СЃС€С‚Р°Р±", 190.00, 42.20, 2.25),
            ("Р›РёСЃС‚", 157.00, 21.85, 2.25),
            ("Р›РёСЃС‚РѕРІ", 175.80, 21.85, 2.25),
        ]
        for text, x, y, size in labels:
            out.extend(self.render_text_source_mm(text, x_mm=x, y_mm=y, size_mm=size))
        return out


def _run_filtered_geometry(pdf_path: Path, out_prefix: Path, source_polys: list[Polyline]) -> tuple[list[Polyline], dict[str, object]]:
    dxf = out_prefix.with_suffix(".dxf")
    raw = out_prefix.with_suffix(".ngc")
    base._write_dxf(source_polys, dxf)
    run = base._run_dxf2gcode(dxf, raw)
    if int(run["returncode"]) != 0 or not raw.exists():
        raise RuntimeError(str(run["stderr"])[-2000:])
    raw_polys = base._raw_gcode_to_polylines(raw)
    deduped = base._dedupe_segments(raw_polys)
    return deduped, {"dxf": str(dxf), "raw_gcode": str(raw), "run": run, "raw_polylines": len(raw_polys), "deduped_polylines": len(deduped)}


def _copy_raw_preview(pdf_stem: str) -> dict[str, str]:
    src_dir = base.MAHOVIKI_DIR / "dwg2gcode"
    raw_pdf = src_dir / f"{pdf_stem}_dxf2gcode_preview.pdf"
    raw_png = src_dir / f"{pdf_stem}_dxf2gcode_preview.png"
    dst_pdf = OUT_DIR / f"{pdf_stem}_alg0_raw_dxf2gcode_preview.pdf"
    dst_png = OUT_DIR / f"{pdf_stem}_alg0_raw_dxf2gcode_preview.png"
    if raw_pdf.exists():
        shutil.copy2(raw_pdf, dst_pdf)
    if raw_png.exists():
        shutil.copy2(raw_png, dst_png)
    return {"preview_pdf": str(dst_pdf), "preview_png": str(dst_png)}


def _png_from_pdf(pdf_path: Path) -> Path:
    png = pdf_path.with_suffix(".png")
    doc = fitz.open(str(pdf_path))
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pix.save(str(png))
    finally:
        doc.close()
    return png


def _render_source_clean_pdf(polylines: list[Polyline], *, page_size_mm: tuple[float, float], out_pdf: Path) -> None:
    page_w_mm, page_h_mm = [float(v) for v in page_size_mm]
    doc = fitz.open()
    try:
        page = doc.new_page(width=page_w_mm * base.MM_TO_PT, height=page_h_mm * base.MM_TO_PT)
        shape = page.new_shape()
        for poly in polylines:
            if len(poly) < 2:
                continue
            pts = [(float(x) * base.MM_TO_PT, (page_h_mm - float(y)) * base.MM_TO_PT) for x, y in poly]
            for a, b in zip(pts, pts[1:]):
                shape.draw_line(fitz.Point(*a), fitz.Point(*b))
        shape.finish(color=(0, 0, 0), width=0.18 * base.MM_TO_PT)
        shape.commit()
        doc.save(str(out_pdf))
    finally:
        doc.close()


def _draw_source_polylines_on_page(page: fitz.Page, polylines: list[Polyline], *, page_h_mm: float) -> None:
    shape = page.new_shape()
    for poly in polylines:
        if len(poly) < 2:
            continue
        pts = [(float(x) * base.MM_TO_PT, (page_h_mm - float(y)) * base.MM_TO_PT) for x, y in poly]
        for a, b in zip(pts, pts[1:]):
            shape.draw_line(fitz.Point(*a), fitz.Point(*b))
    shape.finish(color=(0, 0, 0), width=0.18 * base.MM_TO_PT)
    shape.commit()


def _render_source_clean_pdf_from_template(
    *,
    template_pdf: Path,
    spans: list[dict[str, Any]],
    text_polylines: list[Polyline],
    out_pdf: Path,
) -> None:
    doc = fitz.open(str(template_pdf))
    try:
        page = doc[0]
        page_h_mm = float(page.rect.height) / base.MM_TO_PT
        for span in spans:
            x0, y0, x1, y1 = [float(v) for v in span.get("bbox_mm", (0, 0, 0, 0))]
            pad = 0.25
            rect = fitz.Rect(
                (x0 - pad) * base.MM_TO_PT,
                (page_h_mm - (y1 + pad)) * base.MM_TO_PT,
                (x1 + pad) * base.MM_TO_PT,
                (page_h_mm - (y0 - pad)) * base.MM_TO_PT,
            )
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0, overlay=True)
        _draw_source_polylines_on_page(page, text_polylines, page_h_mm=page_h_mm)
        doc.save(str(out_pdf), garbage=4, deflate=True)
    finally:
        doc.close()


def _pack_clean_source_pdf_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(f"{pdf_path.stem}_pack") / "a4_clean_source.pdf"


def _source_layout_geometry(
    pdf_path: Path,
    fallback_polylines: list[Polyline],
    fallback_page_size: tuple[float, float],
    spans: list[dict[str, Any]],
) -> tuple[list[Polyline], tuple[float, float], str]:
    pack_clean = _pack_clean_source_pdf_for(pdf_path)
    if pack_clean.exists():
        layout_polys, layout_page_size = base._pdf_to_polylines(pack_clean)
        layout_polys = _filter_pack_layout_text_garbage(layout_polys, spans)
        return _with_outer_sheet_frame(layout_polys, layout_page_size), layout_page_size, str(pack_clean)
    return _with_outer_sheet_frame(fallback_polylines, fallback_page_size), fallback_page_size, "generated_clean_source_fallback"


def _publish_clean_outputs(stem: str, *, gcode: Path, preview_pdf: Path, preview_png: Path) -> dict[str, str]:
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    published_gcode = PUBLISH_DIR / f"{stem}_dxf2gcode_text_clean.gcode"
    published_pdf = PUBLISH_DIR / f"{stem}_dxf2gcode_text_clean_preview.pdf"
    published_png = PUBLISH_DIR / f"{stem}_dxf2gcode_text_clean_preview.png"
    shutil.copy2(gcode, published_gcode)
    shutil.copy2(preview_pdf, published_pdf)
    shutil.copy2(preview_png, published_png)
    return {
        "gcode": str(published_gcode),
        "preview_pdf": str(published_pdf),
        "preview_png": str(published_png),
    }


def _publish_source_clean_pdf(
    stem: str,
    *,
    source_pdf: Path,
    source_png: Path,
) -> dict[str, str]:
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    published_pdf = PUBLISH_DIR / f"{stem}_a4_clean_source.pdf"
    published_png = PUBLISH_DIR / f"{stem}_a4_clean_source.png"
    shutil.copy2(source_pdf, published_pdf)
    shutil.copy2(source_png, published_png)
    return {
        "source_pdf": str(published_pdf),
        "source_png": str(published_png),
    }


def prepare_one(pdf_path: Path, renderer: GostOutlineRenderer) -> dict[str, object]:
    stem = pdf_path.stem
    source_polys, page_size = base._pdf_to_polylines(pdf_path)
    spans, _ = _text_spans(pdf_path)
    filtered = _filter_text_garbage(source_polys, spans)
    geom_polys, geom_meta = _run_filtered_geometry(pdf_path, OUT_DIR / f"{stem}_alg1_geometry_only", filtered)
    fitted_geom, transform = _fit_transform(geom_polys)

    geom_gcode = OUT_DIR / f"{stem}_alg1_geometry_only.gcode"
    geom_pdf = OUT_DIR / f"{stem}_alg1_geometry_only_preview.pdf"
    base._write_plotter_gcode(fitted_geom, geom_gcode)
    base._render_preview(fitted_geom, geom_pdf)
    geom_png = _png_from_pdf(geom_pdf)

    text_polys = renderer.render_spans(spans, transform)
    combined = [*fitted_geom, *text_polys]
    text_gcode = OUT_DIR / f"{stem}_alg2_textlayer_gost_outline.gcode"
    text_pdf = OUT_DIR / f"{stem}_alg2_textlayer_gost_outline_preview.pdf"
    base._write_plotter_gcode(combined, text_gcode)
    base._render_preview(combined, text_pdf)
    text_png = _png_from_pdf(text_pdf)

    strict_filtered = _filter_text_garbage(source_polys, spans, pad=4.0, center_match=True)
    strict_source_clean = _filter_source_clean_artifacts(strict_filtered, page_size)
    source_layout_polys, source_layout_page_size, source_layout_from = _source_layout_geometry(
        pdf_path,
        strict_source_clean,
        page_size,
        spans,
    )
    strict_polys, strict_meta = _run_filtered_geometry(pdf_path, OUT_DIR / f"{stem}_alg3_textlayer_gost_clean", source_layout_polys)
    fitted_strict, strict_transform = _fit_transform(strict_polys)
    clean_spans = _filter_source_clean_spans(_plot_text_spans(spans), page_size)
    clean_text_polys = renderer.render_spans(clean_spans, strict_transform)
    stamp_completion_source = renderer.render_stamp_completion_source_mm()
    stamp_completion_plotter = _transform_polylines(stamp_completion_source, strict_transform)
    clean_combined = [*fitted_strict, *clean_text_polys, *stamp_completion_plotter]
    clean_gcode = OUT_DIR / f"{stem}_alg3_textlayer_gost_clean.gcode"
    clean_pdf = OUT_DIR / f"{stem}_alg3_textlayer_gost_clean_preview.pdf"
    base._write_plotter_gcode(clean_combined, clean_gcode)
    base._render_preview(clean_combined, clean_pdf)
    clean_png = _png_from_pdf(clean_pdf)
    published_clean = _publish_clean_outputs(stem, gcode=clean_gcode, preview_pdf=clean_pdf, preview_png=clean_png)

    clean_source_text = renderer.render_spans_source_mm(clean_spans)
    clean_source_overlay = [*clean_source_text, *stamp_completion_source]
    clean_source_pdf = OUT_DIR / f"{stem}_a4_clean_source.pdf"
    source_layout_template = Path(source_layout_from)
    if source_layout_template.exists():
        _render_source_clean_pdf_from_template(
            template_pdf=source_layout_template,
            spans=clean_spans,
            text_polylines=clean_source_overlay,
            out_pdf=clean_source_pdf,
        )
    else:
        _render_source_clean_pdf(
            [*source_layout_polys, *clean_source_overlay],
            page_size_mm=source_layout_page_size,
            out_pdf=clean_source_pdf,
        )
    clean_source_png = _png_from_pdf(clean_source_pdf)
    published_source_clean = _publish_source_clean_pdf(stem, source_pdf=clean_source_pdf, source_png=clean_source_png)

    return {
        "source_pdf": str(pdf_path),
        "text_spans": len(spans),
        "source_polylines": len(source_polys),
        "filtered_polylines": len(filtered),
        "alg0_raw": _copy_raw_preview(stem),
        "alg1_geometry_only": {
            **geom_meta,
            "gcode": str(geom_gcode),
            "preview_pdf": str(geom_pdf),
            "preview_png": str(geom_png),
        },
        "alg2_textlayer_gost_outline": {
            "text_polylines": len(text_polys),
            "gcode": str(text_gcode),
            "preview_pdf": str(text_pdf),
            "preview_png": str(text_png),
        },
        "alg3_textlayer_gost_clean": {
            **strict_meta,
            "filtered_polylines": len(strict_source_clean),
            "text_spans": len(clean_spans),
            "text_polylines": len(clean_text_polys),
            "gcode": str(clean_gcode),
            "preview_pdf": str(clean_pdf),
            "preview_png": str(clean_png),
        },
        "final_text_clean": published_clean,
        "final_a4_clean_source": {
            **published_source_clean,
            "layout_from": source_layout_from,
            "source_text_polylines": len(clean_source_text),
            "stamp_completion_polylines": len(stamp_completion_source),
            "source_geometry_polylines": len(source_layout_polys),
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    renderer = GostOutlineRenderer(FONT_PATH)
    pdfs = sorted(base.SOURCE_PDF_DIR.glob("*.pdf"))
    reports = []
    for pdf in pdfs:
        print(f"processing {pdf.name}")
        report = prepare_one(pdf, renderer)
        reports.append(report)
        print(
            "  spans={text_spans} filtered={filtered_polylines}/{source_polylines} text_polys={text_polys} clean_text_polys={clean_text_polys}".format(
                text_spans=report["text_spans"],
                filtered_polylines=report["filtered_polylines"],
                source_polylines=report["source_polylines"],
                text_polys=report["alg2_textlayer_gost_outline"]["text_polylines"],
                clean_text_polys=report["alg3_textlayer_gost_clean"]["text_polylines"],
            )
        )
    (OUT_DIR / "text_variants_report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

