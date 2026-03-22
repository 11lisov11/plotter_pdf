@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
  echo Python not found.
  echo Install Python 3.10+ and make sure it is available in PATH or .venv\Scripts.
  exit /b 1
)

%PYTHON% "%ROOT%\src\plotter_pdf_drawer.py" --frame %*
if errorlevel 1 pause
exit /b %errorlevel%
