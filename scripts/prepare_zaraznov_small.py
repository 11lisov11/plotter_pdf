from __future__ import annotations

from pathlib import Path
import math
import re
import sys

import fitz
from PIL import Image, ImageDraw, ImageOps

from scripts import prepare_plotter_ready_new_algorithm as pipeline
from src import plotter_pdf_drawer as backend
from src.plotter_backend.geometry.clipping import clip_polylines_to_rect
from src.plotter_backend.geometry.path_processing import trim_to_inner_drawing_frame, remove_rectangular_border
from src.plotter_backend.geometry.simplify import rdp_simplify_polyline


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(r'C:\plotter_pdf')
INPUT = Path(r'C:\Users\USER\Downloads\Telegram Desktop')
OUTPUT = ROOT / '_plotter_jobs/Zaraznov_small'
TEMP = ROOT / 'tmp/pdfs/zaraznov'
OUTPUT.mkdir(parents=True, exist_ok=True)
TEMP.mkdir(parents=True, exist_ok=True)
SETTINGS = pipeline.settings_for_machine_profile('a4_desktop')
backend.apply_quality_profile('high', curve_segment_mm=0.3, arc_segment_mm=0.5,
                              collinear_eps=0.001, rdp_simplify_eps_mm=0.005,
                              disable_arcs=True)
backend.DIRECT_PDF_VECTOR_SOURCE_ACTIVE = False
backend.IMAGE_CONTOUR_MODE = 'off'


def actual_strokes(path: Path):
    x = y = 0.0
    z = SETTINGS.z_up
    absolute = True
    motion = None
    result, current = [], []

    def finish():
        nonlocal current
        if len(current) >= 2:
            result.append(current)
        current = []

    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = re.sub(r'\([^)]*\)|;.*$', '', raw).upper()
        pairs = re.findall(r'([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))', line)
        codes = [float(v) for k, v in pairs if k == 'G']
        words = {k: float(v) for k, v in pairs if k != 'G'}
        if 90.0 in codes:
            absolute = True
        if 91.0 in codes:
            absolute = False
        if 92.0 in codes:
            finish()
            x, y, z = words.get('X', x), words.get('Y', y), words.get('Z', z)
            continue
        for code in codes:
            if code in (0, 1, 2, 3):
                motion = int(code)
        nx = words.get('X', x) if absolute else x + words.get('X', 0.0)
        ny = words.get('Y', y) if absolute else y + words.get('Y', 0.0)
        nz = words.get('Z', z) if absolute else z + words.get('Z', 0.0)
        moving = math.hypot(nx - x, ny - y) > 1e-9
        down = abs(z - SETTINGS.z_down) < abs(z - SETTINGS.z_up)
        if moving and down and motion in (2, 3):
            raise ValueError('Unresolved arc in literal G1 preview')
        if moving and down and motion == 1:
            if not current:
                current = [(x, y)]
            current.append((nx, ny))
        elif moving:
            finish()
        if abs(nz - SETTINGS.z_up) < abs(nz - SETTINGS.z_down):
            finish()
        x, y, z = nx, ny, nz
    finish()
    return result


def frame_and_tables(polylines, specification, logs, *, keep_frame=False):
    clipped = trim_to_inner_drawing_frame(polylines, logger=logs.append)
    left, right, bottom, top = backend.bounds_polylines(clipped)
    frame = (left, right, bottom, top)
    if specification:
        return clipped, frame, [], None
    width, height = right - left, top - bottom
    rows, auxiliary = [], []
    vertical = []
    for poly in clipped:
        for a, b in zip(poly, poly[1:]):
            if abs(a[0] - b[0]) <= 0.005:
                vertical.append(((a[0] + b[0]) / 2, min(a[1], b[1]), max(a[1], b[1])))
            if abs(a[1] - b[1]) > 0.005:
                continue
            lo, hi = sorted((a[0], b[0]))
            y = (a[1] + b[1]) / 2
            if (abs(hi - right) <= 0.005 and hi - lo >= width * 0.05 and
                    bottom + height * 0.60 < y < top - 0.1):
                rows.append((lo, y))
            if (abs(lo - left) <= 0.005 and 1 < hi - lo < width * 0.45 and
                    bottom + 0.5 < y < bottom + height * 0.08):
                auxiliary.append((left, hi, bottom, y))
    if len({round(row[1], 2) for row in rows}) < 3:
        raise ValueError('Cannot safely identify the title table')
    table = (min(row[0] for row in rows), right, min(row[1] for row in rows), top)
    result = remove_rectangular_border(clipped, frame, preserve_regions=[] if keep_frame else [table])
    removed_boxes = []
    for box in auxiliary:
        if not any(abs(x - box[1]) <= 0.005 and abs(lo - box[2]) <= 0.005 and
                   abs(hi - box[3]) <= 0.005 for x, lo, hi in vertical):
            continue
        removed_boxes.append(box)
        result = [poly for poly in result if not all(
            box[0] - 0.005 <= x <= box[1] + 0.005 and
            box[2] - 0.005 <= y <= box[3] + 0.005 for x, y in poly)]
        result = remove_rectangular_border(result, box)
    if keep_frame:
        # Restore the complete inner drawing frame after removing auxiliary boxes,
        # including the sides shared with the stamp and top-left service box.
        result.append([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)])
    logs.append(f'Frame {"retained" if keep_frame else "removed"}; title table retained at {table}')
    return result, frame, removed_boxes, table


