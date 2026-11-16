@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python-env\Scripts\pythonw.exe" (
  echo CADBridge runtime was not found. Keep the runtime folder beside this file.
  pause
  exit /b 1
)
start "" "runtime\python-env\Scripts\pythonw.exe" "app\launch.py"
exit /b 0
