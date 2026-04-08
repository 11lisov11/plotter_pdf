# Drawing Line Optimization Plan

## Goal

Optimize the technical-drawing pipeline so that:

- text and symbols in drawings are emitted as averaged single-line strokes instead of dotted/outline-like fragments;
- pen lifts are reduced materially during writing of dimensions, labels, and title blocks;
- small gaps inside symbols and text are closed more reliably;
- technical geometry remains exact and is not degraded by handwriting-oriented heuristics.

## Current Symptoms

Observed in real drawing packages:

- digits, letters, and symbols are often exported as fragmented contours or tiny filled components;
- centerline conversion is inconsistent for drawing text and technical symbols;
- many very short isolated segments survive into G-code, causing excessive pen up/down cycles;
- local text clusters are not stitched aggressively enough before reorder/penlift stages;
- G-code postprocessing merges only very short travel hops, but by that stage topology is already too fragmented.

## Current Relevant Code

### Extraction / text-to-path / geometry synthesis

- [prepare_folder1_packages.py](C:/plotter_pdf/scripts/prepare_folder1_packages.py)
- [plotter_pdf_drawer.py](C:/plotter_pdf/src/plotter_pdf_drawer.py)
- [pdf_converter.py](C:/plotter_pdf/src/plotter_backend/converters/pdf_converter.py)
- [protocol.py](C:/plotter_pdf/plotter_studio/core/protocol.py)

### Path topology / clipping / dedup

- [path_processing.py](C:/plotter_pdf/src/plotter_backend/geometry/path_processing.py)
- [protocol.py](C:/plotter_pdf/plotter_studio/core/protocol.py)
- [plotter_pdf_drawer.py](C:/plotter_pdf/src/plotter_pdf_drawer.py)

### Pen-lift / final G-code behavior

- [penlift_postprocess.py](C:/plotter_pdf/src/penlift_postprocess.py)
- [penlift.py](C:/plotter_pdf/src/plotter_backend/gcode/penlift.py)

## Root-Cause Hypothesis

The bad behavior is not caused by a single bug. It is the result of four layers interacting badly:

1. PDF/SVG converters often emit drawing text as closed outlines or tiny filled contours.
2. The current single-stroke recovery is heuristic and incomplete for technical symbols.
3. Fragmented pieces are not stitched into stable symbol groups early enough.
4. Pen-lift optimization happens too late, after fragmentation is already baked into topology.

## Non-Goals

- Do not alter dimension geometry, frame geometry, hatching, or exact construction lines unless explicitly marked as text/symbol content.
- Do not reuse TOE handwriting behavior for technical drawings.
- Do not trade geometric correctness for small similarity gains in raster compare.

## Acceptance Criteria

The plan is considered successful only if all of these improve on a regression corpus:

- pen lifts on text-heavy drawings reduced by at least 35%;
- count of very short draw segments under `0.35 mm` reduced by at least 50%;
- dotted/point-like symbol fragments reduced to near zero on title blocks and dimensions;
- drawing-level layout similarity must not regress by more than `0.005` on any protected package;
- no regression in A3 pass alignment or title-block placement.

## Regression Corpus

Use these packages as mandatory regression inputs:

### Technical A4

- [Втулка_pack](C:/plotter_pdf/Компьютерная%20графика/Втулка_pack)
- [Заглушка_pack](C:/plotter_pdf/Компьютерная%20графика/Заглушка_pack)
- [Переходник_pack](C:/plotter_pdf/Компьютерная%20графика/Переходник_pack)
- [МЧ00.01.00.05 Тарелка_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.05%20Тарелка_pack)
- [МЧ00.01.00.06 Пружина_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.06%20Пружина_pack)
- [МЧ00.01.00.07 Винт М16_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.07%20Винт%20М16_pack)
- [Спецификация_pack](C:/plotter_pdf/Компьютерная%20графика/Спецификация_pack)

### Technical A3

- [ЛБ 1 Маховик_pack](C:/plotter_pdf/Компьютерная%20графика/ЛБ%201%20Маховик_pack)
- [ЛБ 2 (1)_pack](C:/plotter_pdf/Компьютерная%20графика/ЛБ%202%20(1)_pack)
- [ЛБ 2 (2)_pack](C:/plotter_pdf/Компьютерная%20графика/ЛБ%202%20(2)_pack)
- [МЧ00.01.00.00 СБ Клапан перепускной_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.00%20СБ%20Клапан%20перепускной_pack)
- [МЧ00.01.00.00 СП Клапан перепускной_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.00%20СП%20Клапан%20перепускной_pack)
- [МЧ00.01.00.01 Корпус_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.01%20Корпус_pack)
- [МЧ00.01.00.02 Крышка_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.02%20Крышка_pack)

## Phase 1: Instrumentation And Measurement

### Objective

Measure fragmentation before changing heuristics.

### Work

- Add per-package metrics:
  - count of draw polylines;
  - count of pen-down strokes after penlift postprocess;
  - count of segments shorter than `0.35 mm`;
  - count of disconnected symbol-like clusters;
  - travel length / draw length ratio.
- Add symbol-focused metrics:
  - small closed loops count;
  - tiny isolated path count;
  - local cluster component count for dimension text and title-block text.

### Files

- [prepare_folder1_packages.py](C:/plotter_pdf/scripts/prepare_folder1_packages.py)
- [penlift_postprocess.py](C:/plotter_pdf/src/penlift_postprocess.py)
- [protocol.py](C:/plotter_pdf/plotter_studio/core/protocol.py)

### Output

- `report.json` and compare artifacts should include topology metrics, not only layout similarity.

## Phase 2: Content Classification For Technical Text

### Objective

Separate technical text/symbol content from exact geometry before G-code generation.

### Work

- Detect text/symbol clusters using:
  - bounding box size;
  - stroke density;
  - local component count;
  - proximity to dimension lines/arrows;
  - title-block regions;
  - source-id grouping from SVG/PDF import.
- Introduce explicit roles:
  - `tech_text`
  - `tech_symbol`
  - `dim_text`
  - `title_block_text`
  - `exact_geometry`
- Never run technical text through handwriting routes.

### Files

- [plotter_pdf_drawer.py](C:/plotter_pdf/src/plotter_pdf_drawer.py)
- [svg_text_utils.py](C:/plotter_pdf/src/plotter_backend/svg_text_utils.py)
- [prepare_folder1_packages.py](C:/plotter_pdf/scripts/prepare_folder1_packages.py)

## Phase 3: Single-Line Recovery For Digits And Symbols

### Objective

Convert fragmented or outline-like symbol content into averaged single-line geometry.

### Work

- Expand current single-stroke recovery to explicitly cover:
  - digits `0-9`;
  - decimal commas and dots;
  - degree sign;
  - diameter sign;
  - `R`, `M`, `x`, `/`, `-`, `+`, `:`;
  - title-block alphanumerics.
- For filled/outline glyphs:
  - cluster nearby components;
  - skeletonize locally;
  - preserve narrow loops;
  - reject bogus skeleton branches;
  - limit branch explosion inside one glyph.
- Add symbol templates for very common technical marks if centerline extraction is unstable:
  - degree mark;
  - diameter sign;
  - simple arrowhead-adjacent digits;
  - stamp grid text.

### Files

- [plotter_pdf_drawer.py](C:/plotter_pdf/src/plotter_pdf_drawer.py)
- [protocol.py](C:/plotter_pdf/plotter_studio/core/protocol.py)
- [handwriting_text_utils.py](C:/plotter_pdf/src/plotter_backend/handwriting_text_utils.py)

### Key Existing Constants To Revisit

- `SINGLE_STROKE_TEXT_ENABLED`
- `SINGLE_STROKE_OUTLINE_TEXT_ENABLED`
- `FILL_CENTERLINE_*`
- `ARROWHEAD_*`

## Phase 4: Local Continuity Stitching

### Objective

Reduce artificial pen lifts inside one word, number, or symbol group.

### Work

- Add cluster-local stitch pass before global reorder:
  - nearest-end join inside one symbol group;
  - A->B->A backtrack removal;
  - collinear gap bridging;
  - slash/diagonal continuity preservation;
  - loop-safe joining for `0`, `6`, `8`, `9`.
