@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.cmd first. See README.md for Python and FFmpeg installation.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause

