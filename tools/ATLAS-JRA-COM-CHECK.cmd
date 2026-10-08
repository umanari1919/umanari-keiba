@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0.."
echo ============================================================
echo  NEO JIZO ATLAS - JV-Link LOCAL COM CHECK
echo ============================================================
echo Local COM registration only. No JVInit, JVOpen, JVGets,
echo no JRA server communication, and no database changes.
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_doctor.py --check-com
) else (
  py -3 tools\atlas_doctor.py --check-com
)
echo.
echo Check JV_COM_LOCAL status above. Other BLOCKED rows are separate.
pause