def move_a3_stamp_to_work_limits(paths, table, frame, scale, mx, my, work_w, work_h):
    """Move only the stamp; preserve every drawing segment outside its cells."""
    x0, x1, y0, y1 = table
    frame_left, _, frame_top, _ = frame
    dx = work_w - ((x1 - frame_left) * scale + mx)
    dy = work_h - ((y1 - frame_top) * scale + my)
    output = []
    for poly in paths:
        current, current_stamp = [], None
        for a, b in zip(poly, poly[1:]):
            vx, vy = b[0] - a[0], b[1] - a[1]
            cuts = [0.0, 1.0]
            for origin, delta, edges in ((a[0], vx, (x0, x1)), (a[1], vy, (y0, y1))):
                if abs(delta) > 1e-12:
                    cuts.extend(t for edge in edges if 0 < (t := (edge - origin) / delta) < 1)
            cuts = sorted(set(cuts))
            for start, end in zip(cuts, cuts[1:]):
                p = (a[0] + vx * start, a[1] + vy * start)
                q = (a[0] + vx * end, a[1] + vy * end)
                cx, cy = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
                stamp = x0 - 1e-7 <= cx <= x1 + 1e-7 and y0 - 1e-7 <= cy <= y1 + 1e-7
                outer_bottom = abs(p[1] - y1) < 0.005 and abs(q[1] - y1) < 0.005
                outer_right = abs(p[0] - x1) < 0.005 and abs(q[0] - x1) < 0.005
                if stamp and (outer_bottom or outer_right):
                    if len(current) >= 2:
                        output.append(current)
                    current, current_stamp = [], None
                    continue
                shift_x, shift_y = (dx, dy) if stamp else (0.0, 0.0)
                mapped = [((x - frame_left) * scale + mx + shift_x,
                           (y - frame_top) * scale + my + shift_y) for x, y in (p, q)]
                if current_stamp != stamp or (current and math.dist(current[-1], mapped[0]) > 1e-7):
                    if len(current) >= 2:
                        output.append(current)
                    current = []
                if not current:
                    current = [mapped[0]]
                current.append(mapped[1])
                current_stamp = stamp
        if len(current) >= 2:
            output.append(current)
    return output


def write_pass(path, paths, offset, source, page_number, scale, two_pass, slot):
    paths = [rdp_simplify_polyline(poly, 0.005) for poly in paths if len(poly) >= 2]
    paths = pipeline.stitch_gcode_polylines.nearest_order(paths)
    pipeline.stitch_gcode_polylines.write_gcode(
        path, paths, feed_travel=SETTINGS.feed_travel, feed_draw=SETTINGS.feed_draw,
        z_up=SETTINGS.z_up, z_down=SETTINGS.z_down, z_feed=SETTINGS.z_feed,
        home_x=SETTINGS.home_x, home_y=SETTINGS.home_y, home_feed=SETTINGS.home_feed,
        legacy_z_reference=SETTINGS.legacy_z_reference,
    )
    paper_w, paper_h = (420.0, 297.0) if two_pass else (210.0, 297.0)
    work_w = SETTINGS.work_width * (2 if two_pass else 1)
    origin_x = (paper_w - work_w) / 2
    origin_y = (paper_h - SETTINGS.work_height) / 2
    if slot == 0:
        home_from_left = origin_x - offset[0]
        home_from_bottom = paper_h - (origin_y - SETTINGS.work_min_y - offset[1])
    else:
        home_from_left = paper_w - (origin_x + work_w + offset[0])
        home_from_bottom = SETTINGS.work_min_y + SETTINGS.work_height + origin_y + offset[1]
    header = (
        '; PDF geometry without source glyph outlines + OpenGOST LFF single-line text -> small plotter\n'
        f'; source={source.name}; source_page={page_number}; scale={scale:.8f}\n'
        f'; machine_profile=a4_desktop; feed_draw={SETTINGS.feed_draw:.1f}; feed_travel={SETTINGS.feed_travel:.1f}\n'
        f'; z_up={SETTINGS.z_up:.3f}; z_down={SETTINGS.z_down:.3f}; calibration_dy_mm={offset[1]:.3f}\n'
        f'; paper_mm={paper_w:.1f}x{paper_h:.1f}; placement=centered_work_area; a3_stamp_at_work_limits={int(two_pass)}\n'
        f'; paper_rotation_deg={180 if slot else 0}; place_home_from_current_paper_left_mm={home_from_left:.3f}; place_home_from_current_paper_bottom_mm={home_from_bottom:.3f}\n'
        '; only the requested drawing and its tables; no outer sheet furniture\n'
    )
    path.write_text(header + path.read_text(encoding='utf-8') + pipeline._safe_trailer_text(SETTINGS),
                    encoding='utf-8', newline='\n')
    return actual_strokes(path)


