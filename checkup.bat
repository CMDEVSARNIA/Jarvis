@echo off
REM Double-click to check Jarvis can reach Claude. The report is safe to share.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Jarvis is not installed in this folder yet.
  echo Double-click start-jarvis.bat in this folder first, then run this again.
  pause
  exit /b
)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
.venv\Scripts\python -m jarvis.doctor
echo.
pause
