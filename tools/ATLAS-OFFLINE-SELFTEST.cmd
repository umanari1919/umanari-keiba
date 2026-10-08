@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0.."
echo ============================================================
echo  NEO JIZO ATLAS - LOCAL SYNTHETIC TESTS
echo ============================================================
echo No licensed JRA/NAR data, no SDK communication, no DB write.
echo DB credentials and live integration flags are removed from tests.
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_offline_selftest.py
) else (
  py -3 tools\atlas_offline_selftest.py
)
if errorlevel 1 echo Some synthetic tests are BLOCKED - do not start real import.
echo.
pause
