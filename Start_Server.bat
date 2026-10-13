@echo off
rem Start the Cadence server and open it in the browser. Double-click to run.
rem If Cadence is already running, this only opens the browser. Stop it with Stop_Server.bat.
setlocal
cd /d "%~dp0"

netstat -ano | findstr /r /c:"127\.0\.0\.1:8420 .*LISTENING" >nul
if not errorlevel 1 (
  echo Cadence is already running.
  start "" http://127.0.0.1:8420
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found in %CD%. Run setup.ps1 first.
  pause
  exit /b 1
)

rem Offline flags: MedASR fails to load on this network's SSL without them.
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

echo Starting Cadence... (the first start takes up to a minute while the speech model loads)
if not exist "logs" mkdir "logs"
rem Server output (startup messages, timings, errors - never note text) goes to logs\server.log, so
rem if Cadence ever stops on its own the reason is on disk. The previous log is kept as server.prev.log.
if exist "logs\server.log" move /y "logs\server.log" "logs\server.prev.log" >nul
start "Cadence Server" /min cmd /c ".venv\Scripts\python.exe -m uvicorn app.ui.server:app --host 127.0.0.1 --port 8420 >> logs\server.log 2>&1 || pause"

for /l %%i in (1,1,60) do (
  ping -n 3 127.0.0.1 >nul
  netstat -ano | findstr /r /c:"127\.0\.0\.1:8420 .*LISTENING" >nul && goto :ready
)
echo Cadence did not start within 2 minutes. The reason is in logs\server.log:
  type "logs\server.log"
pause
exit /b 1

:ready
echo Cadence is running at http://127.0.0.1:8420
start "" http://127.0.0.1:8420
exit /b 0
