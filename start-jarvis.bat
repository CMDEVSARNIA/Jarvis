@echo off
REM Double-click to start Jarvis on Windows.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: setting up Python environment...
  py -3 -m venv .venv || python -m venv .venv
)
echo Checking for updated components...
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist .env (
  echo First run: let us enter your settings.
  .venv\Scripts\python -m jarvis.configure
)
.venv\Scripts\python -m jarvis
pause
