@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

echo === すぐサーチ EXE ビルド ===
echo 作業フォルダ: %ROOT%
echo.

REM 起動中の EXE があると上書きできない
taskkill /F /IM SuguSearch.exe >nul 2>&1

echo [1/4] アイコン生成...
py -3 "%ROOT%\script\build_icon.py"
if errorlevel 1 (
  echo ERROR: build_icon.py に失敗しました
  goto :error
)
if not exist "%ROOT%\assets\sugusearch.ico" (
  echo ERROR: assets\sugusearch.ico がありません
  goto :error
)

echo [2/4] PyInstaller で EXE 作成...
REM --specpath を使うため、--icon / --add-data は絶対パスで渡す
py -3 -m PyInstaller --noconfirm --clean --windowed --onefile --name SuguSearch --icon "%ROOT%\assets\sugusearch.ico" --add-data "%ROOT%\assets\sugusearch.ico;." --add-data "%ROOT%\version.txt;." --hidden-import win32timezone --hidden-import app_paths --hidden-import self_update --distpath "%ROOT%\dist" --workpath "%ROOT%\build" --specpath "%ROOT%\build" "%ROOT%\src\sugusearch.py"
if errorlevel 1 (
  echo ERROR: PyInstaller に失敗しました
  echo   py -3 -m pip install pyinstaller pillow pywin32
  echo   を実行してください。EXE が実行中でないかも確認してください。
  goto :error
)

if not exist "%ROOT%\dist\SuguSearch.exe" (
  echo ERROR: dist\SuguSearch.exe が見つかりません
  goto :error
)

echo [3/4] README / version.txt を dist へ...
copy /Y "%ROOT%\README.MD" "%ROOT%\dist\README.MD" >nul
if exist "%ROOT%\version.txt" (
  copy /Y "%ROOT%\version.txt" "%ROOT%\dist\version.txt" >nul
) else (
  echo 1.0.0> "%ROOT%\dist\version.txt"
)

echo [4/4] 配布用 zip を作成...
set /p VER=<"%ROOT%\version.txt"
set "PKG=%ROOT%\dist\SuguSearch-Setup"
set "ZIP=%ROOT%\dist\SuguSearch-Setup-%VER%.zip"
if exist "%PKG%" rmdir /s /q "%PKG%"
if exist "%ZIP%" del /f /q "%ZIP%"
REM 利用者に見せるのは setup.bat だけ。中身は files\ に入れる
mkdir "%PKG%\files"
copy /Y "%ROOT%\script\setup.bat" "%PKG%\" >nul
copy /Y "%ROOT%\dist\SuguSearch.exe" "%PKG%\files\" >nul
copy /Y "%ROOT%\script\setup.ps1" "%PKG%\files\" >nul
powershell -NoProfile -Command "Compress-Archive -LiteralPath '%PKG%' -DestinationPath '%ZIP%' -Force"
if not exist "%ZIP%" (
  echo ERROR: 配布用 zip を作れませんでした
  goto :error
)

echo.
echo ==============================
echo  BUILD OK
echo  %ROOT%\dist\SuguSearch.exe
echo  %ZIP%
echo  （配布: zip を展開して setup.bat をダブルクリック）
echo ==============================
echo.
pause
exit /b 0

:error
echo.
echo ビルドに失敗しました。
pause
exit /b 1
