@echo off
setlocal

set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%build_windows.ps1" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo Build failed with code %RC%.
  exit /b %RC%
)

echo Build finished successfully.
exit /b 0

