@echo off
setlocal
cd /d "%~dp0.."
echo ============================================================
echo NEO JIZO ATLAS - LOCAL PREFLIGHT (READ ONLY)
echo ============================================================
echo No installation, no JV-Link data retrieval, no DB writes.
where py >nul 2>nul
if errorlevel 1 (
 python tools\atlas_doctor.py
) else (
 py -3 tools\atlas_doctor.py
)
echo.
echo Review any BLOCKED/ACTION_REQUIRED items before running update.
pause
