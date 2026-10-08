@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul 2>&1
:ATLAS_MENU
cls
echo ============================================================
echo       NEO JIZO ATLAS - Windows Control Menu
echo ============================================================
echo.
echo   SAFE / NO DATABASE CHANGES
echo   [1] Doctor : read-only environment checks
echo   [2] Synthetic tests : no databases, keys or network
echo   [3] JV-Link COM check : LOCAL ONLY, no JVInit/download
echo   [4] New database readiness : read-only inspection
echo.
echo   USER-APPROVED ACTIONS ONLY
echo   [5] CREATE a missing isolated atlas database (requires CREATE)
echo   [6] Initial JRA capture (licensed JV-Link, prompts for date)
echo   [7] JRA receive + import + canonical mapping, one cycle
echo   [8] JRA hourly update (keeps this window open)
echo.
echo   [Q] Close this menu
echo.
choice /C 12345678Q /N /M "Choose one option: "
if errorlevel 9 goto ATLAS_EXIT
if errorlevel 8 goto ATLAS_WATCH
if errorlevel 7 goto ATLAS_ONCE
if errorlevel 6 goto ATLAS_CAPTURE
if errorlevel 5 goto ATLAS_CREATE
if errorlevel 4 goto ATLAS_DB_CHECK
if errorlevel 3 goto ATLAS_COM
if errorlevel 2 goto ATLAS_TEST
if errorlevel 1 goto ATLAS_DOCTOR
goto ATLAS_EXIT

:ATLAS_DOCTOR
call "%~dp0ATLAS-DOCTOR.cmd"
goto ATLAS_MENU

:ATLAS_TEST
call "%~dp0ATLAS-OFFLINE-SELFTEST.cmd"
goto ATLAS_MENU

:ATLAS_COM
call "%~dp0ATLAS-JRA-COM-CHECK.cmd"
goto ATLAS_MENU

:ATLAS_DB_CHECK
call "%~dp0ATLAS-DB-CHECK.cmd"
goto ATLAS_MENU

:ATLAS_CREATE
echo WARNING: first-time DB creation, no existing database overwritten.
call "%~dp0ATLAS-DB-CREATE.cmd"
goto ATLAS_MENU

:ATLAS_CAPTURE
echo WARNING: requires rights-approved JRA-VAN local SDK.
call "%~dp0ATLAS-JRA-CAPTURE.cmd"
goto ATLAS_MENU

:ATLAS_ONCE
echo WARNING: connects to JRA-VAN and writes ONLY approved new ATLAS DB.
call "%~dp0ATLAS-JRA-UPDATE.cmd"
goto ATLAS_MENU

:ATLAS_WATCH
echo WARNING: connects to JRA-VAN hourly until interrupted.
call "%~dp0ATLAS-JRA-UPDATE-WATCH.cmd"
goto ATLAS_MENU

:ATLAS_EXIT
echo Menu closed. No scheduled tasks or services were installed.
exit /b 0
