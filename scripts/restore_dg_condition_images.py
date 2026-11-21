"""OFFLINE ONLY: add missing condition miniatures to prepared DG NC files.

Existing vectors, text, source fit, A3 border cleanup and pass offsets are kept.
Only DG files are rewritten; a concurrently drawn CG file is never touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from PIL import Image, ImageDraw, ImageOps

from scripts import prepare_pogudin_small as prep
from src.plotter_backend.geometry.clipping import clip_polylines_to_rect
from src.plotter_backend.geometry.condition_images import extract_condition_miniatures
from src.plotter_backend.geometry.path_processing import remove_rectangular_border


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--remove-borders-only', action='store_true',
                        help='Keep restored miniature strokes, remove only their scanned outer rectangles')
    args = parser.parse_args()
    root = args.root.resolve(); qp = root / 'queue.json'
    queue_bytes = qp.read_bytes(); queue = json.loads(queue_bytes)
    packs = list(dict.fromkeys(Path(r['file']).parent for r in queue if r['document'] == 'DG'))
    backup = ROOT / 'backups' / 'dg_condition_images' / datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_UTC')
    backup.mkdir(parents=True, exist_ok=False); (backup / 'queue.json').write_bytes(queue_bytes)
    updated, thumbnails, comparisons, results = {}, [], [], []
    aggregate = fitz.open()
    for pack in packs:
        mp = pack / 'manifest.json'; original_meta = mp.read_bytes(); meta = json.loads(original_meta)
        if meta.get('condition_images_restored') and not args.remove_borders_only:
            raise ValueError(f'Miniatures already restored: {pack}')
        settings = prep.pipeline.Settings(**meta['settings'])
        two = len(meta['passes']) == 2; ww = settings.work_width * (2 if two else 1); wh = settings.work_height
        source = pack / 'source.pdf'; logs = []
        if args.remove_borders_only:
            extra, records = [], meta.get('condition_images', [])
        else:
            extra, records = extract_condition_miniatures(source, logger=logs.append)
        if not records or (not extra and not args.remove_borders_only):
            raise ValueError(f'No condition miniature recovered: {source}')
        save = backup / pack.name; save.mkdir(); (save / 'manifest.json').write_bytes(original_meta)
        (save / 'plot_preview.pdf').write_bytes((pack / 'plot_preview.pdf').read_bytes())
        logical, headers = [], {}
        for record in meta['passes']:
            nc = Path(record['file']); blob = nc.read_bytes()
            if hashlib.sha256(blob).hexdigest() != record['sha256']:
                raise ValueError(f'Prepared NC changed: {nc}')
            (save / nc.name).write_bytes(blob); text = blob.decode('utf-8')
            headers[str(nc)] = '\n'.join(line for line in text.splitlines() if line.startswith(';')) + '\n'
            dx, dy = record['offset_mm']
            for poly in prep.actual_strokes(text, settings):
                points = [(x - dx, y - dy - settings.work_min_y) for x, y in poly]
                logical.append(points if record['part'] == 1 else [(ww - x, wh - y) for x, y in points])
        left, right, top, bottom = meta['frame_mm']; scale = meta['scale']
        mx, my = (ww - (right - left) * scale) / 2, (wh - (bottom - top) * scale) / 2
        if args.remove_borders_only:
            for miniature in records:
                x0, y0, x1, y1 = miniature['bbox_mm']
                box = ((x0 - left) * scale + mx, (x1 - left) * scale + mx,
                       (y0 - top) * scale + my, (y1 - top) * scale + my)
                logical = remove_rectangular_border(logical, box, tolerance_mm=.35 * scale)
                miniature['outer_border_removed'] = True
            logs.append('Removed scanned miniature borders only; native condition-cell lines preserved.')
        else:
            logical.extend([[((x - left) * scale + mx, (y - top) * scale + my) for x, y in poly] for poly in extra])
        assembled = []
        for record in meta['passes']:
            slot = record['part'] - 1; dx, dy = record['offset_mm']
            chunk = clip_polylines_to_rect(logical, slot * settings.work_width,
                                           (slot + 1) * settings.work_width, 0, wh, continuity_eps_mm=.0001)
            if slot == 0:
                mapped = [[(x + dx, settings.work_min_y + y + dy) for x, y in poly] for poly in chunk]
            else:
                mapped = [[(ww - x + dx, settings.work_min_y + wh - y + dy) for x, y in poly] for poly in chunk]
            mapped = prep.unique_strokes(mapped, precision=3); nc = Path(record['file'])
            prep.pipeline.stitch_gcode_polylines.write_gcode(
                nc, prep.pipeline.stitch_gcode_polylines.nearest_order(mapped),
                feed_travel=settings.feed_travel, feed_draw=settings.feed_draw,
                z_up=settings.z_up, z_down=settings.z_down, z_feed=settings.z_feed,
                home_x=settings.home_x, home_y=settings.home_y, home_feed=settings.home_feed,
                legacy_z_reference=settings.legacy_z_reference)
            payload = (headers[str(nc)] + '; Condition miniature restored as centerline pen paths.\n'
                       + nc.read_text(encoding='utf-8') + prep.pipeline._safe_trailer_text(settings))
            nc.write_text(payload, encoding='utf-8', newline='\n')
            record['sha256'] = hashlib.sha256(payload.encode('utf-8')).hexdigest(); updated[str(nc)] = record
            for poly in prep.actual_strokes(payload, settings):
                points = [(x - dx, y - dy - settings.work_min_y) for x, y in poly]
                assembled.append(points if slot == 0 else [(ww - x, wh - y) for x, y in points])
        preview = prep.render_from_nc(assembled, two, pack / 'plot_preview.pdf', settings)
        (root / 'DG' / (meta['task'] + '.pdf')).write_bytes(preview.tobytes(garbage=4, deflate=True))
        aggregate.insert_pdf(preview); preview.close()
        # Compare source pixels with an actual rendered NEW NC-derived PDF.
        first = records[0]; box = first['bbox_mm']; pw, ph = (420., 297.) if two else (210., 297.)
        paper_x, paper_y = (pw - ww) / 2, (ph - wh) / 2
        rendered_rect = fitz.Rect((paper_x + (box[0] - left) * scale + mx - .3) * prep.MM,
                                  (paper_y + (box[1] - top) * scale + my - .3) * prep.MM,
                                  (paper_x + (box[2] - left) * scale + mx + .3) * prep.MM,
                                  (paper_y + (box[3] - top) * scale + my + .3) * prep.MM)
        with fitz.open(pack / 'plot_preview.pdf') as rendered:
            pix = rendered[0].get_pixmap(matrix=fitz.Matrix(4, 4), clip=rendered_rect, alpha=False)
            nc_image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            pix.save(pack / 'condition_from_Gcode.png')
        with fitz.open(source) as original:
            rect = fitz.Rect(*(v * prep.MM for v in box))
            pix = original[0].get_pixmap(matrix=fitz.Matrix(4, 4), clip=rect, alpha=False)
            source_image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        comparisons.append((meta['task'], source_image, nc_image))
        meta['condition_images'] = records; meta['condition_images_restored'] = True
        meta['condition_images_backup'] = str(save)
        mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        with (pack / 'preparation.log').open('a', encoding='utf-8') as stream:
            stream.write('\n' + '\n'.join(logs))
        thumbnails.append((meta['task'], pack / 'plot_preview.png'))
        result = {'task': meta['task'], 'miniatures': len(records), 'added_centerline_paths': len(extra),
                  'source_scale_unchanged': scale, 'passes': len(meta['passes']),
                  'miniature_borders_removed': bool(args.remove_borders_only)}
        results.append(result); print(json.dumps(result), flush=True)
    for row in queue:
        if row['file'] in updated:
            row.update(updated[row['file']])
    qp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    source_name = Path(next(row['source_pdf'] for row in queue if row['document'] == 'DG')).name
    (root / source_name).write_bytes(aggregate.tobytes(garbage=4, deflate=True)); aggregate.close()
    contact = Image.new('RGB', (1350, math.ceil(len(thumbnails) / 3) * 570), 'white'); draw = ImageDraw.Draw(contact)
    for i, (task, image_path) in enumerate(thumbnails):
        with Image.open(image_path) as image:
            thumb = ImageOps.contain(image.convert('RGB'), (434, 534))
            x, y = i % 3 * 450, i // 3 * 570
            draw.text((x + 8, y + 8), task, fill='black'); contact.paste(thumb, (x + (450 - thumb.width) // 2, y + 30))
    contact.save(root / 'DG_contact.png')
    for start in range(0, len(comparisons), 5):
        group = comparisons[start:start + 5]; board = Image.new('RGB', (840, 360 * len(group)), 'white')
        draw = ImageDraw.Draw(board)
        for j, (task, original, traced) in enumerate(group):
            draw.text((15, j * 360 + 8), task + ' / SOURCE', fill='black')
            draw.text((435, j * 360 + 8), task + ' / FROM G-CODE', fill='black')
            for col, image in enumerate((original, traced)):
                thumb = ImageOps.contain(image, (400, 320))
                board.paste(thumb, (col * 420 + (420 - thumb.width) // 2, j * 360 + 32))
        board.save(root / f'DG_miniatures_comparison_{start + 1:02d}_{start + len(group):02d}.png')
    print(json.dumps({'complete': True, 'DG_pages_updated': len(results), 'NC_files_updated': len(updated),
                      'CG_files_touched': False, 'backup': str(backup), 'pdf': str(root / source_name),
                      'hardware_accessed': False}), flush=True)


if __name__ == '__main__':
    main()
