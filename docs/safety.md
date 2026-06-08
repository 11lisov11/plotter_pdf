# Safety

Before first real draw:

```powershell
plotter-pdf-self-check
plotter-pdf examples\simple_square.svg --preview --output _plotter_jobs\simple_square.nc
```

Checklist: pen up, sheet fixed, no obstacles, correct COM, bounds inside work area, preflight OK, emergency release known. Never run hardware tests without both `PLOTTER_HARDWARE=1` and `PLOTTER_COM=COMx`. Preview and G-code generation are safe offline operations; Draw must be confirmed explicitly.
