@echo off
setlocal
cd /d "%~dp0\.."
python scripts\audit_toe_packages.py %*
endlocal
