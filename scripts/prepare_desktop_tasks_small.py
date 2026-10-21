from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageOps

import prepare_folder1_packages as prep
import prepare_plotter_ready_new_algorithm as pipeline
from src.plotter_backend.geometry.clipping import clip_polylines_to_rect


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '_plotter_jobs' / 'Desktop_tasks_small'
TEMP = ROOT / 'tmp' / 'pdfs' / 'desktop_tasks'
SETTINGS = pipeline.settings_for_machine_profile('a4_desktop', drawing_mode='descriptive_geometry')


def publish_literal_preview(pack: Path, task: str, two_pass: bool) -> None:
    paths = []
    nc_files = [pack / f'plotter_pass_{n:02d}.nc' for n in (1, 2)] if two_pass else [pack / 'plotter.nc']
    for index, nc in enumerate(nc_files):
        strokes = pipeline.stitch_gcode_polylines.read_draw_polylines(
            nc, z_up=SETTINGS.z_up, z_down=SETTINGS.z_down)
        dx, dy = pipeline._a3_pass_plotter_offset(SETTINGS, f'pass_{index + 1:02d}') if two_pass else (0, 0)
        for poly in strokes:
            mapped = []
            for x, y in poly:
                x, y = x - dx, y - dy - SETTINGS.work_min_y
                mapped.append((x, y) if index == 0 else (2 * SETTINGS.work_width - x, SETTINGS.work_height - y))
            paths.append(mapped)
    paper_w, paper_h = (420.0, 297.0) if two_pass else (210.0, 297.0)
    work_w = SETTINGS.work_width * (2 if two_pass else 1)
    mx, my = (paper_w - work_w) / 2, (paper_h - SETTINGS.work_height) / 2
    mm = 72 / 25.4
    doc = fitz.open()
    page = doc.new_page(width=paper_w * mm, height=paper_h * mm)
    shape = page.new_shape()
    for poly in paths:
        shape.draw_polyline([fitz.Point((x + mx) * mm, (y + my) * mm) for x, y in poly])
    shape.finish(color=(0, 0, 0), width=0.18 * mm, lineCap=1, lineJoin=1)
    shape.commit()
    if two_pass:
        for y in range(0, int(SETTINGS.work_height), 13):
            page.draw_line(fitz.Point((mx + SETTINGS.work_width) * mm, (my + y) * mm),
                           fitz.Point((mx + SETTINGS.work_width) * mm, (my + min(y + 8, SETTINGS.work_height)) * mm),
                           color=(0.65, 0.65, 0.65), width=0.15 * mm)
    data = doc.tobytes(deflate=True)
    (pack / 'plot_preview.pdf').write_bytes(data)
    (OUTPUT / f'{task}.pdf').write_bytes(data)
    # Render the serialized final PDF, not a potentially stale in-memory display list.
    with fitz.open(stream=data, filetype='pdf') as rendered:
        rendered[0].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False).save(pack / 'plot_preview.png')
    doc.close()


