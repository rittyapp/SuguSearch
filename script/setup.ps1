# SuguSearch (すぐサーチ) setup — any Windows (no Python required after install)
# Save as UTF-8 with BOM. Called from setup.bat.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$VersionFile = Join-Path $Root "version.txt"
$Version = "1.2.0"
if (Test-Path -LiteralPath $VersionFile) {
    $Version = (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim()
}

$ExeSrc = Join-Path $Root "dist\SuguSearch.exe"
if (-not (Test-Path -LiteralPath $ExeSrc)) {
    throw "dist\SuguSearch.exe not found. Run script\build_exe2.bat first."
}

$InstallRoot = Join-Path $env:LOCALAPPDATA "SuguSearch"
$Current = Join-Path $InstallRoot "current"
$Data = Join-Path $InstallRoot "data"
$Previous = Join-Path $InstallRoot "previous"
$Staging = Join-Path $InstallRoot "staging"

Write-Host ""
Write-Host "=== すぐサーチ setup ==="
Write-Host "version: $Version"
Write-Host "from   : $ExeSrc"
Write-Host "to     : $Current"
Write-Host ""

New-Item -ItemType Directory -Force -Path $Current, $Data, $Previous, $Staging | Out-Null

# Keep previous if upgrading via setup
$DestExe = Join-Path $Current "SuguSearch.exe"
if (Test-Path -LiteralPath $DestExe) {
    $Bak = Join-Path $Previous "SuguSearch.exe"
    Copy-Item -LiteralPath $DestExe -Destination $Bak -Force
    $PrevVer = Join-Path $Current "version.txt"
    if (Test-Path -LiteralPath $PrevVer) {
        Copy-Item -LiteralPath $PrevVer -Destination (Join-Path $Previous "version.txt") -Force
    }
}

Copy-Item -LiteralPath $ExeSrc -Destination $DestExe -Force
Set-Content -LiteralPath (Join-Path $Current "version.txt") -Value $Version -Encoding ASCII

# Migrate settings from next-to-exe / src if data empty
$DataSettings = Join-Path $Data "settings.json"
if (-not (Test-Path -LiteralPath $DataSettings)) {
    foreach ($cand in @(
        (Join-Path $env:LOCALAPPDATA "Everysearch\data\settings.json"),
        (Join-Path $Root "dist\settings.json"),
        (Join-Path $Root "src\settings.json"),
        (Join-Path $Root "settings.json")
    )) {
        if (Test-Path -LiteralPath $cand) {
            Copy-Item -LiteralPath $cand -Destination $DataSettings -Force
            Write-Host "settings migrated: $cand"
            break
        }
    }
}

# Desktop shortcut -> current\SuguSearch.exe
$Desktop = [Environment]::GetFolderPath("Desktop")
$LnkPath = Join-Path $Desktop "すぐサーチ.lnk"
$Wsh = New-Object -ComObject WScript.Shell
$Sc = $Wsh.CreateShortcut($LnkPath)
$Sc.TargetPath = $DestExe
$Sc.WorkingDirectory = $Current
$Sc.Description = "すぐサーチ $Version"
$Ico = Join-Path $Root "assets\sugusearch.ico"
if (Test-Path -LiteralPath $Ico) {
    $Sc.IconLocation = "$Ico,0"
}
$Sc.Save()

# Start Menu
$StartDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $StartDir | Out-Null
$StartLnk = Join-Path $StartDir "すぐサーチ.lnk"
$Sc2 = $Wsh.CreateShortcut($StartLnk)
$Sc2.TargetPath = $DestExe
$Sc2.WorkingDirectory = $Current
$Sc2.Description = "すぐサーチ $Version"
if (Test-Path -LiteralPath $Ico) { $Sc2.IconLocation = "$Ico,0" }
$Sc2.Save()

Write-Host "OK"
Write-Host "shortcut: $LnkPath"
Write-Host "exe     : $DestExe"
Write-Host ""
