@echo off
rem Starts MedMap and opens it in your browser. Double-click this file,
rem or run `web\start.cmd` from the project folder. Close this window to stop.

cd /d "%~dp0.."

rem Find Python 3. The "python" command on Windows can be a Microsoft Store
rem shortcut that isn't really Python, so check that it actually runs.
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  echo.
  echo Python 3 is not installed, and MedMap's server needs it.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^)
  echo or run:  winget install Python.Python.3.12
  echo Then double-click start.cmd again.
  echo.
  pause
  exit /b 1
)

start "" http://127.0.0.1:8000/
%PY% -m uvicorn optimal_hospital_placer.api.main:app --app-dir src --host 127.0.0.1 --port 8000 %*
pause
