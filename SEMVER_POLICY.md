# Plotter Studio Semantic Versioning Policy

Version format: `MAJOR.MINOR.PATCH`

## Rules

1. Increase `PATCH` for backward-compatible bug fixes.
2. Increase `MINOR` for backward-compatible features and behavior improvements.
3. Increase `MAJOR` for breaking changes (APIs, config schema, workflow expectations).

## Examples

- `1.4.2 -> 1.4.3`: bug fix in conversion pipeline, no user-facing break.
- `1.4.2 -> 1.5.0`: new optional rendering mode, backward compatible.
- `1.4.2 -> 2.0.0`: incompatible settings format or protocol contract change.

## Pre-release tags

Use suffixes for release candidates:

- `vX.Y.Z-rc.1`
- `vX.Y.Z-rc.2`

Stable release is published without suffix after RC validation.

## Build metadata

Optional build metadata may be appended when needed:

- `vX.Y.Z+build.<id>`

This metadata must not change version precedence.

