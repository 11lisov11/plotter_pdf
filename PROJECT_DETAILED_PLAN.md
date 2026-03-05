# Plotter Studio - Detailed Execution Plan

Updated: 2026-03-05 (revised v32)  
Project root: `C:\plotter_pdf`

## 0. What Is Not Done Yet (Actual, 2026-03-05)

This is the authoritative list of unfinished work. Items below are intentionally strict and measurable.

### P0 (must finish before release)

- [ ] **HW acceptance for handwriting quality**  
  DoD:
  - run real plotter on `r232a` pages `1..6` and `r238e` pages `1..2`;
  - save photos/scans for each printed page;
  - confirm no critical defects in text/formulas/graphs;
  - confirm no visible double-stroke artifacts on letters;
  - append evidence links/paths to `PDF_HANDWRITING_EXECUTION_LOG_2026-03-05.md`.

- [x] **All-pages sheet-swap pause validation on real hardware**  
  DoD:
  - run multi-page draw (`>=3` pages);
  - verify `continue` flow on at least two pauses;
  - verify `cancel` flow on pause (no freeze/crash, correct stop state);
  - record operation logs and result in execution log.
  Status:
  - `done` (hardware validation report: `_tmp/hw/g2/g2_pause_validation_report.json`).

- [ ] **Enable required GitHub branch protection checks**  
  DoD:
  - apply protection on `main` via `set_branch_protection.ps1` (or UI);
  - require CI statuses (`lint`, `tests`, `build-smoke-windows`);
  - require PR review before merge;
  - store applied policy snapshot in `.github/BRANCH_PROTECTION_SETUP.md`.

### P1 (release hardening)

- [ ] **Portable validation on clean Windows machine**  
  DoD:
  - validate `dist/PlotterStudio-portable.zip` on fresh host/VM;
  - verify startup + preview smoke + log creation;
  - attach evidence (host info, timestamps, checksum match) to `RELEASE_CHECKLIST.md`.

- [x] **Finish remaining typed-error normalization (M4 tail)**  
  Status:
  - `done` for current software scope (critical runtime branches converted; typed-class tests added).

### P2 (post-release engineering quality)

- [ ] **Continue backend modularization (M3 tail)**  
  DoD:
  - extract next geometry/path-processing slice from monolith;
  - keep compatibility wrappers and regression tests green.

- [x] **Raise protocol coverage toward target**  
  Status:
  - `done` (current local `protocol.py` coverage: ~76%).

## 0.1 Detailed Software-Only Backlog (No Plotter Required)

This section is a strict execution queue for tasks that can be completed without hardware access.

### SO-1 (P0) Finish typed-error normalization tail

- Status:
  - `done` for current software scope.

- Scope:
  - replace remaining generic runtime errors in critical adapter paths with typed backend errors;
  - unify message format: short user message + typed class marker.
- Current focus files:
  - `plotter_studio/core/protocol.py`
  - `src/plotter_backend/converters/*.py`
  - `src/plotter_backend/machine/*.py`
- Commands:
  - `.\.venv\Scripts\ruff.exe check src plotter_studio tests scripts`
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
  - `.\.venv\Scripts\python.exe -m pytest -q`
- DoD:
  - no new generic `RuntimeError` in touched critical branches;
  - tests assert exception class for each changed failure path;
  - full suite remains green.

### SO-2 (P0) Raise protocol coverage from ~54% to >=60%

- Status:
  - `done` (current local `protocol.py` coverage: ~76%).

- Scope:
  - add tests for untested paths in `protocol.py`:
    - backend import fallback and backend-path failure;
    - preview generation negative branches;
    - method3 source/page boundary and cancellation paths;
    - manual/emergency/probe adapter branches not yet covered.
- Commands:
  - `.\.venv\Scripts\python.exe -m coverage erase`
  - `.\.venv\Scripts\python.exe -m coverage run -m unittest discover -s tests -p "test_*.py"`
  - `.\.venv\Scripts\python.exe -m coverage report -m --include "plotter_studio/core/protocol.py"`
- DoD:
  - `protocol.py` coverage >= `60%`;
  - coverage snapshot copied to "Progress snapshot" in this file.

### SO-3 (P1) UI reliability tests (headless)

- Status:
  - `done` (headless MainWindow UI reliability suite added and validated in 5 repeated runs).

- Scope:
  - introduce/expand headless Qt tests for:
    - connect/disconnect flow;
    - preview/draw dispatch and disable/enable states;
    - cancel operation flow;
    - settings restore and log drawer persistence.
- Commands:
  - `.\.venv\Scripts\python.exe -m pytest -q tests/test_main_window_headless.py`
  - `1..5 | % { .\.venv\Scripts\python.exe -m pytest -q tests/test_main_window_headless.py }`
- DoD:
  - stable headless UI smoke pass in 5 repeated runs;
  - no flaky timing-based assertion.

### SO-4 (P1) Portable package validation on clean VM

- Scope:
  - verify portable zip on fresh Windows environment (no dev toolchain assumptions);
  - capture startup smoke evidence and checksum match.
