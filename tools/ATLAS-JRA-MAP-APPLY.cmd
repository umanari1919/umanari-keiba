@echo off
setlocal
cd /d "%~dp0.."
if "%ATLAS_PG_DSN%"=="" (
  echo ATLAS_PG_DSN not configured. Nothing was changed.
  pause
  exit /b 2
)
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_jvdata_map.py --local-jra --apply --limit 10
) else (
  py -3 tools\atlas_jvdata_map.py --local-jra --apply --limit 10
)
echo.
pause
