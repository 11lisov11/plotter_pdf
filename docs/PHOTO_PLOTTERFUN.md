# Local Plotterfun photo engine

The original 23 Plotterfun algorithms run offline through Node.js workers.
Five additional stipple/TSP variants and a full-page spiral bring the gallery to 29 styles. This is
real vector geometry, not a raster image embedded in a PDF. Original sources
are pinned to `faf67d4dadc359a9d5703b0c4e501ea3bbad84d9` under
`third_party/plotterfun`; keep its MIT license and dependency notices.

## Prepare, do not draw

Install Node.js (available on PATH), or set `PLOTTERFUN_NODE` to `node.exe`.
Use the normal Python project environment with photo dependencies installed.

```powershell
python scripts/prepare_plotterfun_photo.py "photo.jpg" --styles all --out-dir "_plotter_jobs/photo_all_A4"
python scripts/prepare_plotterfun_photo.py --list-styles
python scripts/prepare_plotterfun_photo.py "photo.jpg" --styles linedraw,squiggle,tsp --quality detailed --out-dir "_plotter_jobs/photo_selected_A4"
python scripts/prepare_photo_plot_package.py "photo.jpg" --plotterfun-style all --out-dir "_plotter_jobs/photo_all_A4"
```

These commands NEVER open a serial port, reset a controller, or start drawing.
Existing `sketch`, `classic`, `hatch`, `scribble`, `portrait`, technical-drawing,
A3 split and registered A1/A2 pipelines are not replaced.

## A4, tone and scale

- Small plotter only: the current production 180 x 280 mm work field.
- Default `--fit cover --margin-mm 0`: fills the active field without stretching
  the photograph. Side/top crop depends on the original aspect ratio. A4 paper
  itself is 210 x 297 mm; its inaccessible margins cannot be drawn.
- Use `--fit contain` to keep the full photograph with white bands.
- EXIF orientation and transparency are resolved before processing.
- Neutral settings pass original RGB to the original worker, like the website.
  No automatic brightening or grayscale conversion is applied. Optional tone
  adjustments use `--contrast`, `--gamma` and `--local-contrast-blend 0..1`.
- Spiral uses a dense, overlapping tonal profile (spacing 0.5, amplitude 3,
  frequency 100, worker contrast 10) rather than the earlier sparse profile.
  Use custom controls for the site's neutral defaults (spacing 1, amplitude 1,
  frequency 150, contrast 0). Closed contours retain their closing segment.
- `spiral` is circular, like the original site; it cannot fill a rectangular A4.
  `spiral-page` runs the unchanged worker on white overscan and clips back to
  the central photograph. It fills all corners of the 180 x 280 mm field,
  without stretching the image or adding pen-down bridges outside the field.
- Each original algorithm has a density profile for readable A4 output. Some
  styles are intentionally abstract: no claim of photorealism for every style.
- Fixed `--seed` makes random styles reproducible with the pinned code/runtime.
- Algorithms output pixel-space paths; the adapter clips segments, splits at
  nonfinite points, simplifies by only 0.025 mm and converts to millimetres.
  Clipping never bridges two disconnected visible fragments.

## Output and safety

Each style has `photo_plot.nc`, an A4 PDF/PNG reconstructed from its FINAL NC,
an SVG of the same pen-down paths, and a manifest with source settings/hash.
The root contains `All_styles_from_Gcode.pdf`, contact sheets, a local HTML
gallery and `photo_queue.json`. Preview titles never enter the NC file.

The production Z-axis pen-lift/finalization pipeline is reused with full lifts
between independent paths. Photo curves are not replaced by fitted arcs or
joined across white gaps. Exact duplicated segments use the shared production
deduplicator. A dedicated linear photo writer avoids technical collinearity
cleanup collapsing small closed art loops; the existing drawing writer is
not modified. Isolated workers also receive the website's common brightness
defaults, including styles such as Linescan that omit them in their controls.
A completion barrier precedes motor release. Firmware, homing
reference and machine settings are not changed by preparation.

The JavaScript adapter accepts only the bundled algorithm allowlist and local
dependencies; no webpage or remote image upload is involved. Each style runs
in its own worker with a hard execution limit. A failed/timed-out style is
reported, never passed off as a finished partial drawing.

Stipple shapes reuse the original worker's optimized particles through its own
redraw API. The completed raw variants are cached locally in `.plotter_cache`,
which is ignored by Git. They do not repeat the full Voronoi/TSP calculation.

Custom controls use a JSON object with optional `*` and per-style objects:

```json
{"squiggle": {"Line Count": 150, "Amplitude": 0.8}, "tsp": {"Max Stipples": 3000}}
```

Pass it with `--controls controls.json`. Labels and value ranges follow the
original Plotterfun controls; invalid controls are rejected.

Source: https://github.com/mitxela/plotterfun
Live reference: https://mitxela.com/plotterfun/
