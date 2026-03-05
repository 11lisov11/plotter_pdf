# Axis Profile Snapshots

This directory stores versioned known-good machine profile snapshots for rollback.

Current baseline snapshot:

- `axis_profile.2026-03-04.known-good.json`

How to use during rollback:

1. Backup current `config/axis_profile.json`.
2. Copy a known-good snapshot from this directory to `config/axis_profile.json`.
3. Restart app and verify frame/preview on the machine.

