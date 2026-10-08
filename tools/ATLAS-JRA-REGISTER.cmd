@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
echo ============================================================
echo NEO JIZO ATLAS - JRA取得元の登録（JRAのみ）
echo ============================================================
echo 初期状態は確認のみ。登録には利用権限の証拠が必要です。
echo 既存 mykeibadb・原本・NAR取得元・サービスには触れません。
echo.
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_jra_register.py
) else (
  py -3 tools\atlas_jra_register.py
)
if errorlevel 1 (
  echo 保留。承認済み設定・新DB接続が確認できません。
  pause
  exit /b 2
)
echo.
set "JRA_CONFIRM="
set /p "JRA_CONFIRM=利用権限とJRAのみのDB登録を確認したら REGISTER と入力: "
if not "%JRA_CONFIRM%"=="REGISTER" (
  echo 中止しました。DB登録は実行していません。
  pause
  exit /b 0
)
where py >nul 2>nul
if errorlevel 1 (
  python tools\atlas_jra_register.py --apply
) else (
  py -3 tools\atlas_jra_register.py --apply
)
if errorlevel 1 (
  echo 保留。データ取得やサービス起動はしません。
  pause
  exit /b 2
)
echo JRA取得元の新DB登録チェックが完了しました。
pause
