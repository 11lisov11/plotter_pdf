# Hardware setup

1. Connect GRBL controller and identify COM in Device Manager.
2. Run `plotter-pdf-self-check`.
3. Run preview first; inspect bounds and line counts.
4. For real draw use `--com COMx` or select COM in GUI.
5. Hardware pytest tests require:

```powershell
$env:PLOTTER_HARDWARE=1
$env:PLOTTER_COM="COM6"
pytest -m hardware_required
```
