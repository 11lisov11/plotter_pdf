@echo off
setlocal

set "ROOT=%~dp0.."

where pyw >nul 2>&1
if not errorlevel 1 (
  start "" pyw "%ROOT%\main.py"
  exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
  start "" pythonw "%ROOT%\main.py"
  exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found in PATH.
  exit /b 1
)

python "%ROOT%\main.py"
exit /b %errorlevel%

