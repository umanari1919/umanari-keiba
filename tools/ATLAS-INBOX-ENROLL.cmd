@echo off
setlocal
cd /d "%~dp0.."
echo ATLAS source enrollment - only permissions you reviewed in sources.local.json.
if "%ATLAS_PG_DSN%"=="" (
 echo ATLAS_PG_DSN is not configured. No database was changed.
 pause
 exit /b 2
)
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_inbox.py --enroll
) else (
  py -3 tools\atlas_inbox.py --enroll
)
echo.
pause
