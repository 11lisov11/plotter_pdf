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
    a4_sector_preview_from_gcode(output, job)
    registration_guide_from_gcode(output, job)
    first_pass_placement_from_gcode(output, job)
    return result


def first_pass_placement_from_gcode(output: Path, job: dict, labels: dict | None = None) -> Path:
    """Full-paper location and top-view setup; all arrows/text are PDF-only."""
    text = {
        "title": "FIRST POSITION / FULL SHEET AND SMALL PLOTTER",
        "subtitle": "Instruction only: colored fields, numbers and arrows are NOT plotted.",
        "first": "FIRST: PASS 1", "second": "NEXT: PASS 2", "start": "O / START",
        "notes_title": "HOW TO PLACE THE PAPER",
        "notes": "1. Keep the whole sheet in landscape orientation.\n\n2. Mark O: {ox:.0f} mm from the LEFT paper edge, {oy:.0f} mm from the TOP edge.\n\n3. Align O to the calibrated field TOP-LEFT, NOT machine HOME.\n\n4. Keep ONE flat layer in the working field; support excess paper outside.\n\n5. Draw pass 1. It draws A/B near the field bottom.\n\n6. Wait for PEN UP, then move PAPER ONLY: {shift}.\n\n7. Align A under the pen; check B. Do not reset XY zero.",
        "detail_title": "PAPER MOVEMENT / TOP VIEW OF THE CALIBRATED FIELD",
        "panel1": "1. DRAW PASS 1", "panel2": "2. PEN PARKS; PAPER STAYS", "panel3": "3. MOVE PAPER; ALIGN A/B",
        "field": "WORK FIELD 180 x 280 mm", "pen": "PEN UP", "paper": "PAPER",
        "caption1": "O is the top-left corner of the FIRST source window, not the full paper corner. A/B are drawn by pass 1.",
        "caption2": "The carriage automatically parks at the NEXT A position. Old A/B are still at the bottom of the paper. Do not move the carriage by hand.",
        "caption3": "After the PAPER moves, old A/B reach the top of the field. Align A, secure the paper, then verify B with a pen-up command before pass 2.",
        "footer": "Same sheet, same orientation, fixed XY zero. This is NOT the nominal eight-A4 fold grid.",
    }
    if labels:
        text.update(labels)
    config = StitchConfig(**job["config"])
    first_record, second_record = job["tiles"][:2]
    transition = job["transitions"][0]
    first = Tile(**{key: first_record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
    second = Tile(**{key: second_record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
    width, height = job["sheet_size_mm"]
    all_paper = []
    first_local = []
    for record in job["tiles"]:
        tile = Tile(**{key: record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
        paths = read_draw_polylines(output / record["file"], z_up=config.z_up, z_down=config.z_down)
        all_paper.extend([[to_paper(p, tile, config) for p in poly] for poly in paths])
        if record["number"] == first.number:
            first_local = [[(x, y - config.work_min_y) for x, y in poly] for poly in paths]
    dx, dy = second.origin_mm[0] - first.origin_mm[0], second.origin_mm[1] - first.origin_mm[1]
    shift = f"{abs(dy):.0f} mm UP" if dy >= 0 else f"{abs(dy):.0f} mm DOWN"
    if abs(dx) > 0.001:
        shift += f", {abs(dx):.0f} mm " + ("LEFT" if dx > 0 else "RIGHT")
    document = fitz.open()
    font_file = "C:/Windows/Fonts/arial.ttf"

    def new_page():
        page = document.new_page(width=420 * MM, height=297 * MM)
        page.insert_font(fontname="Placement", fontfile=font_file)
        return page

    def line(page, x, y, value, size=10, color=(0.12, 0.16, 0.2)):
        page.insert_text((x * MM, y * MM), str(value), fontname="Placement", fontsize=size, color=color)

    def paragraph(page, rect, value, size=10, color=(0.12, 0.16, 0.2)):
        page.insert_textbox(fitz.Rect(*(v * MM for v in rect)), value,
                            fontname="Placement", fontsize=size, color=color, lineheight=1.25)

    def arrow(page, a, b, color=(0.05, 0.35, 0.75), both=False):
        ax, ay = a; bx, by = b
        length = math.hypot(bx - ax, by - ay)
        if length < 0.001:
            return
        ux, uy = (bx - ax) / length, (by - ay) / length
        page.draw_line((ax * MM, ay * MM), (bx * MM, by * MM), color=color, width=1)
        ends = [(bx, by, ux, uy)] + ([(ax, ay, -ux, -uy)] if both else [])
        for x, y, vx, vy in ends:
            for side in (-1, 1):
                end = ((x - 2 * vx - side * vy) * MM, (y - 2 * vy + side * vx) * MM)
                page.draw_line((x * MM, y * MM), end, color=color, width=1)

    def paths_on(page, paths, origin, scale, color=(0, 0, 0)):
        shape = page.new_shape()
        for poly in paths:
            shape.draw_polyline([fitz.Point((origin[0] + x * scale) * MM,
                                           (origin[1] + y * scale) * MM) for x, y in poly])
        shape.finish(color=color, width=0.35, lineCap=1, lineJoin=1, closePath=False)
        shape.commit()

    blue, green, red = (0.05, 0.35, 0.75), (0.0, 0.5, 0.25), (0.8, 0.1, 0.05)
    page = new_page()
    line(page, 12, 14, text["title"], 19)
    line(page, 12, 23, text["subtitle"], 10)
    origin, scale = (12.0, 49.0), min(268 / width, 190 / height)

    def paper_point(point):
        return origin[0] + point[0] * scale, origin[1] + point[1] * scale

    def paper_rect(box):
        return fitz.Rect(*[value * MM for point in (paper_point(box[:2]), paper_point(box[2:])) for value in point])

    page.draw_rect(paper_rect((0, 0, width, height)), color=(0.55, 0.6, 0.65), width=0.7)
    page.draw_rect(paper_rect(first.window_mm), color=None, fill=(0.91, 0.95, 1))
    shared = (max(first.window_mm[0], second.window_mm[0]), max(first.window_mm[1], second.window_mm[1]),
              min(first.window_mm[2], second.window_mm[2]), min(first.window_mm[3], second.window_mm[3]))
    page.draw_rect(paper_rect(shared), color=None, fill=(1, 0.91, 0.55))
    paths_on(page, all_paper, origin, scale)
    page.draw_rect(paper_rect(first.window_mm), color=blue, width=2)
    page.draw_rect(paper_rect(second.window_mm), color=green, width=1.4, dashes="[5 3]")
    x, y = paper_point(first.origin_mm)
    page.draw_circle((x * MM, y * MM), 1.6 * MM, color=red, width=1.2)
    line(page, x + 3, y - 3, text["start"], 11, red)
    line(page, x + 4, y + 10, text["first"], 13, blue)
    sx, sy = paper_point(second.origin_mm)
    line(page, sx + 4, sy + 12, text["second"], 12, green)
    arrow(page, (origin[0], 36), (x, 36), blue, True)
    line(page, origin[0] + (x - origin[0]) / 2 - 8, 33, f"{first.origin_mm[0]:.0f} mm", 11, blue)
    end_x = paper_point((first.window_mm[2], first.window_mm[1]))[0]
    arrow(page, (x, 36), (end_x, 36), blue, True)
    line(page, (x + end_x) / 2 - 8, 33, "180 mm", 11, blue)
    bottom_y = paper_point((first.window_mm[0], first.window_mm[3]))[1]
    arrow(page, (x - 5, y), (x - 5, bottom_y), blue, True)
    line(page, x - 23, (y + bottom_y) / 2, "280 mm", 10, blue)
    for letter, point in zip(("A", "B"), transition["marks_paper_mm"]):
        px, py = paper_point(point)
        page.draw_circle((px * MM, py * MM), 1.2 * MM, color=red, width=1.1)
        line(page, px + 2, py - 2, letter, 12, red)
    line(page, 294, 44, text["notes_title"], 15, blue)
    notes = text["notes"].format(ox=first.origin_mm[0], oy=first.origin_mm[1], shift=shift)
    paragraph(page, (294, 51, 408, 264), notes, 11)
    paragraph(page, (12, 253, 280, 283), text["footer"], 11)

    page = new_page()
    line(page, 12, 14, text["detail_title"], 18)
    panel_x = (12.0, 150.0, 288.0)
    field_width = 82.0
    zoom = field_width / config.work_width
    field_height = config.work_height * zoom
    field_origins = [(left + 12, 54.0) for left in panel_x]
    shifted = [[(x - dx, y - dy) for x, y in poly] for poly in first_local]
    from src.plotter_backend.geometry.small_sheet_tiling import clip_paths
    shifted = clip_paths(shifted, (0, 0, config.work_width, config.work_height))
    for index, (left, field_origin) in enumerate(zip(panel_x, field_origins)):
        paragraph(page, (left, 24, left + 120, 44), text[f"panel{index + 1}"], 14, blue if index == 0 else green)
        fx, fy = field_origin
        page.draw_rect(fitz.Rect(fx * MM, fy * MM, (fx + field_width) * MM, (fy + field_height) * MM),
                       color=blue if index == 0 else green, width=1.2)
        line(page, fx, 49, text["field"], 8)
        paths_on(page, shifted if index == 2 else first_local, field_origin, zoom,
                 (0.3, 0.3, 0.3) if index == 1 else (0, 0, 0))
        for letter, machine in zip(("A", "B"), transition["next_machine_mm"] if index == 2 else transition["previous_machine_mm"]):
            px = fx + machine[0] * zoom
            py = fy + (machine[1] - config.work_min_y) * zoom
            page.draw_circle((px * MM, py * MM), 0.9 * MM, color=red, width=1.1)
            line(page, px + 1, py - 3, letter, 11, red)
        if index == 0:
            page.draw_circle((fx * MM, fy * MM), 1.1 * MM, color=red, width=1.2)
            line(page, fx + 3, fy + 7, "O", 11, red)
            home = (fx, fy - config.work_min_y * zoom)
            line(page, home[0], home[1] + 6, "HOME != O", 9, red)
        else:
            park_x = fx + transition["next_machine_mm"][0][0] * zoom
            park_y = fy + (transition["next_machine_mm"][0][1] - config.work_min_y) * zoom
            page.draw_circle((park_x * MM, park_y * MM), 1.5 * MM, color=green, width=1.5)
            line(page, park_x + 7, park_y + 10, text["pen"], 9, green)
            arrow(page, (park_x + 7, park_y + 7), (park_x, park_y), green)
        if index == 2:
            arrow_x = fx + field_width + 7
            old_y = fy + (transition["previous_machine_mm"][0][1] - config.work_min_y) * zoom
            new_y = fy + (transition["next_machine_mm"][0][1] - config.work_min_y) * zoom
            arrow(page, (arrow_x, old_y), (arrow_x, new_y), blue)
            line(page, fx + 12, fy + field_height + 12, f"{abs(dy):.0f} mm", 12, blue)
            line(page, fx + 12, fy + field_height + 19, text["paper"], 10, blue)
        paragraph(page, (left, 211, left + 120, 273), text[f"caption{index + 1}"], 11)
    line(page, 12, 287, text["footer"], 9)
    result = output / "First_pass_placement.pdf"
    result.write_bytes(document.tobytes(garbage=4, deflate=True))
    document.close()
    return result


def registration_guide_from_gcode(output: Path, job: dict) -> Path:
    """Real overlapping machine windows, not nominal A4 fold boundaries."""
    config = StitchConfig(**job["config"])
    decoded = []
    for record in job["tiles"]:
        tile = Tile(**{key: record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
        machine = read_draw_polylines(output / record["file"], z_up=config.z_up, z_down=config.z_down)
        paper = [[to_paper(point, tile, config) for point in poly] for poly in machine]
        decoded.append((tile, paper))
    document = fitz.open()
    offset = (12.0, 34.0)
    first, first_ink = decoded[0]
    window = first.window_mm
    page = document.new_page(width=(window[2] - window[0] + 24) * MM,
                             height=(window[3] - window[1] + 91) * MM)
    _text(page, 12, 10, "START / PASS 1 / REAL MACHINE FIELD", 12)
    _text(page, 12, 17, "180 x 280 mm field. NOT an entire 210 x 297 mm A4 sector.", 8)
    _text(page, 12, 24, "Colored boundaries and labels are instructions only, not plotted.", 8)
    local = [[(x - window[0], y - window[1]) for x, y in poly] for poly in first_ink]
    _ink(page, local, offset)
    _guide_rectangle(page, (0, 0, window[2] - window[0], window[3] - window[1]), offset,
                     color=(0.05, 0.35, 0.75), width=1.2)
    baseline = window[3] - window[1] + 45
    _text(page, 12, baseline, f"A1 source window starts at X={first.origin_mm[0]:.3f}, Y={first.origin_mm[1]:.3f} mm.", 8)
    _text(page, 12, baseline + 7, "Measure from the TOP-LEFT corner of the full paper.", 8)
    _text(page, 12, baseline + 14, "Align that paper point to the calibrated field TOP-LEFT, NOT HOME.", 8)
    _text(page, 12, baseline + 21, "Keep the paper orientation fixed. Do not reset XY zero between passes.", 8)
    _text(page, 12, baseline + 28, "Do not use the eight nominal A4 fold sectors as machine boundaries.", 8)
    for index, transition in enumerate(job["transitions"]):
        previous, old_ink = decoded[index]
        following, new_ink = decoded[index + 1]
        a, b = previous.window_mm, following.window_mm
        union = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
        shared = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
        width, height = union[2] - union[0], union[3] - union[1]
        page = document.new_page(width=(width + 24) * MM, height=(height + 100) * MM)
        _text(page, 12, 10, f"PASS {previous.number} > PASS {following.number} / PAPER REGISTRATION", 12)
        _text(page, 12, 17, "BLUE = previous field. GREEN = next field. YELLOW = shared paper.", 9)
        _text(page, 12, 24, "The SAME two crosses A/B must remain inside BOTH machine fields.", 9)

        def local_point(point):
            return point[0] - union[0], point[1] - union[1]

        def local_box(box):
            return (box[0] - union[0], box[1] - union[1], box[2] - union[0], box[3] - union[1])

        shared_local = local_box(shared)
        page.draw_rect(fitz.Rect(*[(v + offset[k % 2]) * MM for k, v in enumerate(shared_local)]),
                       color=None, fill=(1, 0.93, 0.68), overlay=False)
        _ink(page, [[local_point(point) for point in poly] for poly in old_ink], offset)
        _ink(page, [[local_point(point) for point in poly] for poly in new_ink], offset)
        _guide_rectangle(page, local_box(a), offset, color=(0.05, 0.35, 0.75), width=1.3)
        _guide_rectangle(page, local_box(b), offset, color=(0.0, 0.5, 0.25), width=1.3)
        for letter, point in zip(("A", "B"), transition["marks_paper_mm"]):
            x, y = local_point(point)
            center = fitz.Point((x + offset[0]) * MM, (y + offset[1]) * MM)
            page.draw_circle(center, 2 * MM, color=(0.8, 0.1, 0.05), width=1.2)
            label_x = min(x + 4, width - 20)
            label_y = y - 4 if y > 8 else y + 7
            _text(page, label_x + offset[0], label_y + offset[1], f"{index + 1}{letter}", 15, (0.8, 0.1, 0.05))
        dx = following.origin_mm[0] - previous.origin_mm[0]
        dy = following.origin_mm[1] - previous.origin_mm[1]
        movements = []
        if abs(dx) > 0.001:
            movements.append(f"{abs(dx):.3f} mm " + ("LEFT" if dx > 0 else "RIGHT"))
        if abs(dy) > 0.001:
            movements.append(f"{abs(dy):.3f} mm " + ("UP" if dy > 0 else "DOWN"))
        baseline = height + 46
        _text(page, 12, baseline, "PAPER shift: " + "; ".join(movements), 9)
        _text(page, 12, baseline + 8, f"Shared area: {shared[2] - shared[0]:.3f} x {shared[3] - shared[1]:.3f} mm.", 9)
        _text(page, 12, baseline + 16, "1. Finish the previous pass. Wait for PEN UP and the parked carriage.", 8)
        _text(page, 12, baseline + 23, "2. Move PAPER ONLY until the existing cross A is under the pen; secure it.", 8)
        _text(page, 12, baseline + 30, "3. Check cross B with the raised pen. Correct alignment before drawing.", 8)
        _text(page, 12, baseline + 37, "Do not move the carriage by hand, rotate paper, or reset XY zero.", 8)
        if job["tiles"][index + 1].get("role") == "title_block":
            _text(page, 12, baseline + 45, "The next GREEN field draws the COMPLETE title block in ONE pass.", 8)
    result = output / "Registration_guide.pdf"
    result.write_bytes(document.tobytes(garbage=4, deflate=True))
    document.close()
    return result


def a4_sector_preview_from_gcode(output: Path, job: dict) -> Path:
    """Operator-only A4 paper sectors; never add their numbers/lines to NC."""
    width, height = job["sheet_size_mm"]
    landscape = width >= height
    if job["sheet_format"] == "A1":
        columns, rows = (4, 2) if landscape else (2, 4)
        cell_width, cell_height = (210.0, 297.0) if landscape else (297.0, 210.0)
    else:
        columns, rows = 2, 2
        cell_width, cell_height = (297.0, 210.0) if landscape else (210.0, 297.0)
    config = StitchConfig(**job["config"])
    paper_paths = []
    for record in job["tiles"]:
        tile = Tile(**{key: record[key] for key in ("number", "row", "column", "origin_mm", "window_mm", "draw_rect_mm")})
        machine = read_draw_polylines(output / record["file"], z_up=config.z_up, z_down=config.z_down)
        paper_paths.extend([[to_paper(point, tile, config) for point in poly] for poly in machine])
    links = job["transitions"]
    legend_rows = math.ceil(len(links) / 3)
    document = fitz.open()
    page = document.new_page(width=(width + 24) * MM, height=(height + 52 + 8 * legend_rows) * MM)
    _text(page, 12, 10, f"{job['sheet_format']} / {columns * rows} A4 PAPER SECTORS / NUMBERS 1-{columns * rows}", 17)
    _text(page, 12, 17, "BLUE: A4 sectors, not pass numbers. RED: existing A/B registration pairs. Colored guides and labels are NOT plotted.", 11)
    offset = (12.0, 25.0)
    _ink(page, paper_paths, offset)
    color = (0.05, 0.35, 0.75)
    page.draw_rect(fitz.Rect(12 * MM, 25 * MM, (12 + width) * MM, (25 + height) * MM),
                   color=(0.55, 0.6, 0.65), width=0.6)
    for column in range(1, columns):
        x = (offset[0] + column * cell_width) * MM
        page.draw_line((x, offset[1] * MM), (x, (offset[1] + height) * MM), color=color, width=1.1)
    for row in range(1, rows):
        y = (offset[1] + row * cell_height) * MM
        page.draw_line((offset[0] * MM, y), ((offset[0] + width) * MM, y), color=color, width=1.1)
    segments = [(a, b) for poly in paper_paths for a, b in zip(poly, poly[1:])]

    def empty_label_area(x, y):
        return all(max(a[0], b[0]) < x - 2 or min(a[0], b[0]) > x + 24
                   or max(a[1], b[1]) < y - 2 or min(a[1], b[1]) > y + 24 for a, b in segments)

    for row in range(rows):
        for column in range(columns):
            left, top = column * cell_width, row * cell_height
            right, bottom = min(width, left + cell_width), min(height, top + cell_height)
            candidates = [(left + 8, top + 8), (right - 30, top + 8),
                          (left + 8, bottom - 30), (right - 30, bottom - 30)]
            x, y = next((point for point in candidates if empty_label_area(*point)), candidates[0])
            center = fitz.Point((x + 11 + offset[0]) * MM, (y + 11 + offset[1]) * MM)
            page.draw_circle(center, 11 * MM, color=color, fill=(1, 1, 1), width=1.2)
            number = str(row * columns + column + 1)
            size = 48
            length = fitz.get_text_length(number, fontname="helv", fontsize=size)
            page.insert_text((center.x - length / 2, center.y + size * 0.35), number,
                             fontname="helv", fontsize=size, color=color)
    registration_color = (0.8, 0.12, 0.08)
    for index, transition in enumerate(links, 1):
        for letter, (x, y) in zip(("A", "B"), transition["marks_paper_mm"]):
            center = fitz.Point((x + offset[0]) * MM, (y + offset[1]) * MM)
            # Outline the real, already plotted cross without covering its
            # precise center. The red ring and pair ID are PDF annotations only.
            page.draw_circle(center, 2.5 * MM, color=registration_color, width=1.4)
            label_x = min(max(x + 4, 0), width - 20)
            label_y = y - 4 if y >= 8 else y + 7
            _text(page, label_x + offset[0], label_y + offset[1], f"{index}{letter}",
                  18, registration_color)
    _text(page, 12, height + 35,
          f"Nominal A4: {cell_width:g} x {cell_height:g} mm. Black strokes restored from {len(job['tiles'])} NC passes; the drawing is unchanged.", 10)
    _text(page, 12, height + 44, "REGISTRATION: match cross A under the raised pen, then verify cross B before the next pass.",
          12, registration_color)
    for index, transition in enumerate(links):
        _text(page, 12 + (index % 3) * width / 3, height + 52 + (index // 3) * 8,
              f"{index + 1}A / {index + 1}B: pass {transition['from_pass']} > {transition['to_pass']}",
              14, registration_color)
    result = output / "A4_sectors_preview.pdf"
    result.write_bytes(document.tobytes(garbage=4, deflate=True))
    document.close()
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
