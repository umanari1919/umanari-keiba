@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0.."
echo ============================================================
echo NEO JIZO ATLAS - NEW DB CHECK (READ ONLY)
echo ============================================================
echo This NEVER creates, deletes or changes a database.
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
where py >nul 2>nul
if errorlevel 1 (
 python tools\atlas_db_setup.py
) else (
 py -3 tools\atlas_db_setup.py
)
echo.
pause
