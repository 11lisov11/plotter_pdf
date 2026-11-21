# A1/A2 registered jobs: physical XY reference

This procedure belongs only to `scripts/send_small_sheet_tiles.py`. Existing
A4/A3 preparation and senders are unchanged.

## New job

The carriage must physically be at the calibrated bottom-left home before the
new session starts. That is NOT the first source-window corner, the top park
after a previous pass, or a point that merely reports WPos X0 Y0.

The sender verifies the board and Idle state, reads settings, then requires the
literal confirmation `HOME 0 0`. Declining sends no initialization, XY zero,
hold, or reset. Confirmation binds the physical home once with G21, G90 and
G92 X0 Y0; it does not command an XY move. The usual Z initialization follows.

The first source-window corner remains at machine X0 Y-285. Place the paper
using the placement guide, independently of the carriage's home reference.

## Between passes

Keep the same connection, XY zero and motor hold. First move the paper by the
large required distance with the pen UP. Confirm that coarse placement before
the sender lowers the stationary pen at A for fine alignment. Secure the sheet
and confirm A; the sender raises the pen, travels to B, then lowers it there
so the tip can be compared directly with the center of the cross. Confirmation
at B raises the pen before returning to A. A retry lowers it again at A; a
successful check leaves it raised before the next DRAW prompt. Do not drag
the paper over a touching pen during the large repositioning step.

This interactive sequence is implemented by the sender, not injected into the
existing NC files. A session that was already running keeps its old prompts
and must not be restarted merely to enable this feature mid-job.

Do not repeat G92, reset the
controller, or move the carriage by hand. If physical XY reference is lost,
do not continue the registered queue: restart with a verified home.

## Why reported zero is insufficient

A controller/USB reset can leave the carriage physically near the top while
reporting zero. Negative-Y commands can then run into the travel boundary;
later, larger negative moves can lose additional steps. The drawing and its
dimension line can consequently have different offsets despite every command
receiving `ok`. Idle and MPos/WPos are not encoder feedback.

The VB-6 photo is consistent with this failure mode. An offline boundary-loss
model reproduces the main-view/dimension displacement (about 91.102 mm).
That is evidence for the hypothesis, not a physical measurement or proof of
a specific mechanical collision. Actual physical motion has not been verified.

## Audit trail

Each new run creates a unique JSONL file in `tmp/small_sheet_runs`, or at a new
path supplied with `--log`. It includes initial MPos/WPos/WCO status responses,
home confirmation, the new reference, transmitted commands, acknowledgements,
file hashes and final Idle positions. Existing logs are never overwritten.
These records show controller state/command acceptance, not physical accuracy.

No NC geometry, scale, pen height, firmware or motor settings were changed by
this reference correction. An already-running sender keeps its old code and
must not be resumed as if this correction had retroactively changed its state.