def main() -> None:
    global OUTPUT, TEMP
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Prepare descriptive-geometry CAD tasks for the small plotter.')
    parser.add_argument('--source-dir', type=Path, default=Path(r'C:\Users\USER\Desktop'))
    parser.add_argument('--output-dir', type=Path, default=OUTPUT)
    parser.add_argument('--temp-dir', type=Path, default=TEMP)
    parser.add_argument('--tasks', type=int, nargs='+', default=list(range(1, 11)))
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    OUTPUT, TEMP = args.output_dir.resolve(), args.temp_dir.resolve()
    tasks = sorted(set(args.tasks))
    if any(n < 1 for n in tasks):
        parser.error('Task numbers must be positive')
    if ROOT.resolve() not in OUTPUT.parents or ROOT.resolve() not in TEMP.parents:
        parser.error('Output and temporary directories must be inside the project workspace')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    TEMP.mkdir(parents=True, exist_ok=True)
    thumbnails = []
    combined = fitz.open()
    queue_number = 0
    for n in tasks:
        task = '\u0417\u0430\u0434\u0430\u0447\u0430 ' + str(n)
        source = source_dir / f'{task}.frw'
        pdf = TEMP / f'task_{n:02d}_source.pdf'
        prep.backend.frw_to_pdf(source, pdf, print)
        pack = OUTPUT / f'{task}_pack'
        # The package preparer clears its output directory. Restrict that operation
        # to this job's dedicated workspace directory, never the user's Desktop.
        if pack.resolve().parent != OUTPUT.resolve() or ROOT.resolve() not in pack.resolve().parents:
            raise ValueError('Package path outside the intended workspace')
        print(f'PREPARING {task}', flush=True)
        pack.mkdir(parents=True, exist_ok=True)
        with fitz.open(pdf) as doc:
            if len(doc) != 1:
                raise RuntimeError(f'{task}: expected one CAD page, got {len(doc)}')
            two_pass = max(doc[0].rect.width, doc[0].rect.height) * 25.4 / 72 > 310
            footer = ' | '.join(block[4].strip().replace('\n', ' ')
                                for block in doc[0].get_text('blocks')
                                if len(block) > 4 and isinstance(block[4], str)
                                and block[1] > doc[0].rect.height - 20 * 72 / 25.4)
            print(f'SOURCE_FOOTER {task}: {footer}', flush=True)
        report = {'source_pdf': str(pdf), 'kind': 'drawing', 'a3_two_pass': two_pass}
        build = pipeline._build_source(pack, pdf, report, SETTINGS)
        missing = set(build.missing_chars)
        if missing:
            raise RuntimeError(f'{task}: unresolved symbols {sorted(missing)}')
        # Recover embedded condition miniatures using the shared centerline route.
        image_paths, _ = prep._extract_small_condition_image_polylines_from_pdf(
            pdf, page_index=0, logger=print)
        source_paths = [*build.polylines, *image_paths]
        left, top, right, bottom = pipeline._bounds(source_paths)
        work_w = SETTINGS.work_width * (2 if two_pass else 1)
        work_h = SETTINGS.work_height
        scale = min(work_w / (right - left), work_h / (bottom - top))
        mx, my = (work_w - (right - left) * scale) / 2, (work_h - (bottom - top) * scale) / 2
        logical = [[((x - left) * scale + mx, (y - top) * scale + my) for x, y in poly]
                   for poly in source_paths]
        for index in range(2 if two_pass else 1):
            chunk = clip_polylines_to_rect(logical, index * SETTINGS.work_width,
                                          (index + 1) * SETTINGS.work_width, 0, work_h,
                                          continuity_eps_mm=0.0001)
            mapped = [[(x, SETTINGS.work_min_y + y) if index == 0 else
                       (work_w - x, SETTINGS.work_min_y + work_h - y) for x, y in poly]
                      for poly in chunk]
            if two_pass:
                mapped, _ = pipeline._apply_a3_pass_plotter_offset(
                    mapped, f'pass_{index + 1:02d}', SETTINGS, [])
            ordered = pipeline.stitch_gcode_polylines.nearest_order(mapped)
            filename = f'plotter_pass_{index + 1:02d}.nc' if two_pass else 'plotter.nc'
            pipeline._write_new_gcode(pack / filename, ordered, SETTINGS)
            (pack / filename).with_suffix('.gcode').unlink(missing_ok=True)
            queue_number += 1
            print(f'QUEUE {queue_number}: {task}; part={index + 1}; file={filename}', flush=True)
        publish_literal_preview(pack, task, two_pass)
        shutil.copy2(pdf, pack / 'source.pdf')
        shutil.copy2(source, pack / source.name)
        pipeline._safe_remove_pack_child(pack, pack / '_new_algorithm_source')
        with fitz.open(pack / 'plot_preview.pdf') as preview:
            combined.insert_pdf(preview)
        thumbnails.append((n, pack / 'plot_preview.png'))
        print(f'PREPARED {task}: files={2 if two_pass else 1}; missing_glyphs=[]', flush=True)
    (OUTPUT / '\u0412\u0441\u0435 \u0437\u0430\u0434\u0430\u0447\u0438.pdf').write_bytes(combined.tobytes(deflate=True))
    combined.close()
    contact = Image.new('RGB', (1500, ((len(thumbnails) + 2) // 3) * 520), 'white')
    draw = ImageDraw.Draw(contact)
    for index, (number, path) in enumerate(thumbnails):
        with Image.open(path) as image:
            thumb = ImageOps.contain(image.convert('RGB'), (480, 480))
            x, y = (index % 3) * 500, (index // 3) * 520
            draw.text((x + 10, y + 8), f'Task {number}', fill='black')
            contact.paste(thumb, (x + (500 - thumb.width) // 2, y + 30))
    contact.save(TEMP / 'prepared_contact.png')
    print(f'FINISHED {OUTPUT}', flush=True)


if __name__ == '__main__':
    main()
