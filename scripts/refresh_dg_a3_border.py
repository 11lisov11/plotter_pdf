"""Offline, layout-preserving refresh of ONLY the prepared A3 DG pages."""

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
from src.plotter_backend.geometry.path_processing import remove_rectangular_border


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    queue_path = root / 'queue.json'
    queue = json.loads(queue_path.read_text(encoding='utf-8'))
    packs = list(dict.fromkeys(Path(row['file']).parent for row in queue
                              if row['document'] == 'DG' and row['format'] == 'A3'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_UTC')
    backup = ROOT / 'backups' / 'dg_a3_frame' / stamp
    backup.mkdir(parents=True, exist_ok=False)
    (backup / 'queue.json').write_bytes(json.dumps(queue, ensure_ascii=False, indent=2).encode('utf-8'))
    updates = {}
    for pack in packs:
        mp = pack / 'manifest.json'
        original_meta = mp.read_bytes(); meta = json.loads(original_meta)
        settings = prep.pipeline.Settings(**meta['settings'])
        save = backup / pack.name; save.mkdir()
        (save / 'manifest.json').write_bytes(original_meta)
        logical = []
        original_headers = {}
        ww, wh = settings.work_width * 2, settings.work_height
        for record in meta['passes']:
            nc = Path(record['file']); payload = nc.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record['sha256']:
                raise ValueError(f'Prepared file changed: {nc}')
            (save / nc.name).write_bytes(payload)
            text = payload.decode('utf-8')
            original_headers[str(nc)] = '\n'.join(line for line in text.splitlines() if line.startswith(';')) + '\n'
            dx, dy = record['offset_mm']
            for poly in prep.actual_strokes(text, settings):
                points = [(x - dx, y - dy - settings.work_min_y) for x, y in poly]
                logical.append(points if record['part'] == 1 else [(ww - x, wh - y) for x, y in points])
        left, right, top, bottom = meta['frame_mm']; scale = meta['scale']
        mx, my = (ww - (right - left) * scale) / 2, (wh - (bottom - top) * scale) / 2
        fitted_frame = (mx, mx + (right - left) * scale, my, my + (bottom - top) * scale)
        logs = []
        # These prepared pages already had their full frame removed. Use the
        # original manifest bounds rather than requiring that frame to still
        # exist: its remaining bottom/right portions are the stamp edges.
        cleaned = remove_rectangular_border(logical, fitted_frame, tolerance_mm=.005)
        logs.append('A3 DG: remaining bottom/right stamp frame edges removed; internal table lines, text and original fit retained.')
        assembled = []
        for record in meta['passes']:
            slot = record['part'] - 1; dx, dy = record['offset_mm']
            chunk = clip_polylines_to_rect(cleaned, slot * settings.work_width,
                                           (slot + 1) * settings.work_width, 0, wh, continuity_eps_mm=.0001)
            if slot == 0:
                mapped = [[(x + dx, settings.work_min_y + y + dy) for x, y in poly] for poly in chunk]
            else:
                mapped = [[(ww - x + dx, settings.work_min_y + wh - y + dy) for x, y in poly] for poly in chunk]
            mapped = prep.unique_strokes(mapped, precision=3)
            nc = Path(record['file'])
            prep.pipeline.stitch_gcode_polylines.write_gcode(
                nc, prep.pipeline.stitch_gcode_polylines.nearest_order(mapped),
                feed_travel=settings.feed_travel, feed_draw=settings.feed_draw,
                z_up=settings.z_up, z_down=settings.z_down, z_feed=settings.z_feed,
                home_x=settings.home_x, home_y=settings.home_y, home_feed=settings.home_feed,
                legacy_z_reference=settings.legacy_z_reference)
            payload = (original_headers[str(nc)] + '; A3 DG: sheet border and bottom/right stamp edges removed; original fit retained.\n'
                       + nc.read_text(encoding='utf-8') + prep.pipeline._safe_trailer_text(settings))
            nc.write_text(payload, encoding='utf-8', newline='\n')
            record['sha256'] = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            updates[str(nc)] = record
            for poly in prep.actual_strokes(payload, settings):
                points = [(x - dx, y - dy - settings.work_min_y) for x, y in poly]
                assembled.append(points if slot == 0 else [(ww - x, wh - y) for x, y in points])
        preview = prep.render_from_nc(assembled, True, pack / 'plot_preview.pdf', settings)
        (root / 'DG' / (meta['task'] + '.pdf')).write_bytes(preview.tobytes(garbage=4, deflate=True))
        preview.close()
        meta['a3_outer_frame_removed'] = True
        meta['a3_stamp_bottom_right_edges_removed'] = True
        meta['a3_frame_rule_log'] = logs
        meta['a3_frame_backup'] = str(save)
        mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'updated': meta['task'], 'scale_unchanged': scale, 'log': logs,
                          'passes': len(meta['passes']), 'hardware_accessed': False}), flush=True)
    for record in queue:
        if record['file'] in updates:
            record.update(updates[record['file']])
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    aggregate = fitz.open(); thumbnails = []
    for number in range(1, 11):
        task = f'Task_{number:02d}'; pack = root / 'DG' / (task + '_pack')
        with fitz.open(pack / 'plot_preview.pdf') as doc:
            aggregate.insert_pdf(doc)
        thumbnails.append((task, pack / 'plot_preview.png'))
    dg_source = next(row['source_pdf'] for row in queue if row['document'] == 'DG')
    (root / Path(dg_source).name).write_bytes(aggregate.tobytes(garbage=4, deflate=True)); aggregate.close()
    contact = Image.new('RGB', (1350, math.ceil(len(thumbnails) / 3) * 570), 'white')
    draw = ImageDraw.Draw(contact)
    for i, (name, path) in enumerate(thumbnails):
        with Image.open(path) as image:
            thumb = ImageOps.contain(image.convert('RGB'), (434, 534))
            x, y = i % 3 * 450, i // 3 * 570
            draw.text((x + 8, y + 8), name, fill='black')
            contact.paste(thumb, (x + (450 - thumb.width) // 2, y + 30))
    contact.save(root / 'DG_contact.png')
    print(json.dumps({'complete': True, 'changed_A3_pages': len(packs), 'changed_NC_files': len(updates),
                      'A4_rewritten': False, 'backup': str(backup), 'hardware_accessed': False}), flush=True)


if __name__ == '__main__':
    main()
