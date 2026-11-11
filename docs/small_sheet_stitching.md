# A2/A1 on the small plotter

This is a separate downstream tiling mode. Existing A4/A3 builders, their
transforms, and the ordinary sender are not changed. The large plotter is not
used. Preparation never opens a serial port.

## Preparation

```powershell
python scripts/prepare_small_sheet_tiles.py --trial --format A2
python scripts/prepare_small_sheet_tiles.py --pdf "C:/drawings/source.pdf" --format A2
python scripts/prepare_small_sheet_tiles.py --pdf "C:/drawings/source.pdf" --format A1 --page 1
```

PDF input uses the existing small-plotter PDF geometry / OpenGOST single-line
recognizer. Missing glyphs block preparation. The new layer does not trace
letter outlines, scale the source, merge dashed gaps, or rotate/mirror passes.
The PDF page must already have the requested A2/A1 dimensions (1 mm tolerance).
Recognition is unchanged; its existing limitations still apply to scanned PDFs.

The public Python hook is
`src.plotter_backend.geometry.small_sheet_tiling.prepare_stitched_job`.
It accepts polylines in millimeters, top-left origin, X right / Y down.
For external vectorizers, `--source-json` accepts:

```json
{"units":"mm","page_size_mm":[594,420],"polylines":[[[10,10],[580,400]]]}
```

## Layout and registration

- Work field: X 0..180, Y -285..-5 mm. Printed top corresponds to minimum Y.
- Full field overlap: 5 mm; source strokes overlap only 0.3 mm at seams.
- Landscape A2: 4 columns x 2 rows, 8 passes. Landscape A1: 5 x 3, 15 passes.
- Portrait pages are supported without rotation; their pass counts differ.
- Serpentine order. Empty passes are retained so no registration link is lost.
- Each transition has TWO crosses in the shared strip, clear of source ink.
- A pass draws its outgoing crosses only. Incoming crosses are not redrawn.
- If two sufficiently separated blank locations are unavailable, preparation
  fails rather than putting marks over the drawing. Reserve blank strips or
  revise the layout before preparing that source.
- Registration marks are real pen strokes. Use an erasable marking instrument
  or removable registration tabs at the marked blank locations if necessary.
- After drawing, the pen lifts and parks at the NEXT pass's local A position.
  Move the paper so its previous A mark is under the pen. Check B before drawing.
- Do not rotate the paper or manually move the carriage. Keep the same session,
  XY coordinate zero and motor holding state throughout all passes.

`Preview_from_Gcode.pdf` decodes final `.nc` files. Black strokes, including
crosses, come from pen-down G-code. Colored field/overlap guides and labels
are preview annotations, not plotter strokes. Individual pass pages are A4
views of the 180 x 280 mm field, not a request to cut the large source sheet.

## Drawing later (not automatic)

```powershell
python scripts/send_small_sheet_tiles.py "C:/plotter_pdf/_plotter_jobs/Small_stitch_trial/job.json" --port COM6
```

Use ONLY this registered-job runner, not the ordinary A4/A3 sender. It verifies
the known small-board identity and file hashes before drawing, retains one
connection, initializes the existing Z reference once, holds motors between
passes, and checks controller Idle/position before paper handling. There is no
automatic unlock, XY homing, reconnect/resume, or firmware update.

Every pass requires an explicit `DRAW N`. Every continuation requires alignment
at A and a pen-up check at B. Abort clears the motion queue; do not resume an
aborted registration chain. The original motor hold setting is restored only
after successful completion. Always visually verify that the pen is raised
before moving paper; software status cannot prove physical pen motion.

The trial is only the first two neighboring A2 passes. It exercises a seam with
circles, diagonals, straight lines and dashes; it does not start any hardware.
Physical registration accuracy still needs this paper trial before production.

The sender does not send feed-hold or reset commands when board identity is
rejected or the controller is already busy before this job starts. Abort/reset
is reserved for motion owned by the verified drawing session. A disconnected
abort still closes the serial handle and asks for manual intervention.
Regression checks inspect actual PDF segments (not only PDF close-path flags),
the serialized NC bounds/pen lifts, file hashes, and both registration frames.
Registration marks are forbidden inside the whole title-block rectangle,
including its blank cells.

## Frameless drawing and a complete title-block pass

For a vector CAD sheet with a standard bottom-right 185 mm title block:

```powershell
python scripts/prepare_small_sheet_tiles.py --pdf "C:/drawings/source.pdf" --format A1 --no-frame --whole-stamp
```

`--no-frame` removes long sheet-border edges, retaining shared edges of the
title-block table. `--whole-stamp` removes the original title block from every
grid pass, scales only that block to at most 180 mm, anchored at its original
bottom-right corner, and places it in one final pass with its own two-mark
registration. Body geometry and text stay at 1:1. Empty body windows are removed
BEFORE registration marks are added. The remaining windows are reordered into
an edge-adjacent route that ends beside the stamp. Preparation fails if no safe
nonempty-only route exists, rather than adding unannounced blank passes.
No paper rotation is needed. Obsolete generator-owned NC files are removed.
The manifest records the title-block scale, position and pass number. These
options do not change A4/A3 or the default A2/A1 tiling mode.

The first active source window can start away from the full-sheet corner.
Its exact coordinates are printed by the runner and recorded in `start_window_mm`.
Use the overview to position this source region in the field before pass 01.
Blue guides of neighboring body windows are clipped away from the title block
in the overview; they do not imply splitting the stamp. A separate one-page
`Title_block_from_Gcode.pdf` shows its entire single physical field, decoded
from the dedicated NC pass, without any neighboring grid guides.

## Explicitly prepare a different paper format

```powershell
python scripts/prepare_small_sheet_tiles.py --pdf "C:/drawings/A1.pdf" --format A2 --fit-format --no-frame --whole-stamp --output "C:/plotter_pdf/_plotter_jobs/drawing_A2"
```

`--fit-format` uniformly fits the source drawing into the requested A2/A1 page,
preserving its orientation and aspect ratio. Unlike the default 1:1 mode,
this explicitly changes the drawing scale. The title block is handled
independently: it remains a complete 180 mm final pass, anchored 5 mm from
the right and bottom target-page edges. Existing dimensions/text content are
not rewritten. The source/target sizes and exact drawing scale are recorded
in `source_fit`, and the overview labels the source scale. Use a separate
output directory for each requested paper format to retain both versions.

Machine files are stored byte-for-byte via `.gitattributes` (`*.nc -text`,
`*.gcode -text`). Do not normalize their line endings independently of the
manifest: its SHA-256 records must match after checkout on any operating system.
