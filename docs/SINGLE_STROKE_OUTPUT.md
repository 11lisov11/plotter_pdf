# Single-stroke output

The final A1/A2 registered writer, the established A4/A3 pen writer and the
shared XY writer use `geometry.unique_strokes.unique_strokes` before emitting
their coordinates. No recognizer, font, scale, pen height or machine setting
is changed by this cleanup.

Coordinates are quantized to the actual output precision (0.001 or 0.0001 mm).
Integer direction-independent line keys and interval unions remove identical,
reversed, contained and partially overlapping segments. Only uncovered parts
of a partially repeated line are retained. Missing parts of a polyline cause
a pen-up break, never a new connecting diagonal. Separate parallel lines,
crossings, hatch spacing and original path order are preserved.

Each registered pass is cleaned independently. The deliberately configured
0.3-mm seam overlap between paper positions is retained for registration.

`scripts/rebuild_registered_single_stroke.py JOB_DIRECTORY [...]` is an offline
migration for existing registered packages. It archives the old manifest/NC,
replays their exact serialized geometry without re-recognizing text, rewrites
every drawing pass and updates hashes/counts. It independently compares the
old/new integer-line unions and rejects loss/addition of visible geometry,
remaining retracing or changed parking. Previews are reconstructed from the
new NC. Initialization, alignment files and sheet transforms are unchanged.

The migration never opens a device or sends drawing commands. A job interrupted
before migration must not resume an old in-memory sender against the new files.
