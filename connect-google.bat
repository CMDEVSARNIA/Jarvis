@echo off
REM Double-click to connect Huxley to your Google account (calendar, Gmail, Docs).
REM See docs\Huxley-Google-Setup.pdf for the one-time Google Cloud steps first.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run start-huxley.bat once first, then try this again.
  pause
  exit /b 1
)
.venv\Scripts\python -m jarvis.google_auth
pause
