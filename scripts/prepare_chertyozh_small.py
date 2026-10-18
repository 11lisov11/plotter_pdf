from pathlib import Path
import math
import re

import fitz

from scripts import prepare_plotter_ready_new_algorithm as pipeline
from src.plotter_backend.geometry.clipping import clip_polylines_to_rect
from src.plotter_backend.geometry.path_processing import remove_rectangular_border


ROOT = Path(r'C:\plotter_pdf')
BIG = ROOT / '_plotter_jobs/Chertyozh_A3_big/Chertyozh_pack'
JOB = ROOT / '_plotter_jobs/Chertyozh_A3_small'
PACK = JOB / 'Chertyozh_pack'
PACK.mkdir(parents=True, exist_ok=True)
settings = pipeline.settings_for_machine_profile('a4_desktop')


def draw_paths(path, z_up, z_down):
    x = y = 0.0
    z = z_up
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
        down = abs(z - z_down) < abs(z - z_up)
        if moving and down:
            if motion in (2, 3):
                raise ValueError('This approved source must contain G1 geometry, not unresolved arcs')
            if motion == 1:
                if not current:
                    current = [(x, y)]
                current.append((nx, ny))
            else:
                finish()
        elif moving:
            finish()
        if abs(nz - z_up) < abs(nz - z_down):
            finish()
        x, y, z = nx, ny, nz
    finish()
    return result


source = draw_paths(BIG / 'plotter.nc', 5.0, -5.0)
points = [point for poly in source for point in poly]
if not points:
    raise ValueError('The approved drawing has no pen-down geometry')
min_x = min(p[0] for p in points)
max_x = max(p[0] for p in points)
min_y = min(p[1] for p in points)
max_y = max(p[1] for p in points)
width = settings.work_width * 2
height = settings.work_height
scale = min(width / (max_y - min_y), height / (max_x - min_x))
margin_x = (width - (max_y - min_y) * scale) / 2
margin_y = (height - (max_x - min_x) * scale) / 2
# The approved portrait machine coordinates become the landscape reading view:
# drawing X = machine Y; drawing top-to-bottom Y = machine X.
logical = [[((y - min_y) * scale + margin_x, (x - min_x) * scale + margin_y)
            for x, y in poly] for poly in source]
# This job keeps the lower-right specification/stamp but no sheet border.
# Detect its repeated full-width rows, including the edges shared with the frame.
frame = (margin_x, width - margin_x, margin_y, height - margin_y)
table_rows = []
auxiliary_boxes = []
for poly in logical:
    for a, b in zip(poly, poly[1:]):
        if abs(a[1] - b[1]) > 0.002:
            continue
        lo, hi = sorted((a[0], b[0]))
        y = (a[1] + b[1]) / 2
        if abs(hi - frame[1]) <= 0.002 and lo > width * 0.5 and hi - lo >= width * 0.05:
            table_rows.append((lo, hi, y))
        if (abs(lo - frame[0]) <= 0.002 and 1.0 < hi - lo < width * 0.2 and
                frame[2] + 0.5 < y < frame[2] + height * 0.06):
            auxiliary_boxes.append((frame[0], hi, frame[2], y))
if len({round(row[2], 2) for row in table_rows}) < 3:
    raise ValueError('Cannot safely identify the specification table; keeping previous outputs')
table = (min(row[0] for row in table_rows), frame[1], min(row[2] for row in table_rows), frame[3])
logical = remove_rectangular_border(logical, frame, preserve_regions=[table])
for box in auxiliary_boxes:
    logical = remove_rectangular_border(logical, box)
