# SuguSearch (すぐサーチ) release
#   build -> (create GitHub repo / git init if needed) -> commit -> push -> GitHub Release (+ SuguSearch.exe, SuguSearch-Setup-<ver>.zip)
#   同じ版を再実行すると、その版のリリースとタグを作り直す
# UTF-8 with BOM. Called from release.bat.
# Log: %TEMP%\sugusearch-release.log (copied to script\release.log at the end; Dropbox locks files in place)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $Root
$Log = Join-Path $env:TEMP "sugusearch-release.log"
$LogCopy = Join-Path $ScriptDir "release.log"
"" | Set-Content -LiteralPath $Log -Encoding UTF8
function G { $ErrorActionPreference = "Continue"; & git @args 2>&1 | ForEach-Object { "$_" } }
function L($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    Write-Host $line
    for ($k = 0; $k -lt 5; $k++) { try { Add-Content -LiteralPath $Log -Value $line -Encoding UTF8 -ErrorAction Stop; break } catch { Start-Sleep -Milliseconds 300 } }
}
function CopyLog { for ($k = 0; $k -lt 10; $k++) { try { Copy-Item -LiteralPath $Log -Destination $LogCopy -Force -ErrorAction Stop; break } catch { Start-Sleep -Milliseconds 500 } } }

try {
    $Owner = "rittyapp"
    $RepoName = "SuguSearch"
    $Repo = "$Owner/$RepoName"
    $Version = (Get-Content -LiteralPath (Join-Path $Root "version.txt") -TotalCount 1).Trim()
    $Tag = "v$Version"
    L "=== SuguSearch release $Tag ==="

    # 1) build
    L "[1/5] build"
    cmd /c "call `"$Root\script\build_exe2.bat`" < nul" | Out-Null
    $Exe = Join-Path $Root "dist\SuguSearch.exe"
    $DistVer = Join-Path $Root "dist\version.txt"
    if (-not (Test-Path -LiteralPath $Exe)) { throw "dist\SuguSearch.exe がありません" }
    if ((Get-Item -LiteralPath $Exe).LastWriteTime -lt (Get-Date).AddMinutes(-15)) { throw "EXE が更新されていません（ビルド失敗の可能性）" }
    if ((Get-Content -LiteralPath $DistVer -TotalCount 1).Trim() -ne $Version) { throw "dist\version.txt が $Version ではありません" }
    $Zip = Join-Path $Root "dist\SuguSearch-Setup-$Version.zip"
    if (-not (Test-Path -LiteralPath $Zip)) { throw "配布用 zip がありません: $Zip" }
    L ("  OK {0:N0} bytes" -f (Get-Item -LiteralPath $Exe).Length)

    # 2) token from git credential manager
    L "[2/5] GitHub token"
    $env:GIT_TERMINAL_PROMPT = "0"
    $ErrorActionPreference = "Continue"; $cred = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null; $ErrorActionPreference = "Stop"
    $Token = ($cred | Where-Object { $_ -like "password=*" } | Select-Object -First 1) -replace "^password=", ""
    if (-not $Token) { throw "GitHub の資格情報が取得できません（git credential fill）" }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $H = @{ Authorization = "Bearer $Token"; Accept = "application/vnd.github+json"; "User-Agent" = "SuguSearch-release"; "X-GitHub-Api-Version" = "2022-11-28" }
    function PostJson($uri, $obj) {
        $json = $obj | ConvertTo-Json
        Invoke-RestMethod -Uri $uri -Headers $H -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($json))
    }

    # 3) repository (create once, public)
    L "[3/5] repository $Repo"
    $exists = $true
    try { Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo" -Headers $H -Method Get | Out-Null } catch { $exists = $false }
    if (-not $exists) {
        $me = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $H -Method Get
        $spec = @{ name = $RepoName; description = "すぐサーチ — Everything (voidtools) 検索クライアント"; private = $false; has_wiki = $false }
        if ([string]::Equals([string]$me.login, $Owner, [StringComparison]::OrdinalIgnoreCase)) {
            PostJson "https://api.github.com/user/repos" $spec | Out-Null
        } else {
            PostJson "https://api.github.com/orgs/$Owner/repos" $spec | Out-Null
        }
        L "  created (public)"
    } else { L "  exists" }

    # 4) git init / commit / push
    L "[4/5] commit + push"
    if (-not (Test-Path -LiteralPath (Join-Path $Root ".git"))) {
        G init | ForEach-Object { L "  $_" }
        G checkout -b main | Out-Null
        G remote add origin "https://github.com/$Repo.git" | Out-Null
    }
    $MsgFile = Join-Path $ScriptDir "release-msg.txt"
    if (Test-Path -LiteralPath $MsgFile) {
        G add -A | Out-Null
        G commit -F $MsgFile | ForEach-Object { L "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "git commit 失敗" }
        Remove-Item -LiteralPath $MsgFile
    }
    G push -u origin main | ForEach-Object { L "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "git push 失敗" }

    # 5) release + assets
    L "[5/5] release $Tag"
    $NotesFile = Join-Path $ScriptDir "release-notes.md"
    $Notes = if (Test-Path -LiteralPath $NotesFile) { [IO.File]::ReadAllText($NotesFile, [Text.Encoding]::UTF8) } else { "" }
    # 同じ版を出し直す場合は、旧リリースとタグを消して最新コミットで作り直す
    $old = $null
    try { $old = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag" -Headers $H -Method Get } catch { }
    if ($old) {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/$($old.id)" -Headers $H -Method Delete | Out-Null
        L "  旧 $Tag リリースを削除"
    }
    try { Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/git/refs/tags/$Tag" -Headers $H -Method Delete | Out-Null; L "  旧 $Tag タグを削除" } catch { }
    $rel = $null
    if (-not $rel) {
        $rel = PostJson "https://api.github.com/repos/$Repo/releases" @{ tag_name = $Tag; target_commitish = "main"; name = "すぐサーチ $Version"; body = [string]$Notes; draft = $false; prerelease = $false }
    }
    foreach ($f in @($Exe, $Zip)) {
        $name = Split-Path -Leaf $f
        foreach ($a in @($rel.assets)) { if ($a -and $a.name -eq $name) { Invoke-RestMethod -Uri $a.url -Headers $H -Method Delete | Out-Null } }
        $up = "https://uploads.github.com/repos/$Repo/releases/$($rel.id)/assets?name=$name"
        $r = Invoke-RestMethod -Uri $up -Headers $H -Method Post -ContentType "application/octet-stream" -InFile $f
        L "  uploaded $($r.name) ($($r.size) bytes)"
    }
    L "RELEASE OK: $($rel.html_url)"
    CopyLog
}
catch {
    L "ERROR: $($_.Exception.Message)"
    try { $rd = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); L ("  " + $rd.ReadToEnd()) } catch { }
    CopyLog
    exit 1
}
