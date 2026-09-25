@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.11 or newer from https://www.python.org/downloads/windows/
  echo Include the Python launcher and Tcl/Tk support, then run Setup.cmd again.
  pause
  exit /b 1
)
py -3 -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or newer is required'"
if errorlevel 1 goto fail
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" daily_reel.py doctor
if errorlevel 1 goto fail
echo.
echo Setup complete. Double-click Start.cmd.
pause
exit /b 0
:fail
echo.
echo Setup is not complete. Read the error above and README.md.
pause
exit /b 1