- Commands:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1`
  - `powershell -NoProfile -ExecutionPolicy Bypass -File .\validate_portable.ps1`
- DoD:
  - validation evidence attached to `RELEASE_CHECKLIST.md` and release log.

### SO-5 (P1) GitHub protection activation

- Scope:
  - apply required checks and PR review requirement on `main`.
- Prerequisite:
  - `GITHUB_TOKEN` with repo admin permission.
- Commands:
  - `$env:GITHUB_TOKEN="<token>"; powershell -NoProfile -ExecutionPolicy Bypass -File .\set_branch_protection.ps1`
- DoD:
  - branch policy confirmed in GitHub settings;
  - reflected in `.github/BRANCH_PROTECTION_SETUP.md`.

### SO-6 (P2) Acceptance analytics hardening

- Status:
  - `done` (script now supports optional baseline report comparison).

- Scope:
  - add automatic "before/after" delta report for `duplicate/tiny/short` ratios between runs;
  - keep regression threshold checks in CI-friendly format.
- Commands:
  - `.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py ...`
- DoD:
  - report contains per-page delta and pass/fail summary;
  - regression detection is reproducible in local run.

## 0.2 Detailed Next Execution Plan (Strict Order, No Skips)

This is the next detailed action sequence from current status.  
Follow stages in order; parallel tracks are explicitly marked.

### Stage G0 - Daily start gate (required before any task)

Goal: prevent work on unstable baseline.

Steps:

1. Run baseline checks.
2. Ensure plan/log files are writable and current date is reflected.
3. Confirm blockers state (`hardware`, `GITHUB_TOKEN`, `clean VM` availability).

Commands:

```powershell
.\.venv\Scripts\ruff.exe check src plotter_studio tests scripts
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m pytest -q
if ($env:GITHUB_TOKEN) { 'GITHUB_TOKEN=SET' } else { 'GITHUB_TOKEN=MISSING' }
```

Artifacts:

- updated `PROJECT_DETAILED_PLAN.md` header date/revision if status changed;
- appended run note in `PDF_HANDWRITING_EXECUTION_LOG_2026-03-05.md` for acceptance-related runs.

Exit criteria:

- all three gates green (`ruff/unittest/pytest`);
- blocker state explicitly recorded for the day.

---

### Stage G1 - Hardware acceptance for handwriting quality (P0 blocker)

Goal: close real-plotter quality acceptance with evidence.

Input set:

1. `data/acceptance/r232a.pdf` pages `1..6`.
2. `data/acceptance/r238e.pdf` pages `1..2`.
3. Current accepted config/profile and quality gates from `PDF_HANDWRITING_ACCEPTANCE_PLAN.md`.

Execution protocol:

1. Generate/refresh software preview artifacts before printing (traceability baseline).
2. Plot pages physically one by one with fixed settings (no ad-hoc parameter changes mid-series).
3. After each page:
   - photo/scan page;
   - log readability defects;
   - mark pass/fail.
4. If a page fails:
   - isolate root cause (text/formula/graph/double-line/out-of-bounds);
   - change at most 1-2 parameters;
   - re-run failed page until pass;
   - restart full sequence for that PDF.

Commands (baseline pre-run):

```powershell
.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py `
  --pdf data\acceptance\r232a.pdf `
  --pages 1,2,3,4,5,6 `
  --out-dir _tmp\acceptance\r232a_final

.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py `
  --pdf data\acceptance\r238e.pdf `
  --pages 1,2 `
  --out-dir _tmp\acceptance\r238e_final
```

Required evidence layout:

- `_tmp/acceptance/hw/r232a/p1..p6/{photo|scan}.{jpg|png|pdf}`
- `_tmp/acceptance/hw/r238e/p1..p2/{photo|scan}.{jpg|png|pdf}`
- page-level notes in `PDF_HANDWRITING_EXECUTION_LOG_2026-03-05.md`

Exit criteria:

1. all 8 pages have physical evidence;
2. no critical defects in text/formulas/graphs;
3. no visible double-stroke artifacts judged on physical output;
4. results and evidence paths recorded in execution log.

---

### Stage G2 - Sheet-swap pause validation on hardware (P0 blocker)

Goal: validate all-pages pause/resume/cancel behavior on real machine.

Status:

- `done` (validated on hardware with dedicated 3-page PDF and saved report).

Scenarios:

1. `continue` path: multi-page job (`>=3` pages), confirm on at least two pauses.
2. `cancel` path: cancel at first pause, verify clean stop and stable UI state.

Steps:

1. Run all-pages draw from UI on prepared PDF.
2. Capture operation logs and timestamps around pause dialogs.
3. Record machine and UI state after each decision.

Required artifacts:

- operation logs from app;
- short operator notes per scenario;
- optional video capture for ambiguous cases.

Exit criteria:

1. no freeze/crash in either scenario;
2. correct next-page behavior for `continue`;
3. correct immediate stop for `cancel`;
4. result reflected in `PDF_HANDWRITING_EXECUTION_LOG_2026-03-05.md`.

Evidence:

1. `_tmp/hw/g2/g2_pause_validation_report.json`

---

### Stage G3 - Branch protection activation (P0 blocker)

Goal: enforce CI + review policy on `main`.

Prerequisite:

- `GITHUB_TOKEN` with repo admin rights.

Steps:

1. Apply protection script.
2. Verify required checks (`lint`, `tests`, `build-smoke-windows`) in GitHub UI/API.
3. Verify PR review requirement enabled.
4. Save resulting policy snapshot.

Command:

```powershell
$env:GITHUB_TOKEN="<token>"
powershell -NoProfile -ExecutionPolicy Bypass -File .\set_branch_protection.ps1
```

Artifacts:

- updated `.github/BRANCH_PROTECTION_SETUP.md` with applied rules and date.

Exit criteria:

- protection visible in repository settings and documented in repo.

---

### Stage G4 - Clean-machine portable validation (P1 blocker)

Goal: prove release portability outside dev machine.

Target environment:

- fresh Windows VM/host without dev toolchain assumptions.

Steps:

1. Build artifacts on main machine.
2. Transfer zip + checksum to clean VM.
3. Run startup/preview/dry-run smoke.
4. Capture host info + timestamps + checksum verification.
5. Record results in release checklist and validation log.

Commands (build side):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\validate_portable.ps1
Get-FileHash .\dist\PlotterStudio-portable.zip -Algorithm SHA256
```

Artifacts:

- `RELEASE_CHECKLIST.md` updated with pass/fail items;
- `RELEASE_VALIDATION_LOG_2026-03-04.md` append with clean-host evidence.

Exit criteria:

1. app starts on clean host;
2. preview smoke and dry-run output work;
3. checksum matches documented artifact.

---

### Stage G5 - Parallel software track while hardware blockers are pending

This stage is allowed only when G1/G2/G4 are blocked by unavailable hardware/VM.

#### G5.1 Next M3 extraction slice (geometry transform cluster)

Status:

- `done` (extracted with compatibility wrappers and direct module tests).

Scope:

- extract:
  - `mat_mul`
  - `mat_apply`
  - `parse_transform`
  - `parse_points`
  - `transform_points`
- keep compatibility wrappers in `src/plotter_pdf_drawer.py`.

Target module:

- `src/plotter_backend/geometry/transform.py`

Validation:

