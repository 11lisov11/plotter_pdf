@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
python "%ROOT%\src\plotter_pdf_drawer.py" --frame
pause
