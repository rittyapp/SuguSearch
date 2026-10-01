@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
echo.
REM 配布 zip では files\setup.ps1、開発フォルダでは同じ場所の setup.ps1
set "PS1=%~dp0files\setup.ps1"
if not exist "%PS1%" set "PS1=%~dp0setup.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
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
