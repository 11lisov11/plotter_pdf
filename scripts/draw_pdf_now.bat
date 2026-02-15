@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
  echo Python not found.
  echo Install Python 3.10+ and make sure python is in PATH.
  pause
  exit /b 1
)

echo Drag and drop a PDF/SVG file on this script.
echo   draw_pdf_now.bat "C:\path\to\file.pdf"
echo   draw_pdf_now.bat "C:\path\to\file.svg"

echo.

if "%~1"=="" (
  pause
  exit /b 1
)

%PYTHON% "%ROOT%\src\plotter_pdf_drawer.py" "%~1"
exit /b %errorlevel%
