@echo off
REM One-click launcher (no build needed). Requires Python 3.9+ installed.
REM Double-click this file to start the app.
setlocal
cd /d "%~dp0"
echo Checking Python and dependencies...
python -m pip install --quiet --disable-pip-version-check pywebview zstandard 2>nul
python "backend\relay_app.py"
if errorlevel 1 (
  echo.
  echo Could not start. Make sure Python 3.9+ is installed and on your PATH.
  echo Download: https://www.python.org/downloads/
  pause
)
endlocal
