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

set "COM=%~1"
if "%COM%"=="" set "COM=COM5"
set "BAUD=%~2"
if "%BAUD%"=="" set "BAUD=115200"

set "SLEEP_ARG="
if /i "%~3"=="sleep" set "SLEEP_ARG=--sleep"
%PYTHON% "%ROOT%\src\release_motors.py" "%COM%" "%BAUD%" %SLEEP_ARG%
exit /b %errorlevel%
