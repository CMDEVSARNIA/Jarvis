@echo off
REM Double-click to start Huxley. It checks for updates, then runs in the tray.
REM Add --console to keep this window open with live logs instead.
cd /d "%~dp0"
if exist start-huxley.new.bat (
  move /y start-huxley.new.bat start-huxley.bat >nul
  start "" "%~dp0start-huxley.bat" %*
  exit /b
)
if not exist .venv\Scripts\python.exe (
  echo First run: setting up Python environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
)
.venv\Scripts\python -m jarvis.launcher %*
if errorlevel 1 pause
