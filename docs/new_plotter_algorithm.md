# New plotter drawing algorithm

This is the project-level contract for the drawing mode tested in
`Компьютерная графика/новый тест букв`.

The key rule: do not repair broken final G-code by deleting random lines. A
new run must build a clean plotter job from source artifacts and then render a
preview from the final G-code.

## Pipeline

1. Source
   - Use the original KOMPAS PDF as the source of truth.
   - Rebuild the package from the PDF when requested.
   - Do not use previously edited `*_plotter_ready.*` files as input.
   - Do not use generated `page_01.nc`, `pass_01.nc`, or `pass_02.nc`
     as the geometry source for the new algorithm.
   - `report.json` may be used only as placement metadata for A3/A4 pass
     transforms after the package has been rebuilt.

2. Geometry layer
   - Extract technical geometry directly from the source PDF/SVG with PDF
     text nodes disabled as plotted geometry.
   - Preserve drawing scale rules selected by the package builder.
   - Keep A3 as two explicit passes.
   - Keep A4 as one explicit pass.

3. Text layer
   - Do not plot PDF glyph contours as the final text source.
   - Extract text strings and their placement from the source PDF.
   - Render recognized technical text with real `GOST_AU.ttf` through the in-project TTF centerline backend.
   - Production `*_new_algorithm` text uses the explicitly approved LibreCAD OpenGOST LFF font `assets/single_line_fonts/lc_opengost-ar.lff`; do not fall back to TTF skeleton text or the old hand-coded glyph dictionary unless explicitly requested.
   - If text cannot be recognized confidently, keep the source geometry and
     mark the package for manual review instead of guessing.

4. Frame rules
   - Apply frame rules before G-code emission, not after plotting output exists.
   - For A3 pass 2, remove only the extra outer KOMPAS frame around the stamp
     zone when that outer frame is outside the required plotted stamp.
   - Do not delete internal stamp grid lines.
   - Do not alter drawing geometry scale to fix frame placement.

5. Final G-code normalization
   - Stitch fragmented strokes.
   - Deduplicate repeated draw segments.
   - Apply the measured machine compensation as a named parameter.
   - Add the safe trailer: pen up, home, motors release.

6. Preview and audit
   - Render preview from the final G-code, not from the source PDF.
   - Produce per-pass PNG/PDF previews.
   - Produce contact sheets for quick visual review.
   - Write a CSV audit with bounds and segment counts.

## Current measured defaults

- Work area: `180 x 280 mm`.
- Calibration machine bounds: `X 0..180`, `Y -285..-5`.
- Paper preview transform: `plotter_y_mirror`.
- Current X compensation: `0.000 mm` (`dedup_xfixed`, no extra X mirror/shift).
- Text font target: `assets/single_line_fonts/lc_opengost-ar.lff` via LibreCAD OpenGOST LFF single-line strokes (`fill=0.86`, `stamp_fill=0.62`, `shear=0.24`).

## Command contract

When the user says "new algorithm", run the dedicated runner:

```powershell
python scripts\prepare_plotter_ready_new_algorithm.py --variant-root "Компьютерная графика\9 вариант" --rebuild
```

For an already rebuilt package folder:

```powershell
python scripts\prepare_plotter_ready_new_algorithm.py --variant-root "Компьютерная графика\9 вариант"
```

The runner writes only explicitly named new-algorithm outputs:

- `page_01_new_algorithm.nc`
- `page_01_new_algorithm.gcode`
- `pass_01_new_algorithm.nc`
- `pass_01_new_algorithm.gcode`
- `pass_02_new_algorithm.nc`
- `pass_02_new_algorithm.gcode`
- `*_new_algorithm_preview_plotter_y_mirror_preview.png`
- `*_new_algorithm_preview_plotter_y_mirror_preview.pdf`

The old `*_plotter_ready.*` files are not used as input and are not modified.
The old package `page_01.nc` / `pass_*.nc` files are also not used as input.