- Prefer continuity inside local text clusters over strict source-order preservation.
- Add separate tolerances for:
  - title-block text;
  - dimension text;
  - tiny notation near arrows.

### Files

- [plotter_pdf_drawer.py](C:/plotter_pdf/src/plotter_pdf_drawer.py)
- [protocol.py](C:/plotter_pdf/plotter_studio/core/protocol.py)
- [path_processing.py](C:/plotter_pdf/src/plotter_backend/geometry/path_processing.py)

## Phase 5: Reorder Optimization For Text Clusters

### Objective

Reduce travel within already-recovered text clusters.

### Work

- Introduce cluster-aware ordering:
  - reorder within one text cluster first;
  - keep exact geometry outside the cluster untouched;
  - direction-normalize neighboring strokes when that removes lifts.
- Prefer local serpentine order for title blocks and specification tables.
- Keep a guard to avoid reordering dimension geometry away from arrows and extension lines.

### Files

- [plotter_pdf_drawer.py](C:/plotter_pdf/src/plotter_pdf_drawer.py)
- [protocol.py](C:/plotter_pdf/plotter_studio/core/protocol.py)

## Phase 6: Pen-Lift Postprocess Optimization

### Objective

Make final G-code exploit improved continuity instead of reintroducing chatter.

### Work

- Extend short-travel merge logic beyond current conservative thresholds.
- Add text-cluster-aware travel merge mode:
  - if a lift is shorter than threshold and stays inside one text cluster, keep pen down;
  - use separate threshold for technical text vs handwriting.
- Suppress micro-lifts produced by tiny non-drawing travel hops after reorder.
- Add reporting:
  - total lifts before/after;
  - merged hops count;
  - average pen-down stroke length.

### Files

- [penlift_postprocess.py](C:/plotter_pdf/src/penlift_postprocess.py)
- [penlift.py](C:/plotter_pdf/src/plotter_backend/gcode/penlift.py)

## Phase 7: Package-Level Validation

### Objective

Ensure optimization improves real packages, not only synthetic tests.

### Work

- Rebuild the regression corpus.
- Generate for each package:
  - updated compare preview;
  - topology metrics;
  - before/after lift counts;
  - short-segment histograms.
- Manually inspect worst packages:
  - `СБ`
  - `СП`
  - `Спецификация`
  - `Корпус`
  - `Крышка`
  - `ЛБ 2 (1)`
  - `ЛБ 2 (2)`

## Phase 8: Safe Rollout

### Objective

Ship without breaking existing drawing preparation.

### Work

- Add feature flags:
  - `TECH_TEXT_SINGLELINE_ENABLE`
  - `TECH_TEXT_CLUSTER_STITCH_ENABLE`
  - `TECH_TEXT_PENLIFT_OPT_ENABLE`
- Default them on only after package regression is green.
- Keep one command to rebuild all drawing packages and compare before/after.

## Implementation Order

Recommended execution order:

1. Instrumentation and metrics.
2. Technical text classification.
3. Single-line recovery for digits and symbols.
4. Local continuity stitching.
5. Reorder optimization.
6. Pen-lift optimization.
7. Rebuild all drawing packages.
8. Manual review of worst packages.
9. Enable rollout by default.

## Immediate First Deliverable

Before touching heuristics broadly, implement this minimal slice:

1. Add fragmentation metrics and lift metrics.
2. Build one isolated technical-text cluster pipeline.
3. Apply it only to:
   - title-block text;
   - dimension numbers;
   - small technical symbols.
4. Rebuild:
   - [МЧ00.01.00.00 СБ Клапан перепускной_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.00%20СБ%20Клапан%20перепускной_pack)
   - [Спецификация_pack](C:/plotter_pdf/Компьютерная%20графика/Спецификация_pack)
   - [МЧ00.01.00.02 Крышка_pack](C:/plotter_pdf/Компьютерная%20графика/МЧ00.01.00.02%20Крышка_pack)

That slice is enough to prove whether the approach is correct before refactoring the full drawing pipeline.
