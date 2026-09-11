@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "TRAY_SCRIPT=%ROOT%\scripts\cali_crm_tray.ps1"
set "REGISTER_SCRIPT=%ROOT%\scripts\register_cali_crm_startup.ps1"

rem Register the CURRENT VIV client location at every manual launch. HKCU Run points
rem to powershell.exe + the persistent tray supervisor, not directly to this .bat.
powershell -NoProfile -ExecutionPolicy Bypass -File "%REGISTER_SCRIPT%" -Root "%ROOT%"
if errorlevel 1 (
  echo VIV startup registration failed.
  exit /b 1
)

rem Start exactly one hidden VIV tray supervisor. It owns the tray icon and ensures
rem the backend on 21000 and frontend on 21010 are running.
start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%TRAY_SCRIPT%"

endlocal
exit /b 0
