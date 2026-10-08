@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
echo NEO JIZO ATLAS JRA: hourly raw collection (requires approved source and existing cursor).
echo Keep this window open; Ctrl+C stops. Windows Task Scheduler not installed.
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_jvlink_capture.py --capture --watch --interval 3600
) else (
  py -3 tools\atlas_jvlink_capture.py --capture --watch --interval 3600
)
echo.
pause