```powershell
.\.venv\Scripts\ruff.exe check src plotter_studio tests scripts
.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_geometry.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

DoD:

1. no behavior regression in existing tests;
2. new direct module tests added for extracted functions;
3. wrappers preserve public entrypoints.

#### G5.2 Next M3 extraction slice (simplify/fit cluster)

Status:

- `done` (simplify/RDP and arc-fit helper clusters extracted with compatibility wrappers and direct tests).

Scope candidate (after G5.1 only):

- `simplify_polyline`
- `rdp_simplify_polyline`
- `polyline_fit_arc`
- related pure geometry helpers.

DoD:

1. extraction in small commits;
2. deterministic tests for corner cases;
3. no drop in protocol/controller coverage snapshot.

#### G5.3 Coverage and diagnostics maintenance

Status:

- `done` (fresh focused coverage snapshot captured after latest extraction slices).

Steps:

1. run targeted coverage snapshot for `protocol.py`, `plotter_controller.py`, `serial_worker.py`;
2. keep thresholds at or above current levels.

Command:

```powershell
.\.venv\Scripts\python.exe -m coverage erase
.\.venv\Scripts\python.exe -m coverage run -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m coverage report -m --include "plotter_studio/core/protocol.py,plotter_studio/core/plotter_controller.py,plotter_studio/core/serial_worker.py"
```

#### G5.4 Next M3 extraction slice (SVG path geometry cluster)

Status:

- `done` (SVG path tokenization/curve approximation helpers extracted with compatibility wrappers and direct tests).

Scope:

- `parse_path_tokens`
- `cubic_approx`
- `quadratic_approx`
- `arc_to_polyline`

Target module:

- `src/plotter_backend/geometry/svg_path.py`

DoD:

1. compatibility wrappers in monolith keep public behavior stable;
2. direct module tests cover tokenization and curve/arc edge cases;
3. full lint + unit + pytest gates remain green.

#### G5.5 Next M3 extraction slice (path-processing core cluster)

Status:

- `done` (path-item bounds/unit-normalization helpers extracted with compatibility wrappers and direct tests).

Scope:

- `bounds_path_items`
- `normalize_path_units_to_page`
- `poly_inside_bbox`

Target module:

- `src/plotter_backend/geometry/path_processing.py`

DoD:

1. compatibility wrappers in monolith keep call signatures stable;
2. direct tests cover bounds, normalization trigger/skip branches, bbox inclusion tolerance;
3. full lint + unit + pytest gates remain green.

#### G5.6 Next M3 extraction slice (outer-frame detection helper)

Status:

- `done` (`filter_outer_frame_path_items` extracted into `path_processing` module with compatibility wrapper and direct tests).

Scope:

- `filter_outer_frame_path_items`
- closed-rectangle candidate branch
- fallback branch for borders exported as 4 separate axis-aligned lines

Target module:

- `src/plotter_backend/geometry/path_processing.py`

DoD:

1. wrapper in monolith preserves call signature and behavior;
2. direct module tests cover both main and fallback detection branches;
3. full lint + unit + pytest gates remain green.

#### G5.7 Next M3 extraction slice (path-items clipping helper)

Status:

- `done` (`clip_path_items_to_rect` extracted into `path_processing` module with compatibility wrapper and direct tests).

Scope:

- `clip_path_items_to_rect`
- clip/join continuity branch
- dropped outside-segment branch

Target module:

- `src/plotter_backend/geometry/path_processing.py`

DoD:

1. wrapper in monolith preserves `PathItem` output schema;
2. direct module tests cover both normal clipping and dropped-segment behavior;
3. full lint + unit + pytest gates remain green.

#### G5.8 Next M3 extraction slice (content-area crop helper)

Status:

- `done` (`clip_to_content_area` extracted into `path_processing` module with compatibility wrapper and direct tests).

Scope:

- `clip_to_content_area`
- page-margin disabled branch
- A4-only guard branch
- successful crop branch
- empty-crop fallback branch

Target module:

- `src/plotter_backend/geometry/path_processing.py`

DoD:

1. monolith wrapper preserves behavior with current margin constants and logging flow;
2. direct module tests cover all key decision branches;
3. full lint + unit + pytest gates remain green.

#### G5.9 Next M3 extraction slice (fit-to-work-area helper)

Status:

- `done` (`fit_polylines_to_area` extracted into `geometry/fitting.py` with compatibility wrapper and direct tests).

Scope:

- `fit_polylines_to_area`
- scale/translate branch
- dimensional-guard branch
- multi-pass shift branch

Target module:

- `src/plotter_backend/geometry/fitting.py`

DoD:

1. wrapper in monolith preserves behavior and logging semantics;
2. direct module tests cover scaling, dimensional guard, and pass-shift logic;
3. full lint + unit + pytest gates remain green.

#### G5.10 Next M3 extraction slice (work-area bounds/config helper)

Status:

- `done` (`base_work_area_bounds`, `work_area_bounds`, `configure_active_work_area` extracted into `geometry/work_area.py` with compatibility wrappers and direct tests).

Scope:

- `base_work_area_bounds`
- `work_area_bounds`
- `configure_active_work_area`

Target module:

- `src/plotter_backend/geometry/work_area.py`

DoD:

1. monolith wrappers preserve global `ACTIVE_WORK_AREA_BOUNDS` behavior;
2. direct module tests cover format/anchor validation and oversize-sheet clamp behavior;
3. full lint + unit + pytest gates remain green.

#### G5.11 Next M3 extraction slice (polyline translation helper)

Status:

- `done` (`translate_polylines` extracted into `geometry/polyline.py` with compatibility wrapper and direct tests).

Scope:

- `translate_polylines`

Target module:

- `src/plotter_backend/geometry/polyline.py`

DoD:

1. wrapper in monolith preserves call signature;
2. direct module test covers non-zero shift and zero-shift branch;
3. full lint + unit + pytest gates remain green.

---

### Stage G6 - Final release readiness gate

Run only after G1+G2+G3+G4 are complete.

Checklist:

1. complete `RELEASE_CHECKLIST.md` sections 1..8;
2. ensure CI on `main` is green;
3. ensure rollback artifacts and owner are set;
4. tag release and freeze plan state.

Exit criteria:

- no unchecked P0 items;
- release checklist fully marked and evidence-backed.

## 1. Purpose of this file

This file is the single execution plan for improving, stabilizing, testing, and releasing the project.  
It is written as an actionable checklist for day-to-day implementation.

The plan is split into phases. Each phase contains:

- goals;
- concrete tasks;
- commands;
- expected artifacts;
- acceptance criteria (Definition of Done for the phase).

## Progress snapshot

- `M1` CI gates: in progress (workflow added, branch protection checklist added).
- `M2` Coverage growth: in progress.
- `M3` Backend modularization: started (CAD conversion extracted into `src/plotter_backend/converters/cad_converter.py` with compatibility wrappers in monolith).
- `M4` Error model: started (explicit exception hierarchy introduced and applied in CAD converter module).
- `M7` Release hardening docs: started (release checklist, semver policy, and release notes template added).
- Repository sync:
  - latest push to `origin/main`: commit `3e699a3` (2026-03-04).
  - local follow-up changes are prepared and not pushed yet.
- Latest verification gate:
  - `ruff`: pass;
  - `unittest`: pass (`272` tests, `4` skipped);
  - `pytest`: pass (`268` passed, `3` skipped, `1` deselected);
  - `build_windows.ps1`: pass.
  - `validate_portable.ps1`: pass (local portable smoke).
- Additional backend extraction completed:
  - `word_to_pdf` and Word font helpers moved to `src/plotter_backend/converters/word_converter.py` with wrapper compatibility;
  - `pdf_to_svg` extraction completed in `src/plotter_backend/converters/pdf_converter.py`:
    - command generation;
    - generated SVG selection;
    - converter export orchestration;
    - converter scoring and best-candidate selection.
  - `grbl_send_manual_commands` moved to `src/plotter_backend/machine/manual_commands.py` with compatibility wrapper.
  - `send_to_grbl` stack moved to `src/plotter_backend/machine/grbl_sender.py`:
    - sender invocation (inline/subprocess);
    - auto-resume nearest-line lookup;
    - resume G-code file generation.
  - G-code summary metrics moved to `src/plotter_backend/gcode/stats.py` with compatibility wrapper in monolith.
  - `make_final_with_preamble` moved to `src/plotter_backend/gcode/finalize.py` with compatibility wrapper.
  - penlift postprocess command runner moved to `src/plotter_backend/gcode/penlift.py` with compatibility wrapper.
  - draw-bounds parser (`_gcode_draw_bounds` helpers) moved to `src/plotter_backend/gcode/bounds.py` with compatibility wrappers.
  - preflight validator moved to `src/plotter_backend/gcode/preflight.py` with compatibility wrapper.
  - polyline geometry primitives moved to `src/plotter_backend/geometry/polyline.py` with compatibility wrappers in monolith:
    - `points_distance`
    - `polyline_length`
    - `total_draw_length_mm`
    - `bounds_polylines`
    - `translate_polylines`
  - geometry transform primitives moved to `src/plotter_backend/geometry/transform.py` with compatibility wrappers in monolith:
    - `mat_mul`
    - `mat_apply`
    - `parse_transform`
    - `parse_points`
    - `transform_points`
  - geometry simplify primitives moved to `src/plotter_backend/geometry/simplify.py` with compatibility wrappers in monolith:
    - `point_line_distance`
    - `path_is_closed`
    - `rdp_simplify_open`
    - `rdp_simplify_polyline`
    - `simplify_polyline`
  - geometry arc-fit primitives moved to `src/plotter_backend/geometry/arc_fit.py` with compatibility wrappers in monolith:
    - `solve_3x3`
    - `fit_circle_kasa`
    - `unwrap_angles`
    - `polyline_is_near_line`
    - `polyline_fit_arc`
    - `arc_extents_xy`
  - geometry hatching primitives moved to `src/plotter_backend/geometry/hatching.py` with compatibility wrappers in monolith:
    - `polygon_area`
    - `polygon_bbox`
    - `rotate_point`
    - `rotate_polyline`
    - `intersects_for_scanline`
    - `should_hatch_polygon`
    - `hatch_polygon`
  - geometry clipping primitives moved to `src/plotter_backend/geometry/clipping.py` with compatibility wrappers in monolith:
    - `point_in_rect`
    - `clip_segment_to_rect`
    - `clip_polylines_to_rect`
  - geometry sheet-tiling primitives moved to `src/plotter_backend/geometry/sheet_tiling.py` with compatibility wrappers in monolith:
    - `plan_tiled_passes_for_sheet`
    - `resolve_sheet_size_mm`
    - `tile_window_start`
    - `compute_pass_shift`
  - geometry SVG path primitives moved to `src/plotter_backend/geometry/svg_path.py` with compatibility wrappers in monolith:
    - `parse_path_tokens`
    - `cubic_approx`
    - `quadratic_approx`
    - `arc_to_polyline`
  - geometry path-processing core primitives moved to `src/plotter_backend/geometry/path_processing.py` with compatibility wrappers in monolith:
    - `bounds_path_items`
    - `normalize_path_units_to_page`
    - `poly_inside_bbox`
    - `filter_outer_frame_path_items`
    - `clip_path_items_to_rect`
    - `clip_to_content_area`
  - fit-to-work-area helper moved to `src/plotter_backend/geometry/fitting.py` with compatibility wrapper in monolith:
    - `fit_polylines_to_area`
  - work-area helpers moved to `src/plotter_backend/geometry/work_area.py` with compatibility wrappers in monolith:
    - `base_work_area_bounds`
    - `work_area_bounds`
    - `configure_active_work_area`
- Structured error propagation improved:
  - `run_pipeline` now includes exception class in failure messages;
  - protocol Method3 Word conversion errors now include exception class.
  - frame/calibration/wear-test pipelines and GUI background workers now use normalized typed error mapping.
  - `pdf_to_svg` now raises typed conversion/dependency errors for core failure branches.
  - conversion/machine slices now return typed dependency/transport error classes in fallback branches (`ToolDependencyError`/`SerialTransportError` formatting).
  - protocol manual/emergency control paths now map backend exceptions to normalized user-facing typed messages.
  - penlift postprocess failures are now raised as typed `ConversionError` in extracted `gcode/penlift.py`.
  - dependency discovery helpers now raise typed `ToolDependencyError` (`find_inkscape`, `find_pdftocairo`, `find_pdftotext`).
  - sender runtime/dependency branches in `machine/grbl_sender.py` now raise typed `ToolDependencyError`/`SerialTransportError` instead of generic `RuntimeError` in key failure paths.
  - CAD COM/PrintJob branches in `converters/cad_converter.py` now raise typed `ToolDependencyError`/`ConversionError` in key failure paths.
  - GRBL wait/position helpers in monolith bridge (`grbl_wait_for_idle`, `grbl_get_wpos_xyz`) now raise typed `SerialTransportError` instead of generic runtime errors.
- Multi-page sheet-swap control implemented in GUI draw path:
  - protocol all-pages Method3 draw now supports per-page pause callback;
  - controller emits `sheet_swap_confirmation_requested` and blocks until user response;
  - UI confirms sheet replacement between pages with continue/cancel handling.
  - safety hardening: protocol now rejects multi-page hardware draw when sheet-swap callback is missing
    (prevents unsafe silent auto-continue).
- Method3 centerline reliability improved for headless environments:
  - `autotrace` PBM input now has no hard Pillow dependency;
  - direct PBM binary writer fallback added when `PIL.Image` is unavailable.
- Method3 vector micro-artifact cleanup improved:
  - micro-segment pruning added before Method3 SVG write (`min_seg_mm=0.08`);
  - acceptance re-check shows tiny-segment ratio drop across tested pages.
- PDF handwriting acceptance automation added:
  - script: `scripts/run_pdf_handwriting_acceptance.py`;
  - stores per-page artifacts (`.svg/.pdf/.nc`) and JSON report;
  - reports duplicate/tiny segment ratios with configurable quality gates;
  - supports optional baseline comparison report (`--baseline-report`) with per-page metric deltas;
  - executed on Russian UFN articles:
    - `data/acceptance/r232a.pdf`: pages `1..6`, `6/6` successful previews;
    - `data/acceptance/r238e.pdf`: pages `1..2`, `2/2` successful previews.
  - post-modularization regression re-check (2026-03-05, `v27`) completed:
    - `_tmp/acceptance/r232a_regress_2026-03-05_v27/handwriting_acceptance_report.json` (`6/6` accepted);
    - `_tmp/acceptance/r238e_regress_2026-03-05_v27/handwriting_acceptance_report.json` (`2/2` accepted);
    - baseline deltas for duplicate/tiny/short ratios remain `0.0` on matched pages.
- Hardware sheet-swap validation (`G2`) completed:
  - continue path (`>=2` pauses) and cancel-on-first-pause path validated on real machine;
  - evidence report: `_tmp/hw/g2/g2_pause_validation_report.json`.
- Operation correlation and diagnostics (initial implementation):
  - `OperationContext.emit_log` now prefixes logs with `op_id`;
  - `SerialWorker` writes per-operation JSON reports to `_tmp/diagnostics/<op_id>.json`.
- Added error-mapping tests:
  - backend error formatter and pipeline mapping (`tests/test_backend_error_mapping.py`);
  - protocol serial probe + manual/emergency exception-class mapping (`tests/test_protocol_control.py`).
  - converter/machine typed message branches (`tests/test_pdf_converter_module.py`, `tests/test_machine_manual_commands_module.py`).
- Deterministic golden G-code checks added (preamble/trailer tokens, finite coordinates, in-area bounds).
- Local portable build validation completed with checksums:
  - see `RELEASE_VALIDATION_LOG_2026-03-04.md`.
- Portable smoke validator added:
  - `validate_portable.ps1` (zip extract + executable startup smoke).
  - wired into CI `build-smoke-windows` job.
- Branch protection automation added:
  - `set_branch_protection.ps1` (GitHub API helper; requires `GITHUB_TOKEN`).
- Rollback runbook added: `ROLLBACK_GUIDE.md`.
- Versioned known-good config snapshot captured:
  - `config/snapshots/axis_profile.2026-03-04.known-good.json`.
- Added in test suite:
  - controller utilities tests;
  - controller lifecycle tests (ports, operation states, enqueue paths);
  - protocol draw/preview path tests;
  - integration dry-run tests for SVG/PDF/DOCX;
  - CAD fallback behavior test with mocks.
  - machine sender module tests (`tests/test_grbl_sender_module.py`).
  - gcode stats module tests (`tests/test_gcode_stats_module.py`).
  - gcode finalize/penlift/bounds module tests (`tests/test_gcode_finalize_module.py`, `tests/test_gcode_penlift_module.py`, `tests/test_gcode_bounds_module.py`).
  - backend dependency discovery tests (`tests/test_backend_dependency_discovery.py`).
  - gcode preflight module tests (`tests/test_gcode_preflight_module.py`).
  - protocol utility tests (`tests/test_protocol_utilities.py`).
  - serial worker lifecycle/cancel path tests (`tests/test_serial_worker_diagnostics.py` extended).
  - autotrace centerline fallback test without Pillow (`tests/test_backend_geometry.py`).
  - sender typed-failure branches (`tests/test_grbl_sender_module.py`: missing sender, sender rc failure, stdout missing, popen failure).
  - CAD primary-failure error-class propagation branch (`tests/test_cad_converter_module.py`).
  - backend bridge + Method3 helper coverage pack (`tests/test_protocol_backend_bridge.py`).
  - acceptance script comparison helper tests (`tests/test_pdf_acceptance_script_module.py`).
  - GRBL helper typed-error tests for timeout/serial-open/missing-position branches (`tests/test_backend_error_mapping.py`).
  - headless MainWindow UI reliability tests (connect/disconnect locks, preview/draw dispatch, cancel-stop path, log drawer unread counter) (`tests/test_main_window_headless.py`).
  - direct polyline geometry module tests (`tests/test_geometry_polyline_module.py`).
  - direct geometry transform module tests (`tests/test_geometry_transform_module.py`).
  - direct geometry simplify module tests (`tests/test_geometry_simplify_module.py`).
  - direct geometry arc-fit module tests (`tests/test_geometry_arc_fit_module.py`).
  - direct geometry hatching module tests (`tests/test_geometry_hatching_module.py`).
  - direct geometry clipping module tests (`tests/test_geometry_clipping_module.py`).
  - direct geometry sheet-tiling module tests (`tests/test_geometry_sheet_tiling_module.py`).
  - direct geometry SVG path module tests (`tests/test_geometry_svg_path_module.py`).
  - direct geometry path-processing module tests (`tests/test_geometry_path_processing_module.py`).
  - direct geometry fitting module tests (`tests/test_geometry_fitting_module.py`).
  - direct geometry work-area module tests (`tests/test_geometry_work_area_module.py`).
- Pytest environment markers introduced:
  - `word_required`
  - `kompas_required`
  - `hardware_required`
  - default run excludes these markers unless explicitly requested.
- Current local coverage (`src/* + plotter_studio/*`): ~42% (latest local `coverage report --include "src/*,plotter_studio/*"`).
  - baseline includes newly extracted backend modules (`machine/grbl_sender.py`, `gcode/stats.py`, `gcode/finalize.py`, `gcode/penlift.py`, `gcode/bounds.py`), so aggregate percentage is stricter than prior snapshot.
- Current local coverage for `plotter_controller.py`: ~68%.
- Current local coverage for `protocol.py`: ~76%.
- Current local coverage for `serial_worker.py`: ~62%.

---

## 2. Current baseline (already verified)

Status at current revision:

- repository is buildable on Windows;
- `ruff` issues fixed to zero;
- unit tests are green;
- packaging is green;
- DOCX pipeline issue with busy Word COM was fixed (retry + isolated Word instance).

Validated commands:

```powershell
.\.venv\Scripts\ruff.exe check src plotter_studio tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Artifacts currently produced by build:

- `dist\PlotterStudio.exe`
- `dist\PlotterStudio-portable.zip`

---

## 3. Global goals (target state)

1. Stable desktop app with predictable behavior for `PDF/SVG/DOCX/FRW/CDW`.
2. Repeatable quality gates in CI (`lint + tests + coverage + build smoke`).
3. Decoupled backend architecture (reduce risk from monolith).
4. High confidence test matrix:
   - unit,
   - integration,
   - UI,
   - hardware regression.
5. Reliable release process with clear rollback path.

---

## 4. Working model

## 4.1 Branch strategy

- `main` for stable releases.
- feature branches:
  - `feat/...`
  - `fix/...`
  - `refactor/...`
  - `test/...`
- pull request required for merge.

## 4.2 Commit strategy

- small atomic commits;
- each commit keeps tests passing;
- commit message format:
  - `fix: ...`
  - `feat: ...`
  - `refactor: ...`
  - `test: ...`
  - `ci: ...`

## 4.3 Daily loop

1. Pull latest.
2. Run fast checks.
3. Implement one scoped task.
4. Run relevant tests.
5. Run full gate before merge.

Fast checks:

```powershell
.\.venv\Scripts\ruff.exe check src plotter_studio tests
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 5. Phase roadmap

## Phase M1 - CI and mandatory quality gates (priority: P0)

Target duration: 2-4 days.

### Tasks

- [x] Add `.github/workflows/ci.yml`.
- [x] Add jobs:
  - lint job (`ruff`);
  - tests job (`unittest + pytest`);
  - optional coverage job (`coverage report`);
  - build smoke job (`build_windows.ps1` on Windows runner).
- [x] Cache pip dependencies in CI.
- [x] Upload build artifact (`PlotterStudio.exe` or zip) from CI smoke job.
- [ ] Make CI required for PR merge (manual GitHub branch protection step required).

### Suggested CI command steps

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest ruff coverage pyinstaller
.\.venv\Scripts\ruff.exe check src plotter_studio tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m pytest -q
```

### Acceptance criteria

- every PR runs CI automatically;
- failed lint/test blocks merge;
- build smoke produces artifacts.

---

## Phase M2 - Coverage growth on critical modules (priority: P0)

Target duration: 1-2 weeks.

### Current weak spots

- `plotter_studio/core/plotter_controller.py` coverage is low.
- `plotter_studio/core/protocol.py` coverage is moderate but insufficient.
- `src/plotter_pdf_drawer.py` is broad and undercovered.

### Tasks

- [x] Add controller tests:
  - port selection logic;
  - operation state transitions;
  - preview path extraction;
  - busy/progress signaling.
- [x] Add protocol tests:
  - draw/preview mode flags;
  - sheet/pass configuration;
  - fallback behaviors;
  - error propagation.
- [x] Add backend integration dry-run tests:
  - SVG -> NC;
  - PDF -> NC;
  - DOCX -> NC (Word available case);
  - CAD fallback behavior with mocks.
- [x] Add deterministic golden checks for key generated gcode properties.

### Coverage targets

- `plotter_controller.py` >= 50%;
- `protocol.py` >= 60%;
- backend non-UI coverage trend upward every sprint.

### Acceptance criteria

- new tests are deterministic;
- no flakiness in 5 repeated local runs;
- coverage baseline documented in CI logs.

---

## Phase M3 - Backend modularization (priority: P0/P1)

Target duration: 2-4 weeks.

### Objective

Reduce risk and complexity by splitting `src/plotter_pdf_drawer.py` into modules without behavior regression.

Current status:

- initial conversion slice completed (`frw_to_pdf` + CAD helper logic moved to `cad_converter.py`);
- `word_to_pdf` + Word font helpers moved to `word_converter.py`;
- `pdf_to_svg` orchestration moved to `pdf_converter.py` (export collection, scoring, and best converter selection);
- `grbl_send_manual_commands` moved to `machine/manual_commands.py`;
- `send_to_grbl` + auto-resume helpers moved to `machine/grbl_sender.py`;
- `summarize_gcode_file` moved to `gcode/stats.py`;
- `make_final_with_preamble` moved to `gcode/finalize.py`;
- penlift postprocess runner moved to `gcode/penlift.py`;
- preflight draw-bounds analyzer helpers moved to `gcode/bounds.py`;
- `preflight_check_gcode` moved to `gcode/preflight.py`;
- legacy public entrypoints preserved in `plotter_pdf_drawer.py` via wrappers.

### Proposed target package structure

`src/plotter_backend/`

- `config.py` - runtime config dataclasses and defaults;
- `logging_utils.py` - safe logging helpers;
- `converters/`
  - `pdf_converter.py`
  - `word_converter.py`
  - `cad_converter.py`
- `geometry/`
  - `svg_parse.py`
  - `path_processing.py`
  - `hatching.py`
  - `centerline.py`
- `gcode/`
  - `writer.py`
  - `penlift.py`
  - `stats.py`
- `machine/`
  - `serial_comm.py`
  - `grbl_sender.py`
  - `manual_commands.py`
- `pipeline/`
  - `draw_pipeline.py`
  - `preview_pipeline.py`
  - `wear_test_pipeline.py`

### Migration rules

- [ ] Move code in small slices.
- [ ] Keep public entrypoints stable while migrating.
- [ ] Preserve old imports via compatibility wrappers until full migration completes.
- [ ] After each move:
  - run lint;
  - run unit tests;
  - run at least one end-to-end dry-run sample.

### Suggested slicing order

1. logging/config constants
2. conversion functions (`word_to_pdf`, `pdf_to_svg`, `frw_to_pdf`)
3. gcode writer + stats
4. penlift logic
5. geometry extraction/transforms
6. high-level pipeline assembly

### Acceptance criteria

- backend file size significantly reduced;
- moved modules have direct unit tests;
- no behavior change in known regression samples.

---

## Phase M4 - Error model and diagnostics (priority: P1)

Target duration: 1 week.

### Tasks

- [x] Define explicit exceptions:
  - `BackendError`
  - `ConversionError`
  - `ToolDependencyError`
  - `SerialTransportError`
  - `PipelineValidationError`
- [ ] Replace broad opaque `"Error: ..."` messages with structured errors.
- [ ] Standardize user-facing vs internal log messages.
- [x] Add operation correlation id in logs.
- [x] Save per-run diagnostic report JSON in app data.

### Acceptance criteria

- error source can be identified by message class and context;
- support/debugging requires fewer manual reproductions.

---

## Phase M5 - UI reliability and integration tests (priority: P1)

Target duration: 1-2 weeks.

### Tasks

- [ ] Add pytest-qt based tests for main user flows.
- [ ] Cover signal-slot chains:
  - connect/disconnect;
  - preview/draw requests;
  - cancel operation;
  - log drawer state persistence.
- [ ] Add tests for settings persistence and restoration.
- [ ] Add tests for invalid file paths and unsupported extensions.

### Acceptance criteria

- UI smoke suite passes headless in CI on Windows;
- no crash on core UI operations.

---

## Phase M6 - Hardware validation protocol (priority: P1/P2)

Target duration: ongoing (per release candidate).

### Hardware lab assumptions

- GRBL controller connected over COM.
- Test paper and pen/pencil setup fixed.
- Known machine profile in `config\axis_profile.json`.

### Hardware test matrix (minimal)

- [ ] HW-001 Connect/disconnect repeatedly (20 cycles).
- [ ] HW-002 Draw frame and verify bounds.
- [ ] HW-003 4-corner calibration repeatability.
- [ ] HW-004 Emergency stop during active draw.
- [ ] HW-005 Recovery and resume behavior.
- [ ] HW-006 DOCX handwriting run.
- [ ] HW-007 PDF technical drawing exact geometry run.
- [ ] HW-008 Long run soak test (>= 60 min).

### Acceptance criteria

- no unhandled crash during protocol;
- no out-of-bounds movement;
- emergency stop always responds;
- post-run motors release behavior consistent.

---

## Phase M7 - Release process hardening (priority: P1)

Target duration: 3-5 days.

### Tasks

- [x] Introduce release checklist file.
- [x] Introduce semantic versioning policy.
- [x] Add release notes template.
- [ ] Validate portable package on clean Windows machine.
- [x] Keep rollback guide:
  - previous stable exe;
  - known-good config snapshot.

### Acceptance criteria

- release can be reproduced from tag;
- rollback can be done in less than 15 minutes.

---

## 6. Detailed test plan

## 6.1 Unit tests

Focus:

- deterministic pure logic;
- geometry math;
- settings normalization;
- protocol option mapping.

Rules:

- no hard dependence on local machine state;
- no network;
- no hardware;
- no GUI rendering unless explicitly UI test.

## 6.2 Integration tests

Focus:

- end-to-end pipeline in `send_to_plotter=False` mode;
- artifact creation and validation;
- conversion chains.

Suggested integration fixture inputs:

- `tests/fixtures/simple_rect.svg`
- `tests/fixtures/multi_text.pdf`
- `tests/fixtures/docx/simple.docx` (optional by environment marker)
- `tests/fixtures/cad/sample.frw` (mock conversion if CAD software unavailable)

## 6.3 Environment-conditional tests

Introduce markers:

- `@pytest.mark.word_required`
- `@pytest.mark.kompas_required`
- `@pytest.mark.hardware_required`

Run strategy:

- CI default excludes hardware and office-required tests.
- local pre-release run includes all available markers.

## 6.4 Golden tests for gcode

Validate:

- generated file exists;
- preamble/trailer required commands present;
- bounds inside configured work area;
- no NaN/inf coordinates;
- expected command ratio (`G0/G1/G2/G3`) within tolerance.

---

## 7. CI/CD implementation details

## 7.1 Required workflows

- `ci.yml` (required for every PR)
- `release.yml` (tag-triggered)

## 7.2 CI jobs

1. `lint`
2. `tests`
3. `coverage-report`
4. `build-smoke-windows`

## 7.3 Suggested artifacts retention

- PR builds: 7 days.
- release builds: 90 days.

## 7.4 Fail-fast rules

- lint failure stops pipeline.
- test failure stops pipeline.
- build smoke failure blocks merge if branch protection is active.

---

## 8. Refactoring guardrails

1. No large rewrites without intermediate checkpoints.
2. Keep behavior compatibility while splitting modules.
3. Any significant refactor must come with tests first or alongside.
4. Keep feature flags for risky behavioral changes.
5. Avoid silent fallback that hides critical operational failures.

---

## 9. Operational runbooks

## 9.1 Local full verification run

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest ruff coverage pyinstaller
.\.venv\Scripts\ruff.exe check src plotter_studio tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

## 9.2 Quick smoke run without hardware

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
```

## 9.3 Regression run before release

- run full CI locally;
- run integration dry-run samples;
- run hardware protocol M6 minimal matrix;
- verify `dist\PlotterStudio.exe` launch.

---

## 10. Risk register

## R1. External tools variability

Risk: Inkscape/Poppler/Office/KOMPAS behavior differs across machines.  
Mitigation:

- preflight tool checks at startup;
- clear diagnostics for missing dependencies;
- environment-specific tests.

## R2. Monolith regression during refactor

Risk: behavior drift while splitting backend.  
Mitigation:

- golden tests;
- staged extraction;
- compatibility wrappers.

## R3. Hardware edge-case failures

Risk: serial interruptions, emergency stop race conditions.  
Mitigation:

- robust serial retry/timeout handling;
- mandatory hardware protocol for release candidates.

## R4. Silent exception swallowing

Risk: hidden production issues due to broad `except Exception`.  
Mitigation:

- reduce broad catches in critical code;
- enforce explicit exception classes.

---

## 11. Definition of Done (project-level)

A task is done only if:

- code implemented;
- lint passes;
- relevant tests added/updated and passing;
- no regressions in existing test suite;
- docs updated if behavior changed.

A milestone is done only if:

- all milestone acceptance criteria are met;
- artifacts exist and are verifiable;
- risks and open issues are explicitly listed.

---

## 12. Immediate backlog (next actions in order)

### Recently completed

1. [x] CI workflow (`lint/tests/coverage/build-smoke`) and artifact upload.
2. [x] Controller/protocol/integration dry-run tests + environment markers.
3. [x] Converter extraction slices: `cad_converter`, `word_converter`, `pdf_converter` (`pdf_to_svg` orchestration included).
4. [x] Structured exception hierarchy and first pass of typed error mapping.
5. [x] Golden G-code checks, operation log correlation id, per-operation diagnostics JSON.
6. [x] Release docs, rollback guide, local portable smoke validation, known-good axis profile snapshot.
7. [x] M4 incremental pass: typed error normalization extended across converter/machine modules and protocol manual-control boundaries.
8. [x] M3 incremental pass: `send_to_grbl` sender/resume stack extracted into `src/plotter_backend/machine/grbl_sender.py` with compatibility wrappers.
9. [x] M3 incremental pass: G-code summary metrics extracted into `src/plotter_backend/gcode/stats.py` with compatibility wrapper.
10. [x] M3 incremental pass: `make_final_with_preamble` + penlift command runner extracted into `src/plotter_backend/gcode/finalize.py` and `src/plotter_backend/gcode/penlift.py`.
11. [x] M3 incremental pass: preflight draw-bounds parser extracted into `src/plotter_backend/gcode/bounds.py` with compatibility wrappers.
12. [x] M4 incremental pass: external tool discovery (`find_inkscape/find_pdftocairo/find_pdftotext`) converted to typed `ToolDependencyError` with dedicated tests.
13. [x] M3 incremental pass: preflight validator extracted into `src/plotter_backend/gcode/preflight.py` with compatibility wrapper and direct module tests.
14. [x] Confidence pass: `serial_worker.py` coverage significantly increased (lifecycle/cancel tests), protocol utility tests added.
15. [x] Confidence pass: protocol low-level G-code utility tests expanded (coverage moved to ~50%).
16. [x] M3 incremental pass: polyline geometry utilities extracted to `src/plotter_backend/geometry/polyline.py` with compatibility wrappers and direct module tests.
17. [x] SO-3: headless MainWindow UI reliability tests added and validated in 5 repeated runs.
18. [x] G5.1 / M3 incremental pass: geometry transform utilities extracted to `src/plotter_backend/geometry/transform.py` with compatibility wrappers and direct module tests.
19. [x] G5.2 (partial) / M3 incremental pass: simplify/RDP geometry utilities extracted to `src/plotter_backend/geometry/simplify.py` with compatibility wrappers and direct module tests.
20. [x] G5.2 / M3 incremental pass completed: arc-fit geometry utilities extracted to `src/plotter_backend/geometry/arc_fit.py` with compatibility wrappers and direct module tests.
21. [x] G5.3 coverage maintenance completed: focused snapshot refreshed (`protocol` 76%, `plotter_controller` 68%, `serial_worker` 62%).
22. [x] M3 incremental follow-up: arc bounds helper `arc_extents_xy` moved to `geometry/arc_fit.py` with compatibility wrapper and tests.
23. [x] M3 incremental follow-up: hatching/polygon helpers moved to `geometry/hatching.py` with compatibility wrappers and direct module tests.
24. [x] M3 incremental follow-up: clipping helpers moved to `geometry/clipping.py` with compatibility wrappers and direct module tests.
25. [x] M3 incremental follow-up: `clamp_to_work_area` aligned to shared clipping helper (`clamp_to_rect`) with dedicated module test coverage.
26. [x] M3 incremental follow-up: sheet-tiling helpers moved to `geometry/sheet_tiling.py` with compatibility wrappers and direct module tests.
27. [x] M3 incremental follow-up: SVG path tokenization/curve approximation helpers moved to `geometry/svg_path.py` with compatibility wrappers and direct module tests.
28. [x] M3 incremental follow-up: path-processing core helpers moved to `geometry/path_processing.py` with compatibility wrappers and direct module tests.
29. [x] M3 incremental follow-up: outer-frame detection helper moved to `geometry/path_processing.py` with compatibility wrapper and direct branch tests.
30. [x] M3 incremental follow-up: `clip_path_items_to_rect` moved to `geometry/path_processing.py` with compatibility wrapper and direct clipping tests.
31. [x] M3 incremental follow-up: `clip_to_content_area` moved to `geometry/path_processing.py` with compatibility wrapper and direct decision-branch tests.
32. [x] M3 incremental follow-up: `fit_polylines_to_area` moved to `geometry/fitting.py` with compatibility wrapper and direct module tests.
33. [x] M3 incremental follow-up: work-area bounds/config helpers moved to `geometry/work_area.py` with compatibility wrappers and direct module tests.
34. [x] M3 incremental follow-up: `translate_polylines` moved to `geometry/polyline.py` with compatibility wrapper and direct module tests.
35. [x] Safety hardening: `run_draw` now requires sheet-swap callback in multi-page hardware mode (prevents silent auto-continue).
36. [x] G2 hardware validation completed with evidence report (`_tmp/hw/g2/g2_pause_validation_report.json`).

### Current execution order

Reference: execute detailed stages `G0..G6` from section `0.2`.

1. [ ] `G1` HW acceptance for handwriting quality (`r232a` 1..6 + `r238e` 1..2) with photo/scan evidence.
2. [ ] `G3` Finalize M1: enable required GitHub branch protection checks on `main`.
3. [ ] `G4` Finalize M7: clean-machine portable validation with evidence in `RELEASE_CHECKLIST.md`.
4. [ ] `G5` Continue M3 tail while hardware blockers are pending (active substep: next extraction slice after `polyline/transform/simplify/arc_fit/hatching/clipping/sheet_tiling/svg_path/path_processing/fitting/work_area`).

### Open prerequisites

1. GitHub branch protection update requires a token with repository admin permissions.
2. Clean-machine validation requires a separate fresh Windows VM/host (not current dev environment).

---

## 13. Progress tracking template

Use this block at the top of PR description:

```text
Milestone:
Task:
Status: in_progress | done
Checks run:
- ruff: pass/fail
- unittest: pass/fail
- pytest: pass/fail
- build: pass/fail
Risk notes:
Rollback plan:
```

---

## 14. Notes for maintainers

- Keep this file in project root and update after every meaningful milestone.
- Do not keep private planning details outside repository if they impact engineering decisions.
- If scope changes, update phases and acceptance criteria before implementation.
