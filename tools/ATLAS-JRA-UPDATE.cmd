@echo off
setlocal
cd /d "%~dp0.."
if "%ATLAS_PG_DSN%"=="" (
 echo ATLAS_PG_DSN is missing. No JRA capture was started.
 pause
 exit /b 2
)
where py >nul 2>nul
if errorlevel 1 (
 python tools\atlas_jra_daily.py --run
) else (
 py -3 tools\atlas_jra_daily.py --run
)
if errorlevel 1 (
 echo ATLAS update has been blocked. Review console status; never bypass safety checks.
)
echo.
pause
