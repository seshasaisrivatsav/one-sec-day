@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.cmd in the repository first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r editor\requirements.txt
  if errorlevel 1 (pause & exit /b 1)
)
".venv\Scripts\python.exe" editor\app.py %*
if errorlevel 1 pause
