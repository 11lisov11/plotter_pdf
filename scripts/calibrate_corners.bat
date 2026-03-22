@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

if "%~1"=="" (
  %PYTHON% "%ROOT%\src\plotter_pdf_drawer.py" --calibrate-corners --corner-mark-size 2.5
) else (
  %PYTHON% "%ROOT%\src\plotter_pdf_drawer.py" --calibrate-corners --com "%~1" --corner-mark-size 2.5
)
if errorlevel 1 pause
exit /b %errorlevel%
