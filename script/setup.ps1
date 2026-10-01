# SuguSearch (すぐサーチ) setup — any Windows (no Python required)
# UTF-8 with BOM. Called from setup.bat.
# Works in two layouts:
#   配布 zip : setup.bat / setup.ps1 / SuguSearch.exe が同じフォルダ
#   開発     : script\setup.ps1 と dist\SuguSearch.exe
# 版数は EXE 内蔵（APP_VERSION）を正とするので version.txt は使わない。

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DevRoot = Split-Path -Parent $ScriptDir

$ExeSrc = $null
foreach ($cand in @((Join-Path $ScriptDir "SuguSearch.exe"), (Join-Path $DevRoot "dist\SuguSearch.exe"))) {
    if (Test-Path -LiteralPath $cand) { $ExeSrc = $cand; break }
}
if (-not $ExeSrc) {
    throw "SuguSearch.exe が見つかりません。zip を展開してから setup.bat を実行してください。"
}

$InstallRoot = Join-Path $env:LOCALAPPDATA "SuguSearch"
$Current = Join-Path $InstallRoot "current"
$Data = Join-Path $InstallRoot "data"
$Previous = Join-Path $InstallRoot "previous"
$Staging = Join-Path $InstallRoot "staging"

Write-Host ""
Write-Host "=== すぐサーチ セットアップ ==="
Write-Host "from : $ExeSrc"
Write-Host "to   : $Current"
Write-Host ""

New-Item -ItemType Directory -Force -Path $Current, $Data, $Previous, $Staging | Out-Null
$DestExe = Join-Path $Current "SuguSearch.exe"

# 起動中なら終了してもらう（上書きできないため）
$running = Get-Process -Name "SuguSearch" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "すぐサーチを終了します..."
    $running | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# 上書き前の EXE を previous に残す
if (Test-Path -LiteralPath $DestExe) {
    Copy-Item -LiteralPath $DestExe -Destination (Join-Path $Previous "SuguSearch.exe") -Force
}
Copy-Item -LiteralPath $ExeSrc -Destination $DestExe -Force
# 古い version.txt が残っていると EXE 内蔵の版より優先されるので消す
$OldVer = Join-Path $Current "version.txt"
if (Test-Path -LiteralPath $OldVer) { Remove-Item -LiteralPath $OldVer -Force }

# 設定の引き継ぎ（data が空のときだけ）: 旧 Everysearch → 開発用の設定
$DataSettings = Join-Path $Data "settings.json"
if (-not (Test-Path -LiteralPath $DataSettings)) {
    foreach ($cand in @(
        (Join-Path $env:LOCALAPPDATA "Everysearch\data\settings.json"),
        (Join-Path $DevRoot "dist\settings.json"),
        (Join-Path $DevRoot "src\settings.json")
    )) {
        if (Test-Path -LiteralPath $cand) {
            Copy-Item -LiteralPath $cand -Destination $DataSettings -Force
            Write-Host "設定を引き継ぎました: $cand"
            break
        }
    }
}

# ショートカット（アイコンは EXE に埋め込んだもの）
$Wsh = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$StartDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $StartDir | Out-Null
foreach ($lnk in @((Join-Path $Desktop "すぐサーチ.lnk"), (Join-Path $StartDir "すぐサーチ.lnk"))) {
    $Sc = $Wsh.CreateShortcut($lnk)
    $Sc.TargetPath = $DestExe
    $Sc.WorkingDirectory = $Current
    $Sc.Description = "すぐサーチ"
    $Sc.IconLocation = "$DestExe,0"
    $Sc.Save()
}

Write-Host "OK"
Write-Host "デスクトップの「すぐサーチ」から起動してください。"
Write-Host ""
