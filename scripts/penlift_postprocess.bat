@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."

if "%~1"=="" (
  echo Drag and drop a .gcode file onto this script.
  echo Usage: %~nx0 ^<file.gcode^>
  pause
  exit /b 1
)

set "IN=%~1"
if /I "%~x1"==".gcode" (
  set "OUT=%~dpn1_pen.gcode"
) else (
  set "OUT=%~dpn1_pen.gcode"
)

python "%ROOT%\src\penlift_postprocess.py" "%IN%" --output "%OUT%" --z-down 11.9 --delay 0.15
if errorlevel 1 (
  echo Error while running postprocessor
  exit /b 1
)

echo Done: %OUT%
