@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0.."
echo ============================================================
echo NEO JIZO ATLAS - CREATE NEW ISOLATED DATABASE
echo ============================================================
echo This only creates an absent database named neo_jizo_atlas.
echo The original mykeibadb and all user data are NEVER modified.
echo Existing unknown databases are NOT overwritten.
if "%ATLAS_PG_ADMIN_DSN%"=="" (
 echo BLOCKED: ATLAS_PG_ADMIN_DSN is not configured.
 pause
 exit /b 2
)
if "%ATLAS_PG_DSN%"=="" (
 echo BLOCKED: ATLAS_PG_DSN is not configured.
 pause
 exit /b 2
)
set "ATLAS_CONFIRM="
set /p "ATLAS_CONFIRM=Type CREATE to explicitly create a NEW atlas database: "
if /I not "%ATLAS_CONFIRM%"=="CREATE" (
 echo Cancelled. Nothing was changed.
 pause
 exit /b 0
)
where py >nul 2>nul
if errorlevel 1 (
 python tools\atlas_db_setup.py --apply
) else (
 py -3 tools\atlas_db_setup.py --apply
)
echo.
pause
