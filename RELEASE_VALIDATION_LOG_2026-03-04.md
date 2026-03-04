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

## Artifact checksums (SHA256)

- `dist\PlotterStudio.exe`
  - `676E0DFB05AF06EC96661C48227643052DE4D73E538EE9B03DEAA68F2DC7C3E7`
- `dist\PlotterStudio-portable.zip`
  - `56892998AB4E12DE79D6F5EE553F13660CBF962597373B19382B642BD8A6A6C1`

## Notes

- This log confirms reproducible local build generation and artifact hashing.
- Clean-machine validation (fresh Windows VM/host install path) remains a separate release gate step.
