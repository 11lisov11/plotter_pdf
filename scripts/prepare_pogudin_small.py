"""Offline preparation of the supplied Pogudin CG/DG PDFs for the small plotter.

Uses the established PDF-geometry/OpenGOST-LFF route and small-machine layout.
No serial connections, calibration or drawing are performed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from PIL import Image, ImageDraw, ImageOps

from scripts import prepare_plotter_ready_new_algorithm as pipeline
from src import plotter_pdf_drawer as backend
from src.plotter_backend.geometry.clipping import clip_polylines_to_rect
from src.plotter_backend.geometry.path_processing import (
    remove_rectangular_border, trim_to_inner_drawing_frame, remove_sheet_border_keep_corner_table,
)
from src.plotter_backend.geometry.unique_strokes import unique_strokes
from src.plotter_backend.geometry.condition_images import extract_condition_miniatures

MM = 72 / 25.4


def actual_strokes(payload: str, settings):
    x = y = 0.0
    z = settings.z_up
    absolute = True
    motion = None
    result, current = [], []

    def finish():
        nonlocal current
        if len(current) > 1:
            result.append(current)
        current = []

    for raw in payload.splitlines():
        line = re.sub(r"\([^)]*\)|;.*$", "", raw).upper()
        pairs = re.findall(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", line)
        codes = [float(v) for k, v in pairs if k == "G"]
        words = {k: float(v) for k, v in pairs if k != "G"}
        if 90 in codes:
            absolute = True
        if 91 in codes:
            absolute = False
        if 92 in codes:
            finish()
            x, y, z = words.get("X", x), words.get("Y", y), words.get("Z", z)
            continue
        for code in codes:
            if code in (0, 1, 2, 3):
                motion = int(code)
        nx = words.get("X", x) if absolute else x + words.get("X", 0)
        ny = words.get("Y", y) if absolute else y + words.get("Y", 0)
        nz = words.get("Z", z) if absolute else z + words.get("Z", 0)
        moving = math.hypot(nx - x, ny - y) > 1e-9
        down = abs(z - settings.z_down) < abs(z - settings.z_up)
        if moving and down:
            if motion != 1:
                raise ValueError("Unexpected arc/rapid with the pen down")
            if not current:
                current = [(x, y)]
            current.append((nx, ny))
        elif moving:
            finish()
        if abs(nz - settings.z_up) < abs(nz - settings.z_down):
            finish()
        x, y, z = nx, ny, nz
    finish()
    return result


def cg_frame_and_tables(polylines, specification, logs, *, keep_frame):
    clipped = trim_to_inner_drawing_frame(polylines, logger=logs.append)
    left, right, top, bottom = backend.bounds_polylines(clipped)
    frame = (left, right, top, bottom)
    if specification:
        return clipped, frame, [], None
    width, height = right - left, bottom - top
    rows, auxiliary, vertical = [], [], []
    for poly in clipped:
        for a, b in zip(poly, poly[1:]):
            if abs(a[0] - b[0]) <= 0.005:
                vertical.append(((a[0] + b[0]) / 2, min(a[1], b[1]), max(a[1], b[1])))
            if abs(a[1] - b[1]) > 0.005:
                continue
            lo, hi = sorted((a[0], b[0])); y = (a[1] + b[1]) / 2
            if abs(hi - right) <= 0.005 and hi - lo >= width * 0.05 and top + height * 0.60 < y < bottom - 0.1:
                rows.append((lo, y))
            if abs(lo - left) <= 0.005 and 1 < hi - lo < width * 0.45 and top + 0.5 < y < top + height * 0.08:
                auxiliary.append((left, hi, top, y))
    if len({round(row[1], 2) for row in rows}) < 3:
        raise ValueError("Cannot safely identify the title table")
    table = (min(row[0] for row in rows), right, min(row[1] for row in rows), bottom)
    result = remove_rectangular_border(clipped, frame, preserve_regions=[] if keep_frame else [table])
    excluded = []
    for box in auxiliary:
        if not any(abs(x - box[1]) <= 0.005 and abs(lo - box[2]) <= 0.005 and abs(hi - box[3]) <= 0.005
                   for x, lo, hi in vertical):
            continue
        excluded.append(box)
        result = [poly for poly in result if not all(box[0] - .005 <= x <= box[1] + .005 and
                                                     box[2] - .005 <= y <= box[3] + .005 for x, y in poly)]
        result = remove_rectangular_border(result, box)
    if keep_frame:
        result.append([(left, top), (right, top), (right, bottom), (left, bottom), (left, top)])
    logs.append(f"CG frame retained={keep_frame}; table={table}; excluded={excluded}")
    return result, frame, excluded, table


def move_a3_stamp(paths, table, frame, scale, mx, my, work_w, work_h):
    x0, x1, y0, y1 = table
    left, _, top, _ = frame
    dx = work_w - ((x1 - left) * scale + mx)
    dy = work_h - ((y1 - top) * scale + my)
    output = []
    for poly in paths:
        current, previous_stamp = [], None
        for a, b in zip(poly, poly[1:]):
            vx, vy = b[0] - a[0], b[1] - a[1]
            cuts = [0., 1.]
            for origin, delta, edges in ((a[0], vx, (x0, x1)), (a[1], vy, (y0, y1))):
                if abs(delta) > 1e-12:
                    cuts += [t for edge in edges if 0 < (t := (edge - origin) / delta) < 1]
            cuts = sorted(set(cuts))
            for start, end in zip(cuts, cuts[1:]):
                p = (a[0] + vx * start, a[1] + vy * start)
                q = (a[0] + vx * end, a[1] + vy * end)
                cx, cy = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
                stamp = x0 - 1e-7 <= cx <= x1 + 1e-7 and y0 - 1e-7 <= cy <= y1 + 1e-7
                if stamp and ((abs(p[1] - y1) < .005 and abs(q[1] - y1) < .005) or
                              (abs(p[0] - x1) < .005 and abs(q[0] - x1) < .005)):
                    if len(current) > 1:
                        output.append(current)
                    current, previous_stamp = [], None
                    continue
                sx, sy = (dx, dy) if stamp else (0., 0.)
                mapped = [((x - left) * scale + mx + sx, (y - top) * scale + my + sy) for x, y in (p, q)]
                if previous_stamp != stamp or (current and math.dist(current[-1], mapped[0]) > 1e-7):
                    if len(current) > 1:
                        output.append(current)
                    current = []
                if not current:
                    current = [mapped[0]]
                current.append(mapped[1]); previous_stamp = stamp
        if len(current) > 1:
            output.append(current)
    return output


def render_from_nc(paths, two_pass, output, settings):
    pw, ph = (420., 297.) if two_pass else (210., 297.)
    ww, wh = settings.work_width * (2 if two_pass else 1), settings.work_height
    mx, my = (pw - ww) / 2, (ph - wh) / 2
    doc = fitz.open(); page = doc.new_page(width=pw * MM, height=ph * MM)
    shape = page.new_shape()
    for poly in paths:
        shape.draw_polyline([fitz.Point((mx + x) * MM, (my + y) * MM) for x, y in poly])
    shape.finish(color=(0, 0, 0), width=.15 * MM, lineCap=1, lineJoin=1, closePath=False)
    shape.commit()
    if two_pass:
        for y in range(0, int(wh), 13):
            page.draw_line(((mx + settings.work_width) * MM, (my + y) * MM),
                           ((mx + settings.work_width) * MM, (my + min(y + 8, wh)) * MM),
                           color=(.65, .65, .65), width=.15 * MM)
    output.write_bytes(doc.tobytes(garbage=4, deflate=True))
    page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False).save(output.with_suffix('.png'))
    return doc


def prepare_document(source, tag, names, mode, output, scratch, queue):
    settings = pipeline.settings_for_machine_profile('a4_desktop', drawing_mode=mode)
    aggregate = fitz.open(); thumbnails = []; pages_meta = []
    collection = output / tag; collection.mkdir()
    with fitz.open(source) as original:
        for index, page in enumerate(original):
            name = names[index] if names else f'Task_{index + 1:02d}'
            pack = collection / (name + '_pack'); pack.mkdir()
            one = fitz.open(); one.insert_pdf(original, from_page=index, to_page=index)
            single = pack / 'source.pdf'; one.save(single, deflate=True); one.close()
            w, h = page.rect.width / MM, page.rect.height / MM
            two = max(w, h) > 310
            text = page.get_text(); specification = 'Обозначение' in text and 'Наименование' in text
            logs = []
            geometry, page_w, page_h, _ = pipeline._geometry_polylines_from_pdf(single, scratch, logs)
            text_lines, _, _ = pipeline._text_lines_for_source(single)
            geometry = pipeline._remove_existing_text_geometry(geometry, text_lines, logs.append)
            condition_images = []
            if mode == 'descriptive_geometry':
                miniature_paths, condition_images = extract_condition_miniatures(single, logger=logs.append)
                geometry.extend(miniature_paths)
            if mode == 'computer_graphics':
                geometry, frame, excluded, table = cg_frame_and_tables(geometry, specification, logs, keep_frame=not two)
            else:
                geometry = trim_to_inner_drawing_frame(geometry, logger=logs.append)
                frame = backend.bounds_polylines(geometry)
                excluded, table = [], None
                if two:
                    geometry = remove_sheet_border_keep_corner_table(geometry, frame, logger=logs.append)
            left, right, top, bottom = frame
            retained = []
            for line in text_lines:
                box = pipeline._line_bbox_mm(line)
                if box is None:
                    continue
                x0, y0, x1, y1 = box
                if not (left <= (x0 + x1) / 2 <= right and top <= (y0 + y1) / 2 <= bottom):
                    continue
                if any(a - .005 <= x0 and x1 <= b + .005 and c - .005 <= y0 and y1 <= d + .005 for a, b, c, d in excluded):
                    continue
                retained.append(line)
            rules = pipeline._horizontal_table_rules_from_polylines(geometry)
            if specification:
                geometry, retained = pipeline._adjust_specification_underlined_heading_layout(geometry, retained, rules, logs)
                rules = pipeline._horizontal_table_rules_from_polylines(geometry)
            glyphs, accepted, missing = pipeline._make_lff_opengost_text_strokes(
                retained, page_w, page_h, logs.append,
                use_stamp_overrides=mode == 'computer_graphics' and not two,
                center_a3_top_left_title=False,
                normalize_dimension_text=mode == 'computer_graphics' and not specification,
                table_rules=rules)
            if missing or (retained and not accepted):
                raise ValueError(f'{tag}/{name}: missing single-line glyphs {sorted(missing)}')
            combined = [*geometry, *glyphs]
            ww, wh = settings.work_width * (2 if two else 1), settings.work_height
            scale = min(ww / (right - left), wh / (bottom - top))
            mx, my = (ww - (right - left) * scale) / 2, (wh - (bottom - top) * scale) / 2
            if two and table is not None:
                logical = move_a3_stamp(combined, table, frame, scale, mx, my, ww, wh)
            else:
                logical = [[((x - left) * scale + mx, (y - top) * scale + my) for x, y in poly] for poly in combined]
            assembled, records = [], []
            for slot in range(2 if two else 1):
                chunk = clip_polylines_to_rect(logical, slot * settings.work_width, (slot + 1) * settings.work_width,
                                               0, wh, continuity_eps_mm=.0001)
                if slot == 0:
                    mapped = [[(x, settings.work_min_y + y) for x, y in poly] for poly in chunk]
                else:
                    mapped = [[(ww - x, settings.work_min_y + wh - y) for x, y in poly] for poly in chunk]
                dx = settings.a3_pass_01_x_offset_mm if two and slot == 0 else settings.a3_pass_02_x_offset_mm if two else 0.
                dy = settings.a3_pass_01_y_offset_mm if two and slot == 0 else settings.a3_pass_02_y_offset_mm if two else 0.
                mapped = unique_strokes([[(x + dx, y + dy) for x, y in poly] for poly in mapped], precision=3)
                ordered = pipeline.stitch_gcode_polylines.nearest_order(mapped)
                nc = pack / (f'plotter_pass_{slot + 1:02d}.nc' if two else 'plotter.nc')
                pipeline.stitch_gcode_polylines.write_gcode(
                    nc, ordered, feed_travel=settings.feed_travel, feed_draw=settings.feed_draw,
                    z_up=settings.z_up, z_down=settings.z_down, z_feed=settings.z_feed,
                    home_x=settings.home_x, home_y=settings.home_y, home_feed=settings.home_feed,
                    legacy_z_reference=settings.legacy_z_reference)
                payload = (f'; source={source.name}; page={index + 1}; task={name}; mode={mode}\n'
                           f'; machine=a4_desktop; scale={scale:.8f}; part={slot + 1}; paper_rotation_deg={180 if slot else 0}\n'
                           f'; calibration_dx_mm={dx:.3f}; calibration_dy_mm={dy:.3f}\n'
                           '; Only prepared drawing; no automatic drawing.\n' + nc.read_text(encoding='utf-8')
                           + pipeline._safe_trailer_text(settings))
                nc.write_text(payload, encoding='utf-8', newline='\n')
                strokes = actual_strokes(payload, settings)
                for poly in strokes:
                    points = [(x - dx, y - dy - settings.work_min_y) for x, y in poly]
                    assembled.append(points if slot == 0 else [(ww - x, wh - y) for x, y in points])
                record = {'number': len(queue) + 1, 'document': tag, 'source_pdf': str(source),
                          'source_page': index + 1, 'task': name, 'part': slot + 1,
                          'parts': 2 if two else 1, 'format': 'A3' if two else 'A4',
                          'file': str(nc), 'sha256': hashlib.sha256(payload.encode('utf-8')).hexdigest(),
                          'paper_rotation_deg': 180 if slot else 0, 'offset_mm': [dx, dy]}
                queue.append(record); records.append(record)
            preview = render_from_nc(assembled, two, pack / 'plot_preview.pdf', settings)
            aggregate.insert_pdf(preview)
            (collection / (name + '.pdf')).write_bytes(preview.tobytes(garbage=4, deflate=True))
            if mode == 'computer_graphics':
                pw, ph = (420., 297.) if two else (210., 297.)
                rect = fitz.Rect(max(0, pw - 218) * MM, (ph - 78) * MM, pw * MM, ph * MM)
                preview[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=rect, alpha=False).save(pack / 'stamp_detail.png')
            preview.close()
            meta = {'source': str(source), 'source_page': index + 1, 'task': name, 'mode': mode,
                    'source_size_mm': [w, h], 'scale': scale, 'frame_mm': frame,
                    'specification': specification, 'single_line_text_count': len(accepted),
                    'missing_characters': sorted(missing), 'settings': asdict(settings), 'passes': records,
                    'preview_source': 'literal_final_gcode', 'condition_images': condition_images,
                    'hardware_accessed': False}
            (pack / 'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            (pack / 'preparation.log').write_text('\n'.join(logs), encoding='utf-8')
            thumbnails.append((name, pack / 'plot_preview.png')); pages_meta.append(meta)
            print(json.dumps({'prepared': tag + '/' + name, 'format': 'A3' if two else 'A4',
                              'passes': 2 if two else 1, 'single_line_text': len(accepted), 'scale': round(scale, 6)}), flush=True)
    destination = output / source.name
    destination.write_bytes(aggregate.tobytes(garbage=4, deflate=True)); aggregate.close()
    cellw, cellh, columns = 450, 570, min(3, len(thumbnails))
    contact = Image.new('RGB', (columns * cellw, math.ceil(len(thumbnails) / columns) * cellh), 'white')
    draw = ImageDraw.Draw(contact)
    for i, (name, image_path) in enumerate(thumbnails):
        with Image.open(image_path) as image:
            thumb = ImageOps.contain(image.convert('RGB'), (cellw - 16, cellh - 36))
            x, y = (i % columns) * cellw, (i // columns) * cellh
            draw.text((x + 8, y + 8), name, fill='black')
            contact.paste(thumb, (x + (cellw - thumb.width) // 2, y + 30))
    contact.save(output / (tag + '_contact.png'))
    return destination, pages_meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lr2', type=Path, required=True)
    parser.add_argument('--lr4', type=Path, required=True)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    scratch = ROOT / 'tmp' / 'pdfs' / 'pogudin_build'; scratch.mkdir(parents=True, exist_ok=True)
    backend.apply_quality_profile('high', curve_segment_mm=.3, arc_segment_mm=.5,
                                  collinear_eps=.001, rdp_simplify_eps_mm=.005, disable_arcs=True)
    backend.DIRECT_PDF_VECTOR_SOURCE_ACTIVE = False
    backend.IMAGE_CONTOUR_MODE = 'off'
    names4 = ['01_Specification', '02_Klapan_SB', '03_Korpus', '04_Kryshka', '05_Flanets',
              '06_Makhovichok', '07_Shpindel', '08_Klapan', '09_Probka']
    documents = [(args.lr2, 'LR2', ['01_Eskiz'], 'computer_graphics'),
                 (args.lr4, 'LR4', names4, 'computer_graphics'),
                 (args.geometry, 'DG', None, 'descriptive_geometry')]
    queue, summaries = [], []
    for source, tag, names, mode in documents:
        pdf, pages = prepare_document(source, tag, names, mode, args.output, scratch, queue)
        summaries.append({'document': tag, 'pdf': str(pdf), 'pages': len(pages)})
    (args.output / 'queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    labels = {'LR2': 'ЛР-2', 'LR4': 'ЛР-4', 'DG': 'Начертательная геометрия'}
    lines = [f"{r['number']}. {labels[r['document']]} / {r['task']} / "
             f"{'часть ' + str(r['part']) + ' из 2' if r['parts'] == 2 else 'целый лист A4'}\n   {r['file']}" for r in queue]
    (args.output / 'DRAW_QUEUE.txt').write_text('\n'.join(lines), encoding='utf-8-sig')
    with (args.output / 'DRAW_QUEUE.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['number', 'document', 'source_page', 'task', 'part', 'parts', 'format', 'file'])
        writer.writeheader(); writer.writerows({k: r[k] for k in writer.fieldnames} for r in queue)
    print(json.dumps({'complete': True, 'documents': summaries, 'drawings': sum(r['pages'] for r in summaries),
                      'NC_files': len(queue), 'output': str(args.output), 'hardware_accessed': False}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
