@echo off
REM Double-click to start Jarvis on Windows.
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up Python environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist .env (
  echo First run: let's enter your settings.
  .venv\Scripts\python -m jarvis.configure
)
.venv\Scripts\python -m jarvis
pause
