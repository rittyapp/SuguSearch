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

echo [1/3] アイコン生成...
py -3 "%ROOT%\script\build_icon.py"
if errorlevel 1 (
  echo ERROR: build_icon.py に失敗しました
  goto :error
)
if not exist "%ROOT%\assets\sugusearch.ico" (
  echo ERROR: assets\sugusearch.ico がありません
  goto :error
)

echo [2/3] PyInstaller で EXE 作成...
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

echo [3/3] README / version.txt を dist へ...
copy /Y "%ROOT%\README.MD" "%ROOT%\dist\README.MD" >nul
if exist "%ROOT%\version.txt" (
  copy /Y "%ROOT%\version.txt" "%ROOT%\dist\version.txt" >nul
) else (
  echo 1.0.0> "%ROOT%\dist\version.txt"
)

echo.
echo ==============================
echo  BUILD OK
echo  %ROOT%\dist\SuguSearch.exe
echo  Next: script\setup.bat
echo ==============================
echo.
pause
exit /b 0

:error
echo.
echo ビルドに失敗しました。
pause
exit /b 1
