@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."
set "CURSOR=%USERPROFILE%\Documents\NEO-JIZO-ATLAS-DATA\receipts\jra_jvlink_cursor.json"
set "SEED="
if not exist "!CURSOR!" (
 echo First run requires an explicit JV-Link last-file timestamp.
 echo This uses NORMAL DELTA only - NOT full historic initial download.
 set /p "SEED=Start YYYYMMDDHHMMSS (e.g. 20261001000000): "
 if "!SEED!"=="" (
   echo No timestamp specified; nothing was downloaded.
   pause
   exit /b 2
 )
)
where py >nul 2>nul
if errorlevel 1 (
  if "!SEED!"=="" (python tools\atlas_jvlink_capture.py --capture) else (python tools\atlas_jvlink_capture.py --capture --first-from !SEED!)
) else (
  if "!SEED!"=="" (py -3 tools\atlas_jvlink_capture.py --capture) else (py -3 tools\atlas_jvlink_capture.py --capture --first-from !SEED!)
)
echo.
echo JV-Link raw capture is separate from DB import and canonical mapping.
pause
