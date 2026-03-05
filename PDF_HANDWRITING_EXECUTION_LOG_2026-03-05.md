# PDF Handwriting Execution Log (2026-03-05)

Project root: `C:\plotter_pdf`

## 1. Scope

Acceptance run for requirement:

1. tune on 1 page;
2. verify transferability on +5 pages;
3. monitor double-line risk in handwriting output.

## 2. Input dataset

1. Russian scientific article (UFN):  
   `data/acceptance/r232a.pdf`  
   source URL: `https://www.ufn.ru/ufn2023/ufn2023_2/Russian/r232a.pdf`
2. Additional Russian scientific PDF (UFN):  
   `data/acceptance/r238e.pdf`  
   source URL: `https://www.ufn.ru/ufn2023/ufn2023_8/Russian/r238e.pdf`

## 3. Pipeline command

```powershell
.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py `
  --pdf data\acceptance\r232a.pdf `
  --pages 1,2,3,4,5,6 `
  --out-dir _tmp\acceptance\r232a `
  --quality high `
  --contours always
```

Execution result: `6/6 pages ok`.

Additional cross-PDF run:

```powershell
.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py `
  --pdf data\acceptance\r238e.pdf `
  --pages 1,2 `
  --out-dir _tmp\acceptance\r238e `
  --quality high `
  --contours always
```

Execution result: `2/2 pages ok`.

## 4. Per-page metrics

1. p1: runtime `148.3s`, segments `45199`, duplicate-ratio `0.00088`, draw-length `22.09m`
2. p2: runtime `207.6s`, segments `64551`, duplicate-ratio `0.00033`, draw-length `30.38m`
3. p3: runtime `361.9s`, segments `72177`, duplicate-ratio `0.00019`, draw-length `34.74m`
4. p4: runtime `294.7s`, segments `69766`, duplicate-ratio `0.00022`, draw-length `33.18m`
5. p5: runtime `223.2s`, segments `66413`, duplicate-ratio `0.00044`, draw-length `32.05m`
6. p6: runtime `190.6s`, segments `56062`, duplicate-ratio `0.00043`, draw-length `26.95m`

Cross-PDF metrics (`r238e.pdf`):

1. p1: runtime `302.8s`, segments `47518`, duplicate-ratio `0.00027`, draw-length `22.67m`
2. p2: runtime `206.1s`, segments `38558`, duplicate-ratio `0.00083`, draw-length `20.11m`

## 5. Artifacts

1. report: `_tmp/acceptance/r232a/handwriting_acceptance_report.json`
2. page artifacts:
   - `_tmp/acceptance/r232a/r232a_p1.svg|pdf|nc`
   - `_tmp/acceptance/r232a/r232a_p2.svg|pdf|nc`
   - `_tmp/acceptance/r232a/r232a_p3.svg|pdf|nc`
   - `_tmp/acceptance/r232a/r232a_p4.svg|pdf|nc`
   - `_tmp/acceptance/r232a/r232a_p5.svg|pdf|nc`
   - `_tmp/acceptance/r232a/r232a_p6.svg|pdf|nc`
3. cross-PDF report: `_tmp/acceptance/r238e/handwriting_acceptance_report.json`
4. cross-PDF artifacts:
   - `_tmp/acceptance/r238e/r238e_p1.svg|pdf|nc`
   - `_tmp/acceptance/r238e/r238e_p2.svg|pdf|nc`

## 6. Code changes used by this run

1. Method3 centerline now supports autotrace PBM generation without Pillow fallback breakage:
   - file: `src/plotter_pdf_drawer.py`
2. Added unit test for this fallback:
   - file: `tests/test_backend_geometry.py`
3. Added acceptance automation script:
   - file: `scripts/run_pdf_handwriting_acceptance.py`

## 7. Remaining manual gate

Hardware sign-off is still required for final "exact handwriting quality":

1. print physical pages with real plotter;
2. inspect letters/formulas/graphs visually;
3. attach photos and approve/deny each page;
4. for all-pages draw, validate pause/continue/cancel sheet-swap flow on real device.

