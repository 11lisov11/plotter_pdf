"""Offline A2/A1 preparation; never opens a serial port. Existing A4/A3 stay unchanged."""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from PIL import Image

from scripts.stitch_gcode_polylines import read_draw_polylines
from src.plotter_backend.geometry.small_sheet_tiling import (
    SHEET_SIZES, StitchConfig, Tile, prepare_stitched_job, to_paper,
)
from src.plotter_backend.geometry.pdf_stroke_paths import native_pdf_strokes
from src.plotter_backend.geometry.sheet_title_block import _outside_paths, prepare_sheet_job

MM = 72 / 25.4


def trial_paths() -> list:
    paths = [[(15, 35), (340, 35), (340, 245), (15, 245), (15, 35)],
             [(15, 45), (340, 235)], [(15, 235), (340, 45)], [(25, 140), (330, 140)]]
    for radius in (58, 28):
        paths.append([(177.5 + radius * math.cos(i * 2 * math.pi / 360),
                       140 + radius * math.sin(i * 2 * math.pi / 360)) for i in range(361)])
    for x in range(25, 330, 18):
        paths.append([(x, 225), (min(x + 10, 330), 225)])
    for x in range(45, 320, 18):
        paths.append([(x, 58), (x + 12, 78)])
    return paths


def _ink(page, paths, offset=(0, 0)) -> None:
    shape = page.new_shape()
    for poly in paths:
        shape.draw_polyline([fitz.Point((x + offset[0]) * MM, (y + offset[1]) * MM) for x, y in poly])
    shape.finish(color=(0, 0, 0), width=0.15 * MM, lineCap=1, lineJoin=1, closePath=False)
    shape.commit()


def _text(page, x, y, text, size=9, color=(0.18, 0.22, 0.25)) -> None:
    page.insert_text((x * MM, y * MM), text, fontsize=size, color=color)


def _guide_rectangle(page, rect, offset, exclude=None, color=(0.35, 0.65, 0.85), width=0.5) -> None:
    x0, y0, x1, y1 = rect
    paths = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
    if exclude is not None:
        paths = _outside_paths(paths, exclude)
    shape = page.new_shape()
    for poly in paths:
        shape.draw_polyline([fitz.Point((x + offset[0]) * MM, (y + offset[1]) * MM) for x, y in poly])
    shape.finish(color=color, width=width, dashes="[4 3]", closePath=False)
    shape.commit()


