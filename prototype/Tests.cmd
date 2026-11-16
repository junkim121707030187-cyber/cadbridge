@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0app"
"runtime\python-env\Scripts\python.exe" -B -m pytest tests -q
pause
