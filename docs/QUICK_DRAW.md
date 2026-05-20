# Quick draw commands

Use these commands from `D:\plotter_pdf`. Default hardware path is `COM6 @ 115200`.

```powershell
python main.py --calibrate-corners --calibration-profile fast --com COM6
python scripts\find_ready_package.py "Компьютерная графика\22 вариант" --kind a4
python main.py --draw-ready "Компьютерная графика\22 вариант" --kind a4 --com COM6
python main.py "path\to\a3.pdf" --sheet-format a3 --pass-cols 1 --pass-rows 2 --pass-row 1 --com COM6
python main.py "path\to\a3.pdf" --sheet-format a3 --pass-cols 1 --pass-rows 2 --pass-row 2 --sheet-offset-y-mm 3.0 --com COM6
```

If a previous sender was interrupted and the port looks busy:

```powershell
python scripts\sender_guard.py --port COM6
python scripts\sender_guard.py --port COM6 --stop
```
