"""Offline route-only rebuild, with exact NC-geometry audit before replacement."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fitz
from scripts import prepare_pogudin_small as prep
from scripts.rebuild_registered_single_stroke import coverage
from src.plotter_backend.geometry.stroke_routing import route_metrics


def rebuild(root, backup):
    root = root.resolve()
    queue_path = root / 'queue.json'
    queue_blob = queue_path.read_bytes()
    queue = json.loads(queue_blob)
    packs = list(dict.fromkeys(Path(r['file']).parent for r in queue))
    save = backup / root.name
    save.mkdir(parents=True, exist_ok=False)
    (save / 'queue.json').write_bytes(queue_blob)
    staged, records, metadata, reports = {}, {}, {}, []
    previews = {}
    # No prepared file is replaced until every candidate in this collection
    # passes the independent interval-union audit of its serialized NC.
    with tempfile.TemporaryDirectory(prefix='route_rebuild_') as temporary:
        for pack in packs:
            blob = (pack / 'manifest.json').read_bytes()
            meta = json.loads(blob)
            settings = prep.pipeline.Settings(**meta['settings'])
            target = save / pack.relative_to(root)
            target.mkdir(parents=True)
            (target / 'manifest.json').write_bytes(blob)
            for name in ('plot_preview.pdf', 'plot_preview.png'):
                if (pack / name).exists():
                    shutil.copyfile(pack / name, target / name)
            assembled = []
            two = len(meta['passes']) == 2
            width = settings.work_width * (2 if two else 1)
            for record in meta['passes']:
                path = Path(record['file'])
                old_blob = path.read_bytes()
                if hashlib.sha256(old_blob).hexdigest() != record['sha256']:
                    raise ValueError(f'Input hash mismatch: {path}')
                (target / path.name).write_bytes(old_blob)
                text = old_blob.decode('utf-8-sig')
                old = prep.actual_strokes(text, settings)
                old_union, old_stats = coverage(old)
                temp_nc = Path(temporary) / 'candidate.nc'
                prep.pipeline.stitch_gcode_polylines.write_gcode(
                    temp_nc, old, feed_travel=settings.feed_travel, feed_draw=settings.feed_draw,
                    z_up=settings.z_up, z_down=settings.z_down, z_feed=settings.z_feed,
                    home_x=settings.home_x, home_y=settings.home_y, home_feed=settings.home_feed,
                    legacy_z_reference=settings.legacy_z_reference, safe_start_y=settings.safe_start_y_mm)
                header = '\n'.join(s for s in text.splitlines() if s.startswith(';'))
                payload = header + '\n; Exact endpoint trail routing; no recognition or fit change.\n' + temp_nc.read_text(encoding='utf-8') + prep.pipeline._safe_trailer_text(settings)
                after = prep.actual_strokes(payload, settings)
                new_union, new_stats = coverage(after)
                if old_union != new_union or new_stats['overdraw_mm'] > .000001:
                    raise ValueError(f'Geometry/overdraw audit failed: {path}')
                options = dict(home=(settings.home_x, settings.home_y), z_up=settings.z_up,
                               z_down=settings.z_down, z_feed=settings.z_feed, feed_travel=settings.feed_travel)
                before_metrics = route_metrics(old, **options)
                after_metrics = route_metrics(after, **options)
                if after_metrics['nominal_non_drawing_seconds'] > before_metrics['nominal_non_drawing_seconds'] + 1e-6:
                    raise ValueError(f'Travel/lift cost regressed: {path}')
                report = {'file': str(path), 'before': before_metrics, 'after': after_metrics,
                          'geometry_identical': True, 'overdraw_mm': new_stats['overdraw_mm'],
                          'draw_length_mm': new_stats['draw_length_mm']}
                reports.append(report)
                staged[path] = payload.encode('utf-8')
                record['sha256'] = hashlib.sha256(staged[path]).hexdigest()
                records[str(path)] = record
                dx, dy = record['offset_mm']
                for poly in after:
                    points = [(x-dx, y-dy-settings.work_min_y) for x,y in poly]
                    assembled.append(points if record['part']==1 else [(width-x, settings.work_height-y) for x,y in points])
            meta['route_optimization'] = {'algorithm': 'exact-euler-trails-cost-guard/v1',
                                           'geometry_source': 'previous_final_nc', 'backup': str(target)}
            metadata[pack] = meta
            previews[pack] = (assembled, two, settings)
        for path, payload in staged.items():
            path.write_bytes(payload)
        for pack, meta in metadata.items():
            (pack/'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            assembled, two, settings = previews[pack]
            preview = prep.render_from_nc(assembled, two, pack/'plot_preview.pdf', settings)
            (pack.parent/(meta['task']+'.pdf')).write_bytes(preview.tobytes(garbage=4, deflate=True))
            preview.close()
        for row in queue:
            row.update(records[row['file']])
        queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
    groups = defaultdict(list)
    for pack, meta in metadata.items():
        groups[meta['source']].append(pack)
    comparison = fitz.open()
    mm = 72/25.4
    report_by_pack = defaultdict(list)
    for row in reports:
        report_by_pack[Path(row['file']).parent].append(row)
    for source, members in groups.items():
        aggregate = fitz.open()
        destination = root/Path(source).name
        if destination.exists():
            shutil.copyfile(destination, save/destination.name)
        for pack in members:
            with fitz.open(pack/'plot_preview.pdf') as doc:
                aggregate.insert_pdf(doc)
                with fitz.open(save/pack.relative_to(root)/'plot_preview.pdf') as old_doc:
                    page = comparison.new_page(width=860*mm, height=322*mm)
                    old_count = sum(r['before']['pen_down_paths'] for r in report_by_pack[pack])
                    new_count = sum(r['after']['pen_down_paths'] for r in report_by_pack[pack])
                    page.insert_text((10*mm, 10*mm), f'{pack.parent.name}/{pack.name}: lifts {old_count} -> {new_count}; exact ink geometry unchanged', fontsize=12)
                    page.show_pdf_page(fitz.Rect(5*mm,20*mm,425*mm,317*mm), old_doc, 0)
                    page.show_pdf_page(fitz.Rect(435*mm,20*mm,855*mm,317*mm), doc, 0)
        destination.write_bytes(aggregate.tobytes(garbage=4, deflate=True))
        aggregate.close()
    comparison.save(root/'Route_before_after_from_Gcode.pdf', deflate=True)
    comparison.close()
    (root/'route_optimization.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    totals = {key: sum(r[key]['pen_down_paths'] for r in reports) for key in ('before','after')}
    print(json.dumps({'root':str(root),'NC_files':len(reports),'lifts':totals,'all_geometry_identical':True,'hardware_accessed':False}), flush=True)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', nargs='+', type=Path)
    args = parser.parse_args()
    backup = ROOT/'backups'/'route_optimization'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_UTC')
    all_reports = []
    for root in args.roots:
        all_reports.extend(rebuild(root, backup))
    (backup/'report.json').write_text(json.dumps(all_reports, indent=2), encoding='utf-8')
    print('BACKUP',backup,flush=True)


if __name__ == '__main__':
    main()
