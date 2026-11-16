@echo off
setlocal
cd /d "%~dp0"
"runtime\python-env\Scripts\pythonw.exe" "app\stop.py"
exit /b 0
