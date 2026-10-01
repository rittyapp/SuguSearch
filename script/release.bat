@echo off
chcp 932 >nul
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release.ps1"
chcp 932 >nul
echo.
pause
