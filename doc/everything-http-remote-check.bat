@echo off
chcp 932 >nul
setlocal EnableExtensions
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
echo === Everything HTTP 疎通チェック（クライアントPC用）===
echo このPCから、指定サーバーの Everything HTTP へ届くか調べます。
echo サーバー上の設定ファイルやプロセスは見えません。
echo.
set "TARGET=%~1"
set "PORT=%~2"
set "USER=%~3"
set "PASS=%~4"
if "%TARGET%"=="" set /p TARGET=サーバーIP: 
if "%TARGET%"=="" (
  echo IPが空です。
  pause
  exit /b 1
)
if "%PORT%"=="" set "PORT=8888"
if not "%~2"=="" goto :have_port
set /p PORT_IN=ポート [%PORT%]: 
if not "%PORT_IN%"=="" set "PORT=%PORT_IN%"
:have_port
if "%USER%"=="" set /p USER=ユーザー名（空可）: 
if "%PASS%"=="" set /p PASS=パスワード（空可）: 
echo.
echo Target: %TARGET%:%PORT%  User: %USER%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Mode RemoteCheck -TargetHost "%TARGET%" -Port %PORT% -Username "%USER%" -Password "%PASS%" -LogDirectory "%LOGDIR%"
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
  echo フォルダ内の everything-http-remote-*.log を見てください。
)
if "%DID_PUSHD%"=="1" popd
echo.
if %EC% neq 0 (echo 結果: 失敗 %EC%) else (echo 結果: 完了)
pause
exit /b %EC%
