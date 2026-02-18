@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "COM=%1"
if "%COM%"=="" set "COM=COM5"

%PYTHON% "%ROOT%\src\plotter_pdf_drawer.py" --calibrate-corners --com %COM% --corner-mark-size 2.5
if errorlevel 1 pause
exit /b %errorlevel%
