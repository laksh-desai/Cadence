@echo off
rem Stop the Cadence server. Save finished notes first: notes still in
rem "Notes in progress" are lost when the server stops.
setlocal
set FOUND=0

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127\.0\.0\.1:8420 .*LISTENING"') do (
  set FOUND=1
  taskkill /PID %%p /T /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq Cadence Server*" /T /F >nul 2>&1

if "%FOUND%"=="0" (
  echo Cadence was not running.
  goto :end
)

rem Wait until the port is really free, so an immediate Start_Server.bat starts fresh
rem instead of seeing the old server and assuming it is still running.
set /a TRIES=0
:waitfree
netstat -ano | findstr /r /c:"127\.0\.0\.1:8420 .*LISTENING" >nul || goto :freed
set /a TRIES+=1
if %TRIES% geq 15 goto :freed
ping -n 2 127.0.0.1 >nul
goto :waitfree

:freed
echo Cadence stopped.
rem A forced stop skips Cadence's own cleanup, which leaves the decrypted working copy of the
rem database in %%TEMP%% (EFS-encrypted, but still a copy). Every save is already stored
rem encrypted, so delete the leftover copy.
for /d %%d in ("%TEMP%\cadence_*") do (
  if exist "%%d\cadence.db" rd /s /q "%%d" 2>nul
)

:end
ping -n 4 127.0.0.1 >nul
exit /b 0