def preview_from_gcode(output: Path, job: dict) -> Path:
    """All black strokes are decoded from FINAL serialized NC, not source paths."""
    config = StitchConfig(**job["config"])
    decoded = []
    for record in job["tiles"]:
        tile = Tile(**{key: record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
        machine = read_draw_polylines(output / record["file"], z_up=config.z_up, z_down=config.z_down)
        paper = [[to_paper(point, tile, config) for point in poly] for poly in machine]
        decoded.append((tile, machine, paper))
    right = max(tile.window_mm[2] for tile, _, _ in decoded)
    bottom = max(tile.window_mm[3] for tile, _, _ in decoded)
    doc = fitz.open()
    page = doc.new_page(width=(right + 24) * MM, height=(bottom + 38) * MM)
    drawing_scale = job.get("drawing_scale", 1.0)
    drawing_label = "DRAWING 1:1" if abs(drawing_scale - 1.0) < 1e-8 else f"DRAWING {drawing_scale * 100:.1f}% OF SOURCE"
    title = "SMALL PLOTTER / G-CODE RECONSTRUCTION / " + drawing_label
    if job.get("title_block"):
        title += f" / TITLE BLOCK {job['title_block']['scale'] * 100:.1f}%"
    _text(page, 12, 10, title, 12)
    _text(page, 12, 16, "Black = NC ink. Blue/orange = body-pass guides. Green = complete final-pass field. Colored guides are NOT plotted.", 9)
    offset = (12, 23)
    reserved_stamp = None
    if job.get("title_block"):
        box = job["title_block"]["target_bbox_mm"]
        reserved_stamp = (box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3)
    for transition in job["transitions"]:
        if job["tiles"][transition["to_pass"] - 1].get("role") == "title_block":
            continue
        previous = job["tiles"][transition["from_pass"] - 1]["window_mm"]
        following = job["tiles"][transition["to_pass"] - 1]["window_mm"]
        shared = (max(previous[0], following[0]), max(previous[1], following[1]),
                  min(previous[2], following[2]), min(previous[3], following[3]))
        page.draw_rect(fitz.Rect(*[(v + offset[i % 2]) * MM for i, v in enumerate(shared)]),
                       color=None, fill=(1, 0.95, 0.85), overlay=False)
    for record, (tile, _, paper) in zip(job["tiles"], decoded):
        stamp = record.get("role") == "title_block"
        guide = record["stamp_bbox_mm"] if stamp else tile.window_mm
        _guide_rectangle(page, guide, offset, None if stamp else reserved_stamp)
        if stamp:
            _guide_rectangle(page, tile.window_mm, offset, color=(0.05, 0.5, 0.3), width=1.5)
            _text(page, tile.window_mm[0] + offset[0] + 3, tile.window_mm[1] + offset[1] + 8,
                  f"PASS {tile.number:02d} FIELD / 180 x 280 mm / REPOSITION SHEET", 9, (0.05, 0.4, 0.24))
            _text(page, guide[0] + offset[0] + 2, guide[1] + offset[1] - 10,
                  f"PASS {tile.number:02d} / COMPLETE TITLE BLOCK / 180 mm", 8, (0.15, 0.4, 0.65))
        else:
            _text(page, tile.window_mm[0] + 16, tile.window_mm[1] + 29, f"PASS {tile.number:02d}", 8, (0.15, 0.4, 0.65))
        _ink(page, paper, offset)
    for transition in job["transitions"]:
        for label, (x, y) in zip(("A", "B"), transition["marks_paper_mm"]):
            _text(page, x + offset[0] + 3, y + offset[1] + 1, label, 9, (0.1, 0.4, 0.7))
    _text(page, 12, bottom + 33, "Same sheet, moved between passes. Do not rotate it. Marks are plotted once; remove them afterwards.", 8)
    for record, (tile, machine, _) in zip(job["tiles"], decoded):
        page = doc.new_page(width=210 * MM, height=297 * MM)
        label = "COMPLETE TITLE BLOCK / 180 mm" if record.get("role") == "title_block" else "NC PEN-DOWN / 1:1"
        _text(page, 15, 5.5, f"PASS {tile.number:02d} / {label}", 8)
        field_color = (0.05, 0.5, 0.3) if record.get("role") == "title_block" else (0.35, 0.65, 0.85)
        page.draw_rect(fitz.Rect(15 * MM, 8.5 * MM, 195 * MM, 288.5 * MM),
                       color=field_color, width=0.8, dashes="[4 3]")
        local = [[(x, y - config.work_min_y) for x, y in poly] for poly in machine]
        _ink(page, local, (15, 8.5))
        _text(page, 15, 293, "Colored field boundary is a preview guide, NOT a pen stroke.", 7)
    result = output / "Preview_from_Gcode.pdf"
    result.write_bytes(doc.tobytes(garbage=4, deflate=True))
    if job.get("title_block"):
        single = fitz.open()
        single.insert_pdf(doc, from_page=len(doc) - 1, to_page=len(doc) - 1)
        (output / "Title_block_from_Gcode.pdf").write_bytes(single.tobytes(garbage=4, deflate=True))
        single.close()
    doc.close()
    return result


def render_preview(pdf: Path) -> Path:
    # Render the delivered PDF itself, not the source drawing or path arrays.
    target = ROOT / "tmp" / "pdfs" / "small_stitch_trial_preview.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf) as document:
        frames = []
        for page in list(document)[:3]:
            pix = page.get_pixmap(matrix=fitz.Matrix(0.8, 0.8), alpha=False)
            frames.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    width = sum(frame.width for frame in frames) + 16 * (len(frames) + 1)
    canvas = Image.new("RGB", (width, max(frame.height for frame in frames) + 32), "#dce1e5")
    x = 16
    for frame in frames:
        canvas.paste(frame, (x, 16))
        x += frame.width + 16
    canvas.save(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--trial", action="store_true", help="Prepare only two adjacent A2/A1 passes of a clean diagnostic drawing")
    source.add_argument("--pdf", type=Path, help="Use the EXISTING small-plotter recognition algorithm, then tile its canonical mm output")
    source.add_argument("--source-json", type=Path, help='Canonical {"units":"mm","page_size_mm":[w,h],"polylines":[...]}')
    parser.add_argument("--format", choices=("A2", "A1"), default="A2")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--drawing-mode", choices=("computer_graphics", "descriptive_geometry"), default="computer_graphics")
    parser.add_argument("--mark-radius-mm", type=float, default=1.2)
    parser.add_argument("--mark-clearance-mm", type=float, default=0.8)
    parser.add_argument("--no-frame", action="store_true", help="Remove sheet borders, preserving title-block table edges")
    parser.add_argument("--whole-stamp", action="store_true", help="Skip empty drawing windows; scale ONLY the title block to <=180 mm and prepare one dedicated final pass")
    parser.add_argument("--fit-format", action="store_true", help="Explicitly fit the source drawing to the requested A2/A1 format; keep the whole stamp at its independent 180 mm width")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    name = "Small_stitch_trial" if args.trial else (args.pdf or args.source_json).stem + "_small_stitch"
    output = (args.output or ROOT / "_plotter_jobs" / name).resolve()
    width, height = SHEET_SIZES[args.format]
    if args.trial:
        paths = trial_paths()
    elif args.source_json:
        payload = json.loads(args.source_json.read_text(encoding="utf-8"))
        if payload.get("units") != "mm":
            raise ValueError("Source JSON must explicitly declare canonical millimeter units")
        width, height = payload["page_size_mm"]
        paths = payload["polylines"]
    else:
        from scripts import prepare_plotter_ready_new_algorithm as pipeline
        settings = pipeline.settings_for_machine_profile("a4_desktop", drawing_mode=args.drawing_mode)
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="small_stitch_source_", dir=ROOT / "tmp") as directory:
            scratch = Path(directory)
            with fitz.open(args.pdf) as original:
                if not 1 <= args.page <= len(original):
                    raise ValueError("Requested PDF page does not exist")
                single = fitz.open()
                single.insert_pdf(original, from_page=args.page - 1, to_page=args.page - 1)
                source_pdf = scratch / "source.pdf"
                single.save(source_pdf)
                single.close()
            built = pipeline._build_source(scratch, source_pdf, {"kind": "drawing", "a3_two_pass": True}, settings)
            if built.missing_chars:
                raise ValueError(f"Recognition has missing glyphs: {built.missing_chars}; refusing incomplete output")
            # Preserve original curves; the SVG/background cleanup route can
            # discard complete arcs in some CAD PDFs. PDF text is NOT outlined.
            geometry = native_pdf_strokes(source_pdf)
            text_paths = built.polylines[-built.text_polylines:] if built.text_polylines else []
            width, height = built.page_w_mm, built.page_h_mm
            paths = [*geometry, *text_paths]
    config = StitchConfig(mark_radius_mm=args.mark_radius_mm, mark_clearance_mm=args.mark_clearance_mm)
    job = prepare_sheet_job(paths, width, height, args.format, output, config=config,
                            trial_first_two=args.trial, no_frame=args.no_frame, whole_stamp=args.whole_stamp,
                            fit_format=args.fit_format)
    pdf = preview_from_gcode(output, job)
    image = render_preview(pdf)
    print(json.dumps({"output": str(output), "passes": len(job["tiles"]), "full_pass_count": job["full_pass_count"],
                      "target_sheet_size_mm": job["sheet_size_mm"], "drawing_source_scale": job.get("drawing_scale", 1.0),
                      "grid": job["grid_columns_rows"], "pdf_from_final_nc": str(pdf), "preview": str(image),
                      "hardware_accessed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
