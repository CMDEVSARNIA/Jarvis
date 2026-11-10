@echo off
REM Double-click to start Jarvis on Windows. It checks for updates first.
cd /d "%~dp0"
if exist start-jarvis.new.bat (
  move /y start-jarvis.new.bat start-jarvis.bat >nul
  start "" "%~dp0start-jarvis.bat" %*
  exit /b
)
if not exist .venv\Scripts\python.exe (
  echo First run: setting up Python environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
)
.venv\Scripts\python -m jarvis.launcher %*
pause
