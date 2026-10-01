@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set EC=%ERRORLEVEL%
chcp 932 >nul
echo.
if %EC% neq 0 (
  echo セットアップに失敗しました（%EC%）。上のメッセージを確認してください。
) else (
  echo セットアップが完了しました。
)
pause
exit /b %EC%
