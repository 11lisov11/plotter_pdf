# Plotter Studio Release Notes Template

## Release

- Version: `vX.Y.Z`
- Date: `YYYY-MM-DD`
- Commit/tag: `<hash or tag>`
- Release owner: `<name>`

## Summary

Short description of what changed in this release.

## Added

- Item 1
- Item 2

## Changed

- Item 1
- Item 2

## Fixed

- Item 1
- Item 2

## Performance

- Item 1

## Tests and validation

- CI status: `pass/fail`
- Local verification:
  - `unittest`: `pass/fail`
  - `pytest`: `pass/fail`
  - `build smoke`: `pass/fail`
- Hardware protocol (if release candidate/stable): `pass/fail/not-run`

## Breaking changes

- None / List breaking changes and migration steps.

## Known issues

- Issue 1 and workaround
- Issue 2 and workaround

## Upgrade instructions

1. Download `PlotterStudio-portable.zip` from release artifacts.
2. Extract to a clean folder.
3. Preserve and review machine profile in `config\axis_profile.json`.
4. Run `PlotterStudio.exe`.

## Rollback instructions

1. Stop current app instance.
2. Restore previous stable package.
3. Restore known-good configuration snapshot.
4. Verify COM connection and dry-run preview.

