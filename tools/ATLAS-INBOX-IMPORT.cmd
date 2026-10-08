@echo off
setlocal
cd /d "%~dp0.."
echo ATLAS approved inbox importer - Only new neo_jizo_atlas is permitted.
if "%ATLAS_PG_DSN%"=="" (
 echo ATLAS_PG_DSN is not configured. Import will not start.
 pause
 exit /b 2
)
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_inbox.py --watch --commit
) else (
  py -3 tools\atlas_inbox.py --watch --commit
)
echo.
pause