def render(paths, two_pass, target):
    mm = 72 / 25.4
    paper_w, paper_h = (420, 297) if two_pass else (210, 297)
    work_w = SETTINGS.work_width * (2 if two_pass else 1)
    work_h = SETTINGS.work_height
    mx, my = (paper_w - work_w) / 2, (paper_h - work_h) / 2
    doc = fitz.open()
    page = doc.new_page(width=paper_w * mm, height=paper_h * mm)
    shape = page.new_shape()
    for poly in paths:
        shape.draw_polyline([fitz.Point((mx + x) * mm, (my + y) * mm) for x, y in poly])
    shape.finish(color=(0, 0, 0), width=0.2 * mm, lineCap=1, lineJoin=1)
    shape.commit()
    if two_pass:
        for y in range(0, int(work_h), 13):
            page.draw_line(fitz.Point((mx + SETTINGS.work_width) * mm, (my + y) * mm),
                           fitz.Point((mx + SETTINGS.work_width) * mm, (my + min(y + 8, work_h)) * mm),
                           color=(0.65, 0.65, 0.65), width=0.15 * mm)
    doc.save(target, deflate=True)
    page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False).save(target.with_suffix('.png'))
    return doc


names = ['01_Spetsifikatsiya', '02_Forsunka_SB', '03_Korpus', '04_Soplo', '05_Troynik',
         '06_Konus', '07_Nippel_05', '08_Nippel_06', '09_Gayka_nakidnaya',
         '10_Makhovik', '11_Gayka_09', '12_Gayka_10']
inputs = [('LR2', INPUT / 'ЛР-2.Эскиз .Заразнов А.В..pdf'),
          ('LR4', INPUT / 'ЛР-4. Заразнов А.В..pdf')]
