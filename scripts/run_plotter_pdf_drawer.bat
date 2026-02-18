@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."

if "%~1"=="" (
  where pyw >nul 2>&1
  if not errorlevel 1 (
    start "" pyw "%ROOT%\src\plotter_pdf_drawer.py"
    exit /b 0
  )
  where pythonw >nul 2>&1
  if not errorlevel 1 (
    start "" pythonw "%ROOT%\src\plotter_pdf_drawer.py"
    exit /b 0
  )
)

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found in PATH.
  echo Install Python 3.10+ and add it to PATH.
  exit /b 1
)

if "%~1"=="" (
  python "%ROOT%\src\plotter_pdf_drawer.py"
  exit /b %errorlevel%
)

python "%ROOT%\src\plotter_pdf_drawer.py" "%~1"
exit /b %errorlevel%
