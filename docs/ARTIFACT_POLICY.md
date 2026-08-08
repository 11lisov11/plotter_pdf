# Plotter package artifact policy

## User-facing package

An ordinary package should contain only:

1. A copy of the source PDF.
2. A PDF preview rendered from the final G-code.
3. The final G-code file, or two pass files for A3.

`NC` and `G-code` are the same instruction payload for this project. Do not
publish duplicate files with both extensions unless an external controller
explicitly requires a particular extension.

## Optional diagnostics

Reports, CSV summaries, logs, page renders, candidates, audits, PNG contacts,
and comparison overlays are generated only for development or acceptance.
They are not part of a normal user package.

Local acceptance output belongs under `_plotter_jobs/product_acceptance/` and
is ignored by Git. A diagnostic artifact is committed only when it is selected
as a stable regression fixture.

## Source protection

- Rebuild from the original PDF or CAD-exported PDF.
- Never use edited final G-code as the geometry source for a new package.
- Never repair a package by deleting arbitrary G-code lines.
- Existing frame, stamp, text, scale, and A3 pass rules are regression-protected.