print(f'Frame removed; specification and stamp protected: {table}; auxiliary boxes removed={len(auxiliary_boxes)}')
assembled = []
for index in (1, 2):
    name = f'pass_{index:02d}'
    left = (index - 1) * settings.work_width
    right = index * settings.work_width
    clipped = clip_polylines_to_rect(logical, left, right, 0.0, height,
                                    continuity_eps_mm=0.0001)
    if index == 1:
        mapped = [[(x, settings.work_min_y + y) for x, y in poly] for poly in clipped]
    else:
        mapped = [[(width - x, settings.work_min_y + height - y) for x, y in poly]
                  for poly in clipped]
    mapped, offset = pipeline._apply_a3_pass_plotter_offset(mapped, name, settings, [])
    mapped = pipeline.stitch_gcode_polylines.nearest_order(mapped)
    # Use the established small-machine writer without changing pen calibration.
    target = PACK / f'plotter_{name}.nc'
    pipeline.stitch_gcode_polylines.write_gcode(
        target, mapped, feed_travel=settings.feed_travel, feed_draw=settings.feed_draw,
        z_down=settings.z_down, z_up=settings.z_up, z_feed=settings.z_feed,
        home_x=settings.home_x, home_y=settings.home_y, home_feed=settings.home_feed,
        legacy_z_reference=settings.legacy_z_reference,
    )
    header = (
        '; approved vector geometry -> common A3 scale -> small plotter two-pass layout\n'
        '; sheet_frame=removed; specification_table=retained\n'
        f'; machine_profile={settings.machine_profile}; item={name}; scale={scale:.8f}\n'
        f'; source_geometry=_plotter_jobs/Chertyozh_A3_big/Chertyozh_pack/plotter.nc\n'
        f'; calibration_offset_x_mm={offset["x_mm"]:.3f}; calibration_offset_y_mm={offset["y_mm"]:.3f}\n'
        f'; feed_draw={settings.feed_draw:.1f}; feed_travel={settings.feed_travel:.1f}\n'
        f'; z_up={settings.z_up:.3f}; z_down={settings.z_down:.3f}\n'
    )
    target.write_text(header + target.read_text(encoding='utf-8') +
                      pipeline._safe_trailer_text(settings), encoding='utf-8', newline='\n')
    actual = draw_paths(target, settings.z_up, settings.z_down)
    for poly in actual:
        restored = []
        for x, y in poly:
            # Reassemble in the calibrated paper reference, accounting for
            # the existing machine correction rather than hiding/changing it.
            x -= offset['x_mm']
            y -= offset['y_mm']
            local_y = y - settings.work_min_y
            restored.append((x, local_y) if index == 1 else (width - x, height - local_y))
        assembled.append(restored)
    bounds = pipeline._bounds(actual)
    print(f'{name}: paths={len(actual)}, bounds={bounds}, calibration={offset}, output={target}')

mm = 72 / 25.4
doc = fitz.open()
page = doc.new_page(width=420 * mm, height=297 * mm)
shape = page.new_shape()
paper_x = (420 - width) / 2
paper_y = (297 - height) / 2
for poly in assembled:
    shape.draw_polyline([fitz.Point((paper_x + x) * mm, (paper_y + y) * mm) for x, y in poly])
shape.finish(color=(0, 0, 0), width=0.2 * mm, lineCap=1, lineJoin=1)
shape.commit()
# A preview-only guide for the two passes, never a command in either NC file.
for y in range(0, int(height), 13):
    page.draw_line(fitz.Point((paper_x + settings.work_width) * mm, (paper_y + y) * mm),
                   fitz.Point((paper_x + settings.work_width) * mm, (paper_y + min(y + 8, height)) * mm),
                   color=(0.6, 0.6, 0.6), width=0.15 * mm)
doc.save(PACK / 'plot_preview.pdf', deflate=True)
doc.save(JOB / 'Chertyozh.pdf', deflate=True)
page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False).save(PACK / 'plot_preview.png')
doc.close()
print(f'A3 small: common scale={scale:.8f}; drawing field={width:.1f}x{height:.1f} mm; pen-up={settings.z_up}; pen-down={settings.z_down}')
print(f'Preview reconstructed from both final NC files: {PACK / "plot_preview.pdf"}')
