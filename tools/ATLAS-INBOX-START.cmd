@echo off
setlocal
cd /d "%~dp0.."
set "ATLAS_MODE="
if /I "%ATLAS_INBOX_COMMIT%"=="1" set "ATLAS_MODE=--commit"
if "%ATLAS_MODE%"=="" echo SAFE PREVIEW MODE - no database changes.
if not "%ATLAS_MODE%"=="" echo APPROVED COMMIT MODE - only neo_jizo_atlas can be written.
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_inbox.py --watch %ATLAS_MODE%
) else (
  py -3 tools\atlas_inbox.py --watch %ATLAS_MODE%
)
echo.
pause
