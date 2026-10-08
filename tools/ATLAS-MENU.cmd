@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul 2>&1
:ATLAS_MENU
cls
echo ============================================================
echo       NEO JIZO ATLAS - データ取り込み操作メニュー
echo ============================================================
echo.
echo   【安全確認】データベースの変更なし
echo   [1] 環境診断（読み取り専用）
echo   [2] 合成テスト（DB・通信・秘密情報なし）
echo   [3] JV-Link COM確認（ローカル限定・取得なし）
echo   [4] 新DBの準備状況を確認（変更なし）
echo.
echo   【実行処理】権利・環境の承認後のみ
echo   [5] 新しいATLAS専用DBを作成（CREATE入力が必要）
echo   [6] JRA初回取得（許諾済みSDK・起点日時が必要）
echo   [7] JRA取得からDB登録まで一括更新
echo   [8] JRAを60分ごとに更新（画面を開いたまま）
echo.
echo   [Q] 終了
echo.
choice /C 12345678Q /N /M "操作を選んでください: "
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
echo 注意：新DBの初回作成です。既存DBは上書きしません。
call "%~dp0ATLAS-DB-CREATE.cmd"
goto ATLAS_MENU

:ATLAS_CAPTURE
echo 注意：JRA-VANの有効な契約と公式SDKが必要です。
call "%~dp0ATLAS-JRA-CAPTURE.cmd"
goto ATLAS_MENU

:ATLAS_ONCE
echo 注意：JRA-VANへ接続し、許諾済みの新ATLAS DBを更新します。
call "%~dp0ATLAS-JRA-UPDATE.cmd"
goto ATLAS_MENU

:ATLAS_WATCH
echo 注意：停止するまで1時間ごとにJRA-VANへ接続します。
call "%~dp0ATLAS-JRA-UPDATE-WATCH.cmd"
goto ATLAS_MENU

:ATLAS_EXIT
echo 終了しました。タスク登録やサービスの変更はしていません。
exit /b 0
