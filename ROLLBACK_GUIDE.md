# Plotter Studio Rollback Guide

## Goal

Restore a previously known-good Plotter Studio build in less than 15 minutes.

## Required artifacts

- Previous stable package (`PlotterStudio-portable.zip` or `PlotterStudio.exe`).
- Known-good config snapshot:
  - `config\axis_profile.json`
  - versioned baseline snapshots in `config\snapshots\` (for example `axis_profile.2026-03-04.known-good.json`)
  - optional machine-specific presets or temp calibrations.
- Current release notes with version and commit tag.

## Trigger conditions

Initiate rollback if any of these are true:

- repeatable crash on startup or during preview/draw;
- conversion regression for production input formats;
- out-of-bounds or unsafe machine motion compared to previous stable build;
- critical serial communication regression.

## Procedure

1. Stop all running Plotter Studio instances.
2. Backup current install directory and current `config\axis_profile.json`.
3. Deploy previous stable package to a clean folder.
4. Restore known-good `config\axis_profile.json`.
5. Launch the previous stable executable.
6. Run quick verification:
   - app opens;
   - COM detection works;
   - SVG preview dry-run works;
   - optional frame draw confirms expected machine bounds.

## Validation checklist

- [ ] Restored version launches successfully.
- [ ] Machine profile loaded correctly.
- [ ] No startup exceptions in logs.
- [ ] Core preview/draw path confirmed.

## Communication

- Record rollback timestamp and operator.
- Reference failing release version and rollback target version.
- Open incident ticket with reproduction steps and logs.
