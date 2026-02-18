# Plotter Control Rules (No Legacy Ambiguity)

This document is the single source of truth for current machine setup.

## 1) Current machine model

- COM: `COM6` (auto-detect prefers COM6)
- Baud: `115200`
- GRBL connected on serial
- Pen lift method: **Z axis only**
- Main constants:
  - `Z_UP = 0.0`
  - `Z_DOWN = 11.9` (can be tuned, if lines are weak: increase to 11.95/12.0)
  - `WORK_AREA_MIN_X = 0`
  - `WORK_AREA_MAX_X = 180`
  - `WORK_AREA_MIN_Y = -280`
  - `WORK_AREA_MAX_Y = 0`
- Pipeline safety:
  - All geometry is clipped to work area before gcode generation.

## 2) Direction lock (do not flip this)

- `X+` = right
- `X-` = left
- `Y+` = down (toward paper lower edge)
- `Y-` = up (toward top edge)

This mapping is fixed for all commands.

## 3) Origin policy

- `0,0` is the left-lower corner of the inner work area.
- When the carriage is in that physical point, run:
  - `G92 X0 Y0`
  - `G92 Z0` (air position)

`G92` only changes work offset. It does not move the carriage.

## 4) Canonical preamble before drawing

Use exactly:

1. `$X`
2. `$1=255`
3. `G21`
4. `G90`
5. `G92 Z0`

Then:
- `G92 X0 Y0` (after manual placement)
- run file drawing

For safety every drawing job is followed by:

- `M5`
- `$1=0`
- Optional: `$SLP` if you need guaranteed stepper disable/cooling (requires Reset to wake).

This removes holding current from the motors after drawing.

## 5) Work area geometry

- Right edge: `X = 180`
- Left edge: `X = 0`
- Top edge (inner): `Y = -280`
- Bottom edge (inner): `Y = 0`

Preferred drawing frame (left-bottom origin):

1. `G0 X0 Y0`
2. `G1 X180 Y0`
3. `G1 X180 Y-280`
4. `G1 X0 Y-280`
5. `G1 X0 Y0`

## 6) Supported source formats

- `.pdf` via Inkscape conversion
- `.svg` loaded directly

For raster drawings:
- convert or trace to SVG/vector first, otherwise there is nothing to extract as paths.

## 7) Default hatch behavior

- Filled closed regions become hatch fill lines automatically.
- Thin regions are kept as strokes only.
- Useful tuning constants:
  - `FILL_HATCH_SPACING_MM`
  - `FILL_HATCH_ANGLE_DEG`
  - `FILL_HATCH_MIN_AREA_MM2`
  - `FILL_HATCH_MIN_SIDE_MM`

If texture is too dense: reduce spacing and/or increase `FILL_HATCH_MIN_AREA_MM2`.

## 8) Stable frame template (session tested)

```gcode
G21
G90
$X
$1=255
G92 Z0
G0 Z0 F1200
G0 X0.0000 Y0.0000 F2500
G0 Z11.9000 F300
G1 X180.0000 Y0.0000 F1200
G1 X180.0000 Y-280.0000
G1 X0.0000 Y-280.0000
G1 X0.0000 Y0.0000
G0 Z0.0000 F300
M5
$1=0
```

## 9) Recovery when geometry drifts

- Query state: `?`
- If offsets look wrong:
  - re-home by physical placement
  - run preamble from section 4
  - run `G92 X0 Y0` at the chosen corner

## 10) Corner calibration run
- Run: `python src\plotter_pdf_drawer.py --calibrate-corners`
- What it does: 4 corner marks (no enclosing frame) with explicit pen down/up.
- Good when: after physical origin adjustment or after any collision/alignment check.
