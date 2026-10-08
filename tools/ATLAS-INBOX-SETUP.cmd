@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_inbox.py --setup
) else (
  py -3 tools\atlas_inbox.py --setup
)
echo.
echo ATLAS - folder setup complete. Sources remain disabled until authorization is reviewed.
pause
