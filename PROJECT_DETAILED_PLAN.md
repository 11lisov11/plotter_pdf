# Plotter Studio - Detailed Execution Plan

Updated: 2026-03-04  
Project root: `C:\plotter_pdf`

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
- Additional backend extraction completed:
  - `word_to_pdf` and Word font helpers moved to `src/plotter_backend/converters/word_converter.py` with wrapper compatibility;
  - first safe `pdf_to_svg` slice moved to `src/plotter_backend/converters/pdf_converter.py` (command generation + generated SVG selection helpers).
- Structured error propagation improved:
  - `run_pipeline` now includes exception class in failure messages;
  - protocol Method3 Word conversion errors now include exception class.
- Deterministic golden G-code checks added (preamble/trailer tokens, finite coordinates, in-area bounds).
- Local portable build validation completed with checksums:
  - see `RELEASE_VALIDATION_LOG_2026-03-04.md`.
- Rollback runbook added: `ROLLBACK_GUIDE.md`.
- Added in test suite:
  - controller utilities tests;
  - controller lifecycle tests (ports, operation states, enqueue paths);
  - protocol draw/preview path tests;
  - integration dry-run tests for SVG/PDF/DOCX;
  - CAD fallback behavior test with mocks.
- Pytest environment markers introduced:
  - `word_required`
  - `kompas_required`
  - `hardware_required`
  - default run excludes these markers unless explicitly requested.
- Current local coverage (`src/* + plotter_studio/*`): ~43% (local `coverage report` on 2026-03-04).
- Current local coverage for `plotter_controller.py`: ~60%.
- Current local coverage for `protocol.py`: ~44%.

---

## 2. Current baseline (already verified)

Status at the moment this plan was created:

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
- [ ] Add deterministic golden checks for key generated gcode properties.

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
- [ ] Add operation correlation id in logs.
- [ ] Save per-run diagnostic report JSON in app data.

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

1. [x] Add `ci.yml` and enforce PR gate prerequisites (workflow + branch protection setup guide).
2. [x] Add controller test suite for operation lifecycle.
3. [x] Add protocol test suite for draw/preview paths.
4. [x] Add integration dry-run tests for `SVG/PDF/DOCX` and CAD fallback with mocks.
5. [x] Introduce environment markers for Office/CAD/hardware tests.
6. [x] Start backend extraction: conversion module first (CAD slice completed).
7. [x] Add structured exception hierarchy (defined + initial adoption in CAD converter).
8. [x] Add release checklist and release notes template.

Next practical sequence:

1. [x] Extract `word_to_pdf` logic into `src/plotter_backend/converters/word_converter.py` with wrapper compatibility.
2. [x] Extract `pdf_to_svg` logic into `src/plotter_backend/converters/pdf_converter.py` in incremental safe slices (initial helper slice).
3. [x] Propagate structured backend exceptions to `run_pipeline` and protocol-level user messages (initial surface-level mapping).
4. [x] Add deterministic golden tests for G-code preamble/trailer and bounds checks.
5. [ ] Run portable package validation on a clean Windows environment and finalize rollback runbook evidence.

Current next sequence:

1. [ ] Complete `pdf_to_svg` extraction (converter selection + scoring path) into `pdf_converter.py`.
2. [ ] Propagate structured exceptions across remaining conversion paths and replace broad opaque `"Error: ..."` in critical pipelines.
3. [ ] Perform clean-machine portable package validation and attach evidence to release checklist.
4. [ ] Capture and version a known-good config snapshot for rollback execution readiness.

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