## 8. Re-check After Micro-Segment Cleanup

Pipeline change:

1. Method3 now prunes micro-segments before SVG emission (`min_seg_mm=0.08`).

Observed effect on tiny-segment ratio (`<0.12 mm`):

`r232a.pdf`

1. p1: `0.0199 -> 0.00888`
2. p2: `0.0108 -> 0.00281`
3. p3: `0.0092 -> 0.00202`
4. p4: `0.0091 -> 0.00171`
5. p5: `0.0085 -> 0.00232`
6. p6: `0.0095 -> 0.00235`

`r238e.pdf`

1. p1: `0.0157 -> 0.00498`
2. p2: `0.0129 -> 0.00356`

Current duplicate ratio remains low (all pages below `0.001`).

Quality-gate check (`max_duplicate_ratio=0.002`, `max_tiny_ratio=0.015`):

1. `r232a`: `6/6` pages pass.
2. `r238e`: `2/2` pages pass.

## 9. Re-check After Geometry Modularization (v27)

Run date: `2026-03-05`

Commands:

```powershell
.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py `
  --pdf data\acceptance\r232a.pdf `
  --pages 1,2,3,4,5,6 `
  --out-dir _tmp\acceptance\r232a_regress_2026-03-05_v27 `
  --quality high `
  --contours always `
  --max-duplicate-ratio 0.002 `
  --max-tiny-ratio 0.015 `
  --baseline-report _tmp\acceptance\r232a\handwriting_acceptance_report.json

.\.venv\Scripts\python.exe scripts\run_pdf_handwriting_acceptance.py `
  --pdf data\acceptance\r238e.pdf `
  --pages 1,2 `
  --out-dir _tmp\acceptance\r238e_regress_2026-03-05_v27 `
  --quality high `
  --contours always `
  --max-duplicate-ratio 0.002 `
  --max-tiny-ratio 0.015 `
  --baseline-report _tmp\acceptance\r238e\handwriting_acceptance_report.json
```

Result summary:

1. `r232a`: `6/6` pages accepted.
2. `r238e`: `2/2` pages accepted.
3. comparison vs baseline reports:
   - average `duplicate_ratio_delta = 0.0`;
   - average `tiny_ratio_delta = 0.0`;
   - average `short_ratio_delta = 0.0`.

Artifacts:

1. `_tmp/acceptance/r232a_regress_2026-03-05_v27/handwriting_acceptance_report.json`
2. `_tmp/acceptance/r238e_regress_2026-03-05_v27/handwriting_acceptance_report.json`

## 10. Hardware Sheet-Swap Validation (G2) on Real Plotter

Run date: `2026-03-05`

Dataset:

1. `_tmp/hw/g2/pause_test_3p.pdf` (3-page test PDF for pause flow validation).

Execution:

1. Continue scenario: all pages sent with `continue` on pauses.
2. Cancel scenario: operation canceled on first pause.

Results:

1. continue scenario: `ok=true`, pause confirmations observed: `2` (`page 1/3`, `page 2/3`).
2. cancel scenario: `ok=false` with expected message `Canceled during sheet replacement after page 1.`, pause confirmations observed: `1`.
3. no app freeze/crash observed in either scenario.

Evidence:

1. `_tmp/hw/g2/g2_pause_validation_report.json`

## 11. Safety Incident Note (Emergency Stop)

During a later long hardware batch attempt, the operation was interrupted by operator request.

Actions performed:

1. terminated hanging sender Python processes from `.venv`;
2. sent GRBL emergency sequence (`soft reset`, `hold`, `M5`, unlock, motors release);
3. sent safe return commands (`G21`, `G90`, `G0 Z0`, `G0 X0 Y0`);
4. verified controller status: `<Idle|MPos:0.000,0.000,66.750|...>`.

Current state after incident:

1. machine is stopped;
2. pen returned to home XY with safe Z-up position;
3. G1 full physical acceptance (`r232a 1..6`, `r238e 1..2` with photo/scan evidence) remains open and must be re-run in controlled mode.
