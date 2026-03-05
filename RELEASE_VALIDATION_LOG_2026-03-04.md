# Release Validation Log (2026-03-04)

## Environment

- Host: local Windows workstation
- Project root: `C:\plotter_pdf`
- Validation date: 2026-03-04

## Build execution

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Result: `pass`

Generated artifacts:

- `dist\PlotterStudio.exe`
- `dist\PlotterStudio-portable.zip`

## Portable package smoke validation

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\validate_portable.ps1
```

Result: `pass`

Observed behavior:

- archive extracted to temporary directory;
- `PlotterStudio.exe` launched successfully;
- smoke instance terminated after startup wait.

## Artifact checksums (SHA256)

- `dist\PlotterStudio.exe`
  - `E4B04A6DD1CADA0406D3123083F794EF29F59D0E625D6EFCECCE67238E33953C`
- `dist\PlotterStudio-portable.zip`
  - `88C545C142C7CDC0346AF89D4D56C7898017B0A2E3AAEED4460308E9B62C3EEB`

## Notes

- This log confirms reproducible local build generation and artifact hashing.
- Validation was re-run after backend extraction/error-model updates (`machine/grbl_sender.py`, `gcode/stats.py`, `gcode/finalize.py`, `gcode/penlift.py`, `gcode/bounds.py`, `gcode/preflight.py`, protocol/manual error mapping).
- Clean-machine validation (fresh Windows VM/host install path) remains a separate release gate step.
