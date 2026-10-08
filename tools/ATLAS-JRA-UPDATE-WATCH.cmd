@echo off
setlocal
cd /d "%~dp0.."
if "%ATLAS_PG_DSN%"=="" (
 echo ATLAS_PG_DSN is missing. Nothing started.
 pause
 exit /b 2
)
echo ATLAS JRA approved hourly updates. Keep this window open. Ctrl+C stops.
echo Do not start ATLAS-JRA-WATCH simultaneously.
where py >nul 2>nul
if errorlevel 1 (
 python tools\atlas_jra_daily.py --watch --interval 3600
) else (
 py -3 tools\atlas_jra_daily.py --watch --interval 3600
)
echo.
pause
