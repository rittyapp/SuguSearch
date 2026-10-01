@echo off
chcp 932 >nul
setlocal EnableExtensions
set "PORT=8888"
if not "%~1"=="" set "PORT=%~1"
set "SCRIPT=%~dp0everything-http-tool.ps1"
set "LOGDIR=%~dp0"
set "DID_PUSHD=0"
pushd "%~dp0" 2>nul
if not errorlevel 1 (
  set "DID_PUSHD=1"
  set "SCRIPT=%CD%\everything-http-tool.ps1"
  set "LOGDIR=%CD%\"
)
if not exist "%SCRIPT%" (
  echo ERROR: script not found
  echo %SCRIPT%
  if "%DID_PUSHD%"=="1" popd
  pause
  exit /b 1
)
echo.
echo === Everything HTTP ツール（サーバーPC用）===
echo  1. このPCの Everything 診断（ID/パスワード）
echo  2. ファイアウォール許可
echo 他PCからの疎通確認は everything-http-remote-check.bat
echo Script: %SCRIPT%
echo Log   : %LOGDIR%everything-http-tool-^<IP末尾6桁^>.log
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode All -Port %PORT% -LogDirectory "%LOGDIR%"
set EC=%ERRORLEVEL%
echo.
echo ----- ログ -----
set "LOGFILE="
if exist "%TEMP%\everything-http-tool-last-log.txt" set /p LOGFILE=<"%TEMP%\everything-http-tool-last-log.txt"
if defined LOGFILE (
  echo LogFile: %LOGFILE%
  echo.
  if exist "%LOGFILE%" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath '%LOGFILE%' -Encoding UTF8"
) else (
  echo フォルダ内の everything-http-tool-*.log を見てください。
)
if "%DID_PUSHD%"=="1" popd
echo.
if %EC% neq 0 (echo 結果: 失敗 %EC%) else (echo 結果: 完了)
pause
exit /b %EC%
