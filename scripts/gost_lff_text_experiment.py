"""Try LibreCAD OpenGOST LFF single-line text on a real KOMPAS PDF.

This is intentionally an experiment, not a replacement for the production
plotter pipeline yet.  It renders PDF text with the LibreCAD LFF line font so
we can compare letters before wiring the method into package generation.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "Компьютерная графика" / "9 вариант" / "1.pdf"
DEFAULT_FONT = ROOT / "assets" / "single_line_fonts" / "lc_opengost-ar.lff"
DEFAULT_OUT_DIR = ROOT / "Компьютерная графика" / "новый тест букв"

PT_TO_MM = 25.4 / 72.0
FONT_EM_MIN = -1.25
FONT_EM_MAX = 9.25


Point = tuple[float, float]
Polyline = list[Point]


@dataclass
class Glyph:
    char: str
    polylines: list[Polyline]
    min_x: float
    max_x: float

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)


@dataclass
class LffFont:
    glyphs: dict[str, Glyph]
    letter_spacing: float = 1.0
    word_spacing: float = 4.0


def _manual_glyph_for(char: str) -> Glyph | None:
    if char == "0":
        cx = 2.25
        cy = 4.50
        rx = 1.95
        ry = 4.12
        polyline = [
            (cx + rx * math.cos(2.0 * math.pi * i / 36.0), cy + ry * math.sin(2.0 * math.pi * i / 36.0))
            for i in range(37)
        ]
        return Glyph("0", [polyline], 0.0, 4.5)
    if char == "□":
        polyline = [(0.20, 2.20), (3.85, 2.20), (3.85, 5.85), (0.20, 5.85), (0.20, 2.20)]
        return Glyph("□", [polyline], 0.0, 4.05)
    return None


def _clean_source_for(source_pdf: Path) -> Path | None:
    candidate = source_pdf.with_name(f"{source_pdf.stem}_pack") / "a4_clean_source.pdf"
    if candidate.exists():
        return candidate
    return None


def _parse_float(value: str) -> float:
    return float(value.strip().replace(",", "."))


def _arc_points_from_bulge(p0: Point, p1: Point, bulge: float) -> Polyline:
    """Approximate a DXF/LFF bulge arc from p0 to p1."""

    if abs(bulge) < 1e-9:
        return [p0, p1]

    x0, y0 = p0
    x1, y1 = p1
    dx = x1 - x0
    dy = y1 - y0
    chord = math.hypot(dx, dy)
    if chord < 1e-9:
        return [p0]

    theta = 4.0 * math.atan(bulge)
    radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    mid_x = (x0 + x1) * 0.5
    mid_y = (y0 + y1) * 0.5
    normal_x = -dy / chord
    normal_y = dx / chord
    center_offset = chord * (1.0 - bulge * bulge) / (4.0 * bulge)
    center_x = mid_x + normal_x * center_offset
    center_y = mid_y + normal_y * center_offset

    start_angle = math.atan2(y0 - center_y, x0 - center_x)
    steps = max(5, int(math.ceil(abs(theta) * radius / 0.22)))
    points: Polyline = []
    for index in range(steps + 1):
        angle = start_angle + theta * index / steps
        points.append(
            (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle),
            )
        )
    return points


def _parse_lff_line(line: str) -> Polyline:
    raw_points: list[tuple[float, float, float]] = []
    for token in line.split(";"):
        token = token.strip()
        if not token:
            continue
        parts = [part.strip() for part in token.split(",") if part.strip()]
        if len(parts) < 2:
            continue
        x = _parse_float(parts[0])
        y = _parse_float(parts[1])
        bulge = 0.0
        for part in parts[2:]:
            if part.upper().startswith("A"):
                bulge = _parse_float(part[1:])
        raw_points.append((x, y, bulge))

    if not raw_points:
        return []

    polyline: Polyline = [(raw_points[0][0], raw_points[0][1])]
    for prev, current in zip(raw_points, raw_points[1:]):
        p0 = (prev[0], prev[1])
        p1 = (current[0], current[1])
        segment = _arc_points_from_bulge(p0, p1, current[2])
        polyline.extend(segment[1:])
    return polyline


def load_lff_font(path: Path) -> LffFont:
    glyphs: dict[str, Glyph] = {}
    letter_spacing = 1.0
    word_spacing = 4.0
    current_char: str | None = None
    current_lines: list[Polyline] = []

    def flush() -> None:
        nonlocal current_char, current_lines
        if current_char is None:
            return
        points = [point for polyline in current_lines for point in polyline]
        if points:
            xs = [point[0] for point in points]
            glyphs[current_char] = Glyph(current_char, current_lines, min(xs), max(xs))
        else:
            glyphs[current_char] = Glyph(current_char, [], 0.0, 0.0)
        current_char = None
        current_lines = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("# LetterSpacing:"):
                letter_spacing = _parse_float(line.split(":", 1)[1])
            elif line.startswith("# WordSpacing:"):
                word_spacing = _parse_float(line.split(":", 1)[1])
            continue
        if line.startswith("[") and "]" in line:
            flush()
            code = line[1 : line.index("]")]
            try:
                current_char = chr(int(code, 16))
            except ValueError:
                current_char = None
            current_lines = []
            continue
        if current_char is not None:
            polyline = _parse_lff_line(line)
            if len(polyline) >= 2:
                current_lines.append(polyline)
    flush()

    if not glyphs:
        raise RuntimeError(f"No glyphs parsed from {path}")
    return LffFont(glyphs=glyphs, letter_spacing=letter_spacing, word_spacing=word_spacing)


def _glyph_for(font: LffFont, char: str) -> Glyph | None:
    manual = _manual_glyph_for(char)
    if manual is not None:
        return manual
    return font.glyphs.get(char) or font.glyphs.get(char.upper())


def text_to_lff_polylines(
    font: LffFont,
    text: str,
    *,
    shear: float,
    missing: set[str],
) -> tuple[list[Polyline], float]:
    x_cursor = 0.0
    polylines: list[Polyline] = []

    for char in text:
        if char.isspace():
            x_cursor += font.word_spacing
            continue

        glyph = _glyph_for(font, char)
        if glyph is None:
            missing.add(char)
            x_cursor += font.word_spacing * 0.5
            continue

        for source_polyline in glyph.polylines:
            polyline: Polyline = []
            for x, y in source_polyline:
                normalized_x = x - glyph.min_x
                slanted_x = normalized_x + (y - FONT_EM_MIN) * shear
                polyline.append((x_cursor + slanted_x, y))
            if len(polyline) >= 2:
                polylines.append(polyline)

        x_cursor += max(glyph.width, 0.8) + font.letter_spacing

    return polylines, x_cursor


def _unit(vector: Point) -> Point:
    length = math.hypot(vector[0], vector[1])
    if length < 1e-9:
        return (1.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def _project_rect(rect: fitz.Rect, u: Point, v: Point) -> tuple[float, float, float, float]:
    corners = [
        (rect.x0, rect.y0),
        (rect.x1, rect.y0),
        (rect.x1, rect.y1),
        (rect.x0, rect.y1),
    ]
    t_values = [point[0] * u[0] + point[1] * u[1] for point in corners]
    s_values = [point[0] * v[0] + point[1] * v[1] for point in corners]
    return min(t_values), max(t_values), min(s_values), max(s_values)


def _page_point_from_basis(t: float, s: float, u: Point, v: Point) -> Point:
    return (u[0] * t + v[0] * s, u[1] * t + v[1] * s)


def _extract_text_lines(page: fitz.Page) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir", (1.0, 0.0))
            spans = line.get("spans", [])
            for span in spans:
                text = span.get("text", "")
                if not text.strip():
                    continue
                bbox = fitz.Rect(span["bbox"])
                if bbox.is_empty or bbox.width <= 0.5 or bbox.height <= 0.5:
                    continue
                lines.append({"text": text, "bbox": bbox, "dir": direction})
    return lines


def _line_display_text(line: dict[str, object]) -> str:
    text = str(line["text"]).strip()
    # KOMPAS may expose the square dimension sign in "□5" as vector geometry
    # and only return the digit in PDF text extraction. Render the sign
    # deliberately so it is controlled by the same single-line font path.
    if text == "5":
        return "□5"
    return text


def _line_render_rect(line: dict[str, object]) -> fitz.Rect:
    rect = fitz.Rect(line["bbox"])  # type: ignore[arg-type]
    if _line_display_text(line) == "□5":
        h = max(1.0, float(rect.height))
        return fitz.Rect(rect.x0 - h * 1.45, rect.y0 - h * 0.18, rect.x1 + h * 0.10, rect.y1 + h * 0.08)
    return rect


def _looks_like_stamp_cell(text: str, rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    normalized = text.strip().lower().replace(" ", "")
    stamp_words = {
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
    if normalized in stamp_words:
        return True
    if rect.x0 < page_rect.width * 0.46 and rect.y0 > page_rect.height * 0.55:
        return True
    return rect.height < 8.0 and rect.width < 80.0


def _normalized_text_key(text: str) -> str:
    return (
        text.lower()
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace("\n", "")
        .replace("\r", "")
        .replace('"', "")
        .replace("'", "")
        .replace("«", "")
        .replace("»", "")
        .replace("“", "")
        .replace("”", "")
    )


def _is_service_or_footer_text(text: str, rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    key = _normalized_text_key(text)
    service_markers = (
        "компас-3d",
        "аскон",
        "учебнаяверсия",
        "недлякоммерческогоиспользования",
        "всеправазащищены",
        "инв.№",
        "инв№",
        "взам.инв.№",
        "взаминв№",
        "№подл",
        "подпи дата",
        "подп.идата",
        "подпидата",
        "перв.примен",
        "первпримен",
        "справ.№",
        "справ№",
        "копировал",
    )
    if any(marker in key for marker in service_markers):
        return True
    left_service_text_band = rect.x0 < page_rect.width * 0.075
    if left_service_text_band and key in {
        "инв.",
        "инв",
        "№",
        "подл.",
        "подл",
        "взам.инв.",
        "взаминв",
        "дубл.",
        "дубл",
        "справ.",
        "справ",
    }:
        return True
    if key in {"формата4", "форматa4", "a4"}:
        return True
    bottom_footer_band = rect.y0 > page_rect.height * 0.965
    if bottom_footer_band and rect.height < page_rect.height * 0.04:
        return True
    return False


def _draw_polyline(shape: fitz.Shape, points: Iterable[Point]) -> None:
    fitz_points = [fitz.Point(x, y) for x, y in points]
    if len(fitz_points) >= 2:
        shape.draw_polyline(fitz_points)


def _line_to_page_polylines(
    font: LffFont,
    line: dict[str, object],
    *,
    fill: float,
    shear: float,
    missing: set[str],
) -> list[Polyline]:
    text = _line_display_text(line)
    rect = _line_render_rect(line)
    u = _unit(tuple(line.get("dir", (1.0, 0.0))))  # type: ignore[arg-type]
    v = (-u[1], u[0])
    t_min, t_max, s_min, s_max = _project_rect(rect, u, v)
    box_width = max(0.1, t_max - t_min)
    box_height = max(0.1, s_max - s_min)

    font_polylines, text_width = text_to_lff_polylines(
        font,
        text,
        shear=shear,
        missing=missing,
    )
    if not font_polylines or text_width <= 1e-6:
        return []

    font_height = FONT_EM_MAX - FONT_EM_MIN
    scale = box_height * fill / font_height
    if text_width * scale > box_width * 0.98:
        scale = box_width * 0.98 / text_width

    rendered_width = text_width * scale
    rendered_height = font_height * scale
    local_x0 = (box_width - rendered_width) * 0.5
    local_y0 = (box_height - rendered_height) * 0.5

    result: list[Polyline] = []
    for font_polyline in font_polylines:
        page_polyline: Polyline = []
        for x, y in font_polyline:
            local_x = local_x0 + x * scale
            local_y = local_y0 + (FONT_EM_MAX - y) * scale
            page_polyline.append(
                _page_point_from_basis(t_min + local_x, s_min + local_y, u, v)
            )
        if len(page_polyline) >= 2:
            result.append(page_polyline)
    return result


def _expanded_rect(rect: fitz.Rect, pad: float) -> fitz.Rect:
    return fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)


def _segment_length(p0: fitz.Point, p1: fitz.Point) -> float:
    return math.hypot(float(p1.x - p0.x), float(p1.y - p0.y))


def _segment_center(p0: fitz.Point, p1: fitz.Point) -> fitz.Point:
    return fitz.Point((float(p0.x) + float(p1.x)) * 0.5, (float(p0.y) + float(p1.y)) * 0.5)


def _segment_bbox(p0: fitz.Point, p1: fitz.Point) -> fitz.Rect:
    return fitz.Rect(
        min(float(p0.x), float(p1.x)),
        min(float(p0.y), float(p1.y)),
        max(float(p0.x), float(p1.x)),
        max(float(p0.y), float(p1.y)),
    )


def _is_long_structural_segment(p0: fitz.Point, p1: fitz.Point, rect: fitz.Rect) -> bool:
    dx = abs(float(p1.x - p0.x))
    dy = abs(float(p1.y - p0.y))
    length = _segment_length(p0, p1)
    axis_aligned = dx <= 0.08 or dy <= 0.08
    if not axis_aligned:
        return False
    return length > 40.0 or length > max(float(rect.width), float(rect.height)) * 1.8


def _should_drop_background_segment(
    p0: fitz.Point,
    p1: fitz.Point,
    text_rects: list[fitz.Rect],
) -> bool:
    center = _segment_center(p0, p1)
    bbox = _segment_bbox(p0, p1)
    for rect in text_rects:
        if center in rect and p0 in rect and p1 in rect:
            if _is_long_structural_segment(p0, p1, rect):
                return False
            return True
        if center in rect and bbox.width <= rect.width * 1.15 and bbox.height <= rect.height * 1.15:
            if _is_long_structural_segment(p0, p1, rect):
                return False
            return True
    return False


def _is_background_service_gutter_segment(
    p0: fitz.Point,
    p1: fitz.Point,
    page_rect: fitz.Rect,
) -> bool:
    bbox = _segment_bbox(p0, p1)
    length = _segment_length(p0, p1)
    dx = abs(float(p1.x - p0.x))
    dy = abs(float(p1.y - p0.y))
    axis_aligned = dx <= 0.08 or dy <= 0.08

    left_service_band = bbox.x1 < float(page_rect.width) * 0.112
    bottom_footer_band = bbox.y0 > float(page_rect.height) * 0.962
    if not left_service_band and not bottom_footer_band:
        return False

    if axis_aligned and length >= 18.0:
        return False
    if length >= 34.0:
        return False
    return True


def _build_vector_background_without_text(
    background_pdf: Path,
    text_doc: fitz.Document,
) -> tuple[fitz.Document, dict[str, int]]:
    background = fitz.open(background_pdf)
    out = fitz.open()
    removed_segments = 0
    kept_segments = 0

    for page_index, bg_page in enumerate(background):
        text_page = text_doc[min(page_index, text_doc.page_count - 1)]
        text_rects = [
            _expanded_rect(_line_render_rect(line), 0.35)
            for line in _extract_text_lines(text_page)
        ]
        out_page = out.new_page(width=bg_page.rect.width, height=bg_page.rect.height)

        for drawing in bg_page.get_drawings():
            shape = out_page.new_shape()
            for item in drawing.get("items", []):
                kind = item[0]
                if kind == "l":
                    p0, p1 = item[1], item[2]
                    if _is_background_service_gutter_segment(p0, p1, bg_page.rect):
                        removed_segments += 1
                        continue
                    if _should_drop_background_segment(p0, p1, text_rects):
                        removed_segments += 1
                        continue
                    shape.draw_line(p0, p1)
                    kept_segments += 1
                elif kind == "qu":
                    if hasattr(shape, "draw_quad"):
                        shape.draw_quad(item[1])
                    kept_segments += 1
            shape.finish(
                color=drawing.get("color") or (0, 0, 0),
                width=float(drawing.get("width") or 0.45),
            )
            shape.commit()

    background.close()
    return out, {"removed_background_text_segments": removed_segments, "kept_background_segments": kept_segments}


def _write_text_only_gcode(path: Path, polylines: list[Polyline]) -> None:
    lines = [
        "(Experimental text-only G-code from LibreCAD OpenGOST LFF)",
        "G21",
        "G90",
        "G0 Z3.500",
    ]
    for polyline in polylines:
        if len(polyline) < 2:
            continue
        x0 = polyline[0][0] * PT_TO_MM
        y0 = -polyline[0][1] * PT_TO_MM
        lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
        lines.append("G1 Z0.000 F600")
        for x_pt, y_pt in polyline[1:]:
            lines.append(f"G1 X{x_pt * PT_TO_MM:.3f} Y{-y_pt * PT_TO_MM:.3f} F1800")
        lines.append("G0 Z3.500")
    lines.append("M2")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_lff_preview(
    source_pdf: Path,
    font_path: Path,
    out_dir: Path,
    *,
    background_pdf: Path | None = None,
    fill: float = 0.86,
    stamp_fill: float = 0.62,
    shear: float = 0.24,
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    font = load_lff_font(font_path)
    resolved_background = background_pdf or _clean_source_for(source_pdf) or source_pdf
    text_doc = fitz.open(source_pdf)
    background_cleanup: dict[str, int] = {"removed_background_text_segments": 0, "kept_background_segments": 0}
    if resolved_background != source_pdf:
        doc, background_cleanup = _build_vector_background_without_text(resolved_background, text_doc)
    else:
        doc = fitz.open(resolved_background)
    missing: set[str] = set()
    rendered_polylines: list[Polyline] = []
    line_count = 0

    for page_index, page in enumerate(doc):
        text_page = text_doc[min(page_index, text_doc.page_count - 1)]
        lines = _extract_text_lines(text_page)
        line_count += len(lines)
        if resolved_background == source_pdf:
            for line in lines:
                rect = fitz.Rect(line["bbox"])  # type: ignore[arg-type]
                page.add_redact_annot(_expanded_rect(rect, 0.15))
            if lines:
                page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                    text=fitz.PDF_REDACT_TEXT_REMOVE,
                )

        shape = page.new_shape()
        page_polylines: list[Polyline] = []
        for line in lines:
            line_rect = fitz.Rect(line["bbox"])  # type: ignore[arg-type]
            if _is_service_or_footer_text(str(line["text"]), line_rect, page.rect):
                continue
            line_fill = stamp_fill if _looks_like_stamp_cell(str(line["text"]), line_rect, page.rect) else fill
            page_polylines.extend(
                _line_to_page_polylines(
                    font,
                    line,
                    fill=line_fill,
                    shear=shear,
                    missing=missing,
                )
            )
        for polyline in page_polylines:
            _draw_polyline(shape, polyline)
        stroke_width = 0.34
        shape.finish(color=(0, 0, 0), width=stroke_width)
        shape.commit()
        rendered_polylines.extend(page_polylines)

    pdf_out = out_dir / "07_lff_opengost_text_preview.pdf"
    png_out = out_dir / "07_lff_opengost_text_preview.png"
    crop_out = out_dir / "07_lff_opengost_stamp_crop.png"
    gcode_out = out_dir / "07_lff_opengost_text_only.nc"
    report_out = out_dir / "07_lff_opengost_report.json"

    if pdf_out.exists():
        pdf_out.unlink()
    doc.save(pdf_out, deflate=True, garbage=4)
    doc.close()
    text_doc.close()

    preview = fitz.open(pdf_out)
    page = preview[0]
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(png_out)
    crop_rect = fitz.Rect(
        0,
        page.rect.height * 0.62,
        page.rect.width * 0.76,
        page.rect.height,
    )
    page.get_pixmap(matrix=fitz.Matrix(3.4, 3.4), clip=crop_rect, alpha=False).save(crop_out)
    preview.close()

    _write_text_only_gcode(gcode_out, rendered_polylines)

    report = {
        "source_pdf": str(source_pdf),
        "background_pdf": str(resolved_background),
        "used_clean_source_background": resolved_background != source_pdf,
        "font": str(font_path),
        "font_license": "SIL Open Font License 1.1 (declared in LFF header)",
        "text_lines": line_count,
        "rendered_polylines": len(rendered_polylines),
        "missing_chars": sorted(missing),
        "fill": fill,
        "stamp_fill": stamp_fill,
        "shear": shear,
        "background_cleanup": background_cleanup,
        "outputs": {
            "pdf": str(pdf_out),
            "png": str(png_out),
            "stamp_crop": str(crop_out),
            "text_only_gcode": str(gcode_out),
        },
    }
    report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--background", type=Path, default=None)
    parser.add_argument("--fill", type=float, default=0.86)
    parser.add_argument("--stamp-fill", type=float, default=0.62)
    parser.add_argument("--shear", type=float, default=0.24)
    args = parser.parse_args()

    report = render_lff_preview(
        args.source,
        args.font,
        args.out_dir,
        background_pdf=args.background,
        fill=args.fill,
        stamp_fill=args.stamp_fill,
        shear=args.shear,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
