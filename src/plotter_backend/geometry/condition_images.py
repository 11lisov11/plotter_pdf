"""Recover small embedded condition diagrams as real centerline pen paths."""

from __future__ import annotations

from pathlib import Path


def extract_condition_miniatures(source_pdf: Path, *, page_index: int = 0, logger=None):
    import fitz
    import numpy as np
    from src import plotter_pdf_drawer as backend
    from .path_processing import remove_rectangular_border

    paths, records, seen = [], [], set()
    render_scale = 6.0
    mm_per_point = 25.4 / 72.0
    with fitz.open(source_pdf) as document:
        page = document[page_index]
        for image in page.get_image_info(xrefs=True):
            rect = fitz.Rect(image['bbox']) & page.rect
            width, height = rect.width * mm_per_point, rect.height * mm_per_point
            if not (2 <= width <= 85 and 2 <= height <= 85 and width * height <= 5000):
                continue
            key = tuple(round(v, 3) for v in rect)
            if key in seen:
                continue
            seen.add(key)
            # Page rendering applies the image's placement matrix exactly once.
            # Raw xref pixels can be upside down in KOMPAS exports.
            pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale),
                                  clip=rect, colorspace=fitz.csGRAY, alpha=False)
            gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            pixel_paths = backend._extract_image_centerline_paths_px(
                gray, min_component_px=3, min_path_px=1.5,
                max_paths=20000, rdp_px=.35, threshold_floor=0)
            if not pixel_paths and int(gray.min()) < 150:
                raise ValueError(f'Could not recover condition miniature: {source_pdf}, {key}')
            restored = [[((pix.x + x + .5) / render_scale * mm_per_point,
                          (pix.y + y + .5) / render_scale * mm_per_point)
                         for x, y in poly] for poly in pixel_paths if len(poly) > 1]
            # The scanned book-picture border is not part of the epure. Its
            # centerline can wander by a few pixels, so use a narrow source-mm
            # edge band; internal axes, geometry and the variant badge remain.
            bounds = (rect.x0 * mm_per_point, rect.x1 * mm_per_point,
                      rect.y0 * mm_per_point, rect.y1 * mm_per_point)
            restored = remove_rectangular_border(restored, bounds, tolerance_mm=.35)
            paths.extend(restored)
            record = {'bbox_mm': [v * mm_per_point for v in rect],
                      'stroke_count': len(restored), 'render_scale': render_scale,
                      'method': 'page-oriented centerline paths, not image contours',
                      'outer_border_removed': True}
            records.append(record)
            if logger:
                logger(f"Condition miniature recovered: {record['bbox_mm']}, strokes={len(restored)}")
    return paths, records
