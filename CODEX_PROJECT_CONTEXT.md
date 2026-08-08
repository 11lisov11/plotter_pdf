# Codex Project Context: plotter_pdf

This is the single canonical Codex context file for `plotter_pdf`.

Do not commit restored raw Codex rollouts, chat digests, base64 images, local
SQLite dumps, or multiple `.codex_*` memory files to GitHub. Raw histories belong
to the local Codex app storage. GitHub should keep only this compact project
context so the project has one clear source of truth.

## Project

- Current working project root: `C:\plotter_pdf`.
- Clean GitHub mirror used for repository updates: `C:\plotter_pdf_latest`.
- Supported workflows are CLI/headless and the current PySide6 Windows GUI.
- Keep drawing generation in the existing production engines; GUI/layout work
  must not silently change frame, stamp, text, scale, or A3 pass rules.
- Main entry points:
  - `main.py`
  - `src/plotter_pdf_drawer.py`
  - `src/send_grbl_file.py`
  - `plotter_studio/core/protocol.py`
  - `plotter_studio/core/serial_worker.py`
- Treat the user worktree as potentially dirty. Do not revert generated/user
  files unless the user explicitly asks.

## Codex Dialog Rule

- Keep one active Codex dialog for this project.
- Archive older restored Plotter PDF dialogs instead of attaching several old
  threads to the same project.
- If historical context is needed, summarize it here instead of committing raw
  restored rollouts or huge chat digests.
- Previous restored digest files were intentionally removed:
  - `.codex_plotter_history_digest.md`
  - `.codex_plotter_project_memory.md`

## Machine Rules

Two machine profiles are production inputs and must remain separate.

### A4 desktop plotter

- Default USB port: `COM6`.
- Common Bluetooth port: `COM11`.
- Baud: `115200`.
- Controller: GRBL/CH340 USB serial.
- Pen lift method: Z axis only, not `M3/M5`, not `M280`.
- Canonical constants from `config/PLOTTER_CONTROL_RULES.md`:
  - `Z_UP = 0.0`
  - `Z_DOWN = 11.9`
  - work area `X: 0..180`
  - work area `Y: -280..0`
  - production offset `WORK_OFFSET_Y_MM = -5.0`
- Direction lock:
  - `X+` right
  - `X-` left
  - `Y+` down
  - `Y-` up
- Origin:
  - `0,0` is the left-lower corner of the inner work area.
  - After manually placing the carriage there, run `G92 X0 Y0` and `G92 Z0`.
  - `G92` changes coordinates only; it does not move the machine.
- Preamble before real drawing:
  - `$X`
  - `$1=255`
  - `G21`
  - `G90`
  - `G92 Z0`
  - `G92 X0 Y0` after physical placement
- End jobs with `M5`, `$1=0`, optionally `$SLP` to release/cool motors.

### A2 CoreXY plotter

- Profile: `a2_corexy`.
- Controller: FluidNC 3.9.x over GRBL-compatible serial protocol.
- Confirmed work area: `X: 0..390`, `Y: 0..580` mm.
- Origin: left-lower corner of the confirmed work area.
- Direction lock: `X+` right, `Y+` up.
- PDF source geometry is mirrored once on Y by the machine profile. Do not add
  another manual mirror unless a preview explicitly proves it is required.
- Physical A2 paper is `420x594` mm, larger than the confirmed work area. Keep
  geometry at `1:1` and clip only the inactive outer paper bands.
- Valid full-size calibration layouts: `a2`, `a2_2xa3`, `a2_4xa4`.
- Eight full-size A4 sheets do not fit on A2 and must not be offered as a
  production layout.

## Calibration And Drawing

- Corner calibration:
  - `python src\plotter_pdf_drawer.py --calibrate-corners`
  - or `python main.py --calibrate-corners --com COM6`
- Production work frame:
  - left `X=0`
  - right `X=180`
  - bottom `Y=-5`
  - top `Y=-285`
- Do not assume hardware calibration is complete unless the user confirms it.

## A3 Two-Pass Rule

- A3 is split as `2 columns x 1 row`.
- `pass_01`: normal orientation.
- `pass_02`: user physically rotates the sheet by `180 deg`.
- Backend must also rotate `pass_02` geometry by `180 deg` around the active
  area center before clipping/G-code.
- Apply Y translation after rotation. Trust `config/PLOTTER_CONTROL_RULES.md`
  over older README/history notes when values disagree.
- Do not replace this with only horizontal or vertical mirroring.
- Preserve the Method3 hybrid canvas rule: inner drawing stays `1:1`; do not
  reintroduce whole-page shrink-to-work-area for A3.

## Text And Handwriting

- Russian body text must become vector handwritten text, not printed text and
  not raster.
- For Cyrillic paragraph/body text, prefer TTF single-line/centerline routing
  with a handwriting font, usually `Marck Script`.
- For technical drawings, formulas, dimensions, title blocks, and short numeric
  tokens, prefer readable technical/vector text routes.
- Page-level raster fallback is a last resort, not the default.
- Target behavior:
  - body text -> handwritten vector
  - formulas/technical labels/table text -> readable printed/vector route
  - diagrams/tables/line art -> exact vector geometry
  - image-only content -> traced only when needed

## Technical Drawing Optimization

- Do not break exact geometry, frames, dimensions, hatching, clipping, A3 pass
  alignment, or title-block placement.
- Existing improvement targets:
  - reduce pen lifts in text-heavy drawings by at least 35%
  - reduce tiny segments under `0.35 mm` by at least 50%
  - avoid dotted/point-like symbols in title blocks/dimensions
  - layout similarity must not regress more than `0.005`
- Avoid handwriting heuristics on technical drawings unless text is explicitly
  body handwriting content.
- `stitch` previously caused unwanted connecting lines in technical/A3 packages;
  preserve source order where needed.

## Testing

- For code changes, run focused tests first, then broader pytest when geometry
  or backend behavior is touched.
- Useful checks:
  - `python -m py_compile src\plotter_pdf_drawer.py`
  - `python -m pytest -q`
  - targeted tests under `tests/`
  - package comparison artifacts: `report.json`, `summary.csv`,
    `source_vs_gcode_compare.*`, logs
- For real hardware actions, explicitly state COM port, file, line count,
  elapsed time, and release motors at the end.