thumbnails = []
total_passes = 0
for document_name, source in inputs:
    aggregate = fitz.open()
    with fitz.open(source) as original:
        for index, source_page in enumerate(original):
            task = 'LR2_Eskiz' if document_name == 'LR2' else 'LR4_' + names[index]
            pack = OUTPUT / (task + '_pack')
            pack.mkdir(parents=True, exist_ok=True)
            original_page = fitz.open()
            original_page.insert_pdf(original, from_page=index, to_page=index)
            original_page.save(pack / 'source.pdf', deflate=True)
            original_page.close()
            w, h = source_page.rect.width * 25.4 / 72, source_page.rect.height * 25.4 / 72
            two_pass = max(w, h) > 310
            text = source_page.get_text()
            specification = 'Обозначение' in text and 'Наименование' in text
            logs = []
            single_page_source = pack / 'source.pdf'
            polylines, page_w, page_h, _ = pipeline._geometry_polylines_from_pdf(
                single_page_source, TEMP, logs)
            text_lines, _, _ = pipeline._text_lines_for_source(single_page_source)
            polylines = pipeline._remove_existing_text_geometry(polylines, text_lines, logs.append)
            geometry, frame, excluded_boxes, stamp_table = frame_and_tables(
                polylines, specification, logs, keep_frame=not two_pass)
            geometry = backend.deduplicate_segments(geometry, eps=0.001, logger=None)
            geometry = backend.deduplicate_collinear_overlaps(geometry, logger=None)
            left, right, top, bottom = frame
            retained_text = []
            for line in text_lines:
                box = pipeline._line_bbox_mm(line)
                if box is None:
                    continue
                x0, y0, x1, y1 = box
                if not (left <= (x0 + x1) / 2 <= right and top <= (y0 + y1) / 2 <= bottom):
                    continue
                if any(a - 0.005 <= x0 and x1 <= b + 0.005 and
                       c - 0.005 <= y0 and y1 <= d + 0.005
                       for a, b, c, d in excluded_boxes):
                    continue
                retained_text.append(line)
            table_rules = pipeline._horizontal_table_rules_from_polylines(geometry)
            if specification:
                geometry, retained_text = pipeline._adjust_specification_underlined_heading_layout(
                    geometry, retained_text, table_rules, logs)
                table_rules = pipeline._horizontal_table_rules_from_polylines(geometry)
            text_polys, accepted_text, missing_chars = pipeline._make_lff_opengost_text_strokes(
                retained_text, page_w, page_h, logs.append,
                use_stamp_overrides=not two_pass,
                center_a3_top_left_title=False,
                normalize_dimension_text=not specification,
                table_rules=table_rules)
            if missing_chars or (retained_text and not accepted_text):
                raise ValueError(f'{task}: cannot render single-line text: {sorted(missing_chars)}')
            # Deduplicate structural lines before overlay, never simplify LFF glyphs as contours.
            geometry = [*geometry, *text_polys]
            left, right, top, bottom = frame
            fw, fh = right - left, bottom - top
            work_w = SETTINGS.work_width * (2 if two_pass else 1)
            work_h = SETTINGS.work_height
            scale = min(work_w / fw, work_h / fh)
            # Restore the original centered placement for the drawing and all A4 sheets.
            mx, my = (work_w - fw * scale) / 2, (work_h - fh * scale) / 2
            if two_pass and stamp_table is not None:
                logical = move_a3_stamp_to_work_limits(
                    geometry, stamp_table, frame, scale, mx, my, work_w, work_h)
            else:
                logical = [[((x - left) * scale + mx, (y - top) * scale + my) for x, y in poly]
                           for poly in geometry]
            assembled = []
            for slot in range(2 if two_pass else 1):
                chunk = clip_polylines_to_rect(logical, slot * SETTINGS.work_width,
                                               (slot + 1) * SETTINGS.work_width, 0, work_h,
                                               continuity_eps_mm=0.0001)
                if slot == 0:
                    mapped = [[(x, SETTINGS.work_min_y + y) for x, y in poly] for poly in chunk]
                else:
                    mapped = [[(work_w - x, SETTINGS.work_min_y + work_h - y) for x, y in poly]
                              for poly in chunk]
                dx = SETTINGS.a3_pass_01_x_offset_mm if two_pass and slot == 0 else SETTINGS.a3_pass_02_x_offset_mm if two_pass else 0
                dy = SETTINGS.a3_pass_01_y_offset_mm if two_pass and slot == 0 else SETTINGS.a3_pass_02_y_offset_mm if two_pass else 0
                mapped = [[(x + dx, y + dy) for x, y in poly] for poly in mapped]
                filename = f'plotter_pass_{slot + 1:02d}.nc' if two_pass else 'plotter.nc'
                strokes = write_pass(pack / filename, mapped, (dx, dy), source, index + 1, scale, two_pass, slot)
                for poly in strokes:
                    restored = []
                    for x, y in poly:
                        x, y = x - dx, y - dy - SETTINGS.work_min_y
                        restored.append((x, y) if slot == 0 else (work_w - x, work_h - y))
                    assembled.append(restored)
                total_passes += 1
            preview = render(assembled, two_pass, pack / 'plot_preview.pdf')
            aggregate.insert_pdf(preview)
            preview.close()
            thumbnails.append((task, pack / 'plot_preview.png'))
            print(f'{task}: source={w:.2f}x{h:.2f} mm; passes={2 if two_pass else 1}; scale={scale:.6f}; source_paths={len(polylines)}; draw_paths={len(assembled)}; spec_grid={specification}; single_line_text={len(accepted_text)}', flush=True)
            for line in logs:
                print(' ', line, flush=True)
    # Do not unlink an existing PDF: viewers may deny deletion while still
    # allowing its contents to be updated in place.
    (OUTPUT / source.name).write_bytes(aggregate.tobytes(deflate=True))
    aggregate.close()

cell_w, cell_h = 400, 440
columns = 3
rows = math.ceil(len(thumbnails) / columns)
contact = Image.new('RGB', (columns * cell_w, rows * cell_h), 'white')
draw = ImageDraw.Draw(contact)
for index, (name, path) in enumerate(thumbnails):
    with Image.open(path) as original:
        thumb = ImageOps.contain(original.convert('RGB'), (cell_w - 12, cell_h - 32))
        x, y = (index % columns) * cell_w, (index // columns) * cell_h
        draw.text((x + 6, y + 6), name, fill='black')
        contact.paste(thumb, (x + (cell_w - thumb.width) // 2, y + 28))
contact.save(TEMP / 'prepared_contact.png')
print(f'FINISHED: drawings={len(thumbnails)}; NC files={total_passes}; output={OUTPUT}', flush=True)
