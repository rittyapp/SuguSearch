@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

echo === すぐサーチ コミット ===
echo リポジトリ: %ROOT%

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo ERROR: git リポジトリではありません
  goto :error
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
echo ブランチ: %BRANCH%
echo.

echo --- 変更内容 ---
git status --short
echo.

REM 変更が無ければ何もしない
for /f "delims=" %%c in ('git status --porcelain') do goto :haschange
echo コミットする変更はありません。
goto :done

:haschange
set "MSG=%~1"
if "%MSG%"=="" set /p "MSG=コミットメッセージ（空で中止・二重引用符は使わない）: "
if "%MSG%"=="" (
  echo 中止しました。
  goto :done
)

git add -A
if errorlevel 1 goto :error
git commit -m "%MSG%"
if errorlevel 1 goto :error

echo.
echo --- 最近のコミット ---
git log --oneline -5
echo.
echo コミットしました。push はしていません。
echo GitHub へ上げる場合: git push origin %BRANCH%

:done
echo.
pause
exit /b 0

:error
echo.
echo 失敗しました。
pause
exit /b 1
