# Release

Windows release is manual in GitHub Actions: **Release Windows** workflow. Local Windows build:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows_release.ps1
```

The zip contains `PlotterPDF_GUI.exe`, `plotter-pdf.exe`, `plotter-pdf-self-check.exe`, `config`, `examples`, and `README_START_HERE.md`.
