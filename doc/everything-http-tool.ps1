# Everything HTTP tool: server diagnose+FW, or remote reachability from another PC
# Server PC: everything-http-tool.bat
# Other PC:  everything-http-remote-check.bat
# Log: one file next to script (overwrite). Save as UTF-8 with BOM.

param(
    [ValidateSet("All", "Inspect", "Firewall", "RemoteCheck")]
    [string]$Mode = "All",
    [ValidateRange(1, 65535)]
    [int]$Port = 8888,
    [string]$TargetHost = "",
    [string]$Username = "",
    [string]$Password = "",
    [string]$LogDirectory = "",
    [switch]$HidePassword,
    # Parent skips final line when elevated child writes it
    [switch]$SkipFinalVerdict
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Get-SelfPath {
    if ($PSCommandPath) { return $PSCommandPath }
    if ($MyInvocation.MyCommand.Path) { return $MyInvocation.MyCommand.Path }
    return "(unknown)"
}
function Test-DirWritable([string]$Dir) {
    if (-not $Dir) { return $false }
    try {
        if (-not (Test-Path -LiteralPath $Dir)) { New-Item -ItemType Directory -Force -Path $Dir | Out-Null }
        $probe = Join-Path $Dir ("probe-" + [Guid]::NewGuid().ToString("n") + ".tmp")
        [IO.File]::WriteAllText($probe, "ok")
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch { return $false }
}
function Get-SelfIpv4List {
    $list = @()
    try {
        foreach ($a in @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" })) {
            $list += [pscustomobject]@{ Alias = [string]$a.InterfaceAlias; IP = [string]$a.IPAddress; Prefix = [int]$a.PrefixLength }
        }
    } catch {}
    return $list
}
function Get-PreferredIpv4 {
    $ips = @(Get-SelfIpv4List)
    if ($ips.Count -eq 0) { return "" }
    $lan = @($ips | Where-Object { $_.IP -notlike "169.254.*" })
    if ($lan.Count -gt 0) { return [string]$lan[0].IP }
    return [string]$ips[0].IP
}
function Get-IpNameSuffix {
    $ip = Get-PreferredIpv4
    if ($ip -match '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$') {
        $padded = "{0:D3}{1:D3}{2:D3}{3:D3}" -f ([int]$Matches[1]),([int]$Matches[2]),([int]$Matches[3]),([int]$Matches[4])
        return $padded.Substring($padded.Length - 6)
    }
    return "000000"
}
function Resolve-LogDirectory([string]$Preferred) {
    $candidates = @()
    if ($Preferred) { $candidates += $Preferred.TrimEnd('\', '/') }
    $self = Get-SelfPath
    if ($self -ne "(unknown)") {
        $selfDir = [IO.Path]::GetDirectoryName($self)
        $temp = [IO.Path]::GetTempPath().TrimEnd('\', '/')
        if ($selfDir -and ($selfDir.TrimEnd('\', '/') -ne $temp)) { $candidates += $selfDir }
    }
    $candidates += (Join-Path $env:LOCALAPPDATA "SuguSearch\logs")
    foreach ($c in $candidates) { if ($c -and (Test-DirWritable $c)) { return $c } }
    return (Join-Path $env:TEMP "SuguSearch-logs")
}
function Write-LogLine([string]$Path, [AllowEmptyString()][string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message"
    if (-not (Test-Path -LiteralPath $Path)) {
        [IO.File]::WriteAllText($Path, "", (New-Object System.Text.UTF8Encoding $true))
    }
    [IO.File]::AppendAllText($Path, ($line + [Environment]::NewLine), (New-Object System.Text.UTF8Encoding $false))
    Write-Host $Message
}
function Save-TempPointer([string]$Path) {
    Set-Content -LiteralPath (Join-Path $env:TEMP "everything-http-tool-last-log.txt") -Value $Path -Encoding ASCII
}
function Read-IniMap([string]$IniPath) {
    $map = @{}
    if (-not (Test-Path -LiteralPath $IniPath)) { return $map }
    $encodings = @(
        (New-Object System.Text.UTF8Encoding $false),
        [System.Text.Encoding]::GetEncoding(932),
        [System.Text.Encoding]::Default
    )
    $bestLines = $null; $bestScore = -1
    foreach ($enc in $encodings) {
        try {
            $lines = [IO.File]::ReadAllLines($IniPath, $enc)
            $score = 0
            foreach ($line in $lines) {
                if ($line -match '^http_server_') { $score += 10 }
                if ($line -match '^[a-z0-9_]+=') { $score += 1 }
            }
            if ($score -gt $bestScore) { $bestScore = $score; $bestLines = $lines }
        } catch {}
    }
    if ($null -eq $bestLines) { $bestLines = [IO.File]::ReadAllLines($IniPath) }
    foreach ($line in $bestLines) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith(";") -or $t.StartsWith("#") -or $t.StartsWith("[")) { continue }
        $eq = $t.IndexOf("=")
        if ($eq -lt 1) { continue }
        $map[$t.Substring(0, $eq).Trim()] = $t.Substring($eq + 1)
    }
    return $map
}
function Get-IniValue($Map, [string]$Key, [string]$Default = "") {
    if ($null -ne $Map -and $Map.ContainsKey($Key)) { return [string]$Map[$Key] }
    return $Default
}
function Format-Secret([string]$Value, [bool]$Hide) {
    if ($null -eq $Value -or $Value -eq "") { return "(empty / not set)" }
    if ($Hide) { return ("(set, length={0})" -f $Value.Length) }
    return $Value
}
function Get-FileVersionSafe([string]$Path) {
    try {
        if ($Path -and (Test-Path -LiteralPath $Path)) {
            return [string](Get-Item -LiteralPath $Path).VersionInfo.FileVersion
        }
    } catch {}
    return ""
}

# ---- log path ----
$LogDir = Resolve-LogDirectory $LogDirectory
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if ($Mode -eq "RemoteCheck") {
    $suffix = "000000"
    if ($TargetHost -match '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$') {
        $padded = "{0:D3}{1:D3}{2:D3}{3:D3}" -f ([int]$Matches[1]),([int]$Matches[2]),([int]$Matches[3]),([int]$Matches[4])
        $suffix = $padded.Substring($padded.Length - 6)
    } elseif ($TargetHost) {
        $safe = ($TargetHost -replace '[^a-zA-Z0-9.-]', '_')
        if ($safe.Length -gt 24) { $safe = $safe.Substring(0, 24) }
        $suffix = $safe
    }
    $LogPath = Join-Path $LogDir "everything-http-remote-$suffix.log"
} else {
    $ip6 = Get-IpNameSuffix
    $LogPath = Join-Path $LogDir "everything-http-tool-$ip6.log"
}
if ($Mode -ne "Firewall") {
    if (Test-Path -LiteralPath $LogPath) { Remove-Item -LiteralPath $LogPath -Force }
}

$script:HttpPort = $Port
$script:HttpUser = ""
$script:HttpPass = ""
$script:HttpEnabled = ""
$script:HttpBind = ""
$script:PrimaryIp = Get-PreferredIpv4
$exitCode = 0

function Invoke-Inspect {
    Write-LogLine $LogPath "=== Everything HTTP tool ==="
    Write-LogLine $LogPath "Mode       : Inspect"
    Write-LogLine $LogPath "WARNING    : Log may contain HTTP username/password from Everything.ini."
    Write-LogLine $LogPath "Computer   : $env:COMPUTERNAME"
    Write-LogLine $LogPath "User       : $env:USERDOMAIN\$env:USERNAME"
    Write-LogLine $LogPath "APPDATA    : $env:APPDATA"
    Write-LogLine $LogPath "Script     : $(Get-SelfPath)"
    Write-LogLine $LogPath "LogFile    : $LogPath"
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- This PC IPv4 ---"
    $ips = @(Get-SelfIpv4List)
    if ($ips.Count -eq 0) { Write-LogLine $LogPath "(none)" }
    else {
        foreach ($i in $ips) {
            $pref = if ($i.Prefix -gt 0) { "/$($i.Prefix)" } else { "" }
            Write-LogLine $LogPath ("  {0,-40} {1}{2}" -f $i.Alias, $i.IP, $pref)
        }
    }
    Write-LogLine $LogPath "Primary hint: $($script:PrimaryIp)"
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- Network profile ---"
    try {
        foreach ($pr in @(Get-NetConnectionProfile -ErrorAction Stop)) {
            Write-LogLine $LogPath ("  {0,-40} Name={1}  Category={2}" -f $pr.InterfaceAlias, $pr.Name, $pr.NetworkCategory)
        }
    } catch { Write-LogLine $LogPath "  (unavailable)" }
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- Everything service / install ---"
    $installLoc = ""
    try {
        $svc = Get-Service -Name "Everything" -ErrorAction SilentlyContinue
        if ($svc) { Write-LogLine $LogPath ("Service: {0} / {1}" -f $svc.Status, $svc.StartType) }
        else { Write-LogLine $LogPath "Service: (not found)" }
    } catch {}
    try {
        $reg = Get-ItemProperty "HKLM:\SOFTWARE\voidtools\Everything" -ErrorAction SilentlyContinue
        if ($reg) {
            $installLoc = [string]$reg.InstallLocation
            Write-LogLine $LogPath ("InstallLocation: {0}" -f $reg.InstallLocation)
            Write-LogLine $LogPath ("InstallAppData : {0}" -f $reg.InstallAppData)
        }
    } catch {}
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- Running Everything.exe ---"
    $procs = @()
    try { $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'Everything.exe'" -ErrorAction Stop) } catch {}
    if ($procs.Count -eq 0) { Write-LogLine $LogPath "  (not running)" }
    else {
        foreach ($p in $procs) {
            $path = [string]$p.ExecutablePath
            if (-not $path) { try { $path = [string](Get-Process -Id $p.ProcessId -EA SilentlyContinue).Path } catch {} }
            Write-LogLine $LogPath ("  PID={0} Version={1}" -f $p.ProcessId, (Get-FileVersionSafe $path))
            Write-LogLine $LogPath ("    Path: {0}" -f $(if ($path) { $path } else { "(unknown)" }))
            Write-LogLine $LogPath ("    Cmd : {0}" -f $(if ($p.CommandLine) { $p.CommandLine } else { "(n/a)" }))
        }
    }
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- Everything.ini (ID/password) ---"
    $cands = New-Object System.Collections.Generic.List[string]
    foreach ($c in @(
        (Join-Path $env:APPDATA "Everything\Everything.ini"),
        (Join-Path $env:APPDATA "Everything\Everything-1.5a.ini"),
        (Join-Path $env:LOCALAPPDATA "Everything\Everything.ini"),
        (Join-Path ${env:ProgramFiles} "Everything\Everything.ini"),
        (Join-Path ${env:ProgramFiles(x86)} "Everything\Everything.ini")
    )) { if ($c) { [void]$cands.Add($c) } }
    if ($installLoc) { [void]$cands.Add((Join-Path $installLoc "Everything.ini")) }
    foreach ($p in $procs) {
        $ep = [string]$p.ExecutablePath
        if ($ep) {
            $d = [IO.Path]::GetDirectoryName($ep)
            if ($d) {
                [void]$cands.Add((Join-Path $d "Everything.ini"))
                [void]$cands.Add((Join-Path $d "Everything-1.5a.ini"))
            }
        }
    }
    $seen = @{}; $found = @()
    foreach ($c in $cands) {
        $k = $c.ToLowerInvariant()
        if ($seen.ContainsKey($k)) { continue }
        $seen[$k] = $true
        if (Test-Path -LiteralPath $c) {
            $found += $c
            $it = Get-Item -LiteralPath $c
            Write-LogLine $LogPath ("  FOUND {0} ({1} bytes)" -f $c, $it.Length)
        } else {
            Write-LogLine $LogPath ("  miss  {0}" -f $c)
        }
    }
    Write-LogLine $LogPath ""

    $bestScore = -1
    $primaryIni = ""
    if ($found.Count -eq 0) {
        Write-LogLine $LogPath "  No ini — cannot read username/password."
        Write-LogLine $LogPath "  Run as the same Windows user that runs Everything."
    } else {
        foreach ($ini in $found) {
            Write-LogLine $LogPath ("INI: {0}" -f $ini)
            $map = Read-IniMap $ini
            $en = Get-IniValue $map "http_server_enabled"
            $po = Get-IniValue $map "http_server_port"
            $bi = Get-IniValue $map "http_server_bindings"
            $us = Get-IniValue $map "http_server_username"
            $pw = Get-IniValue $map "http_server_password"
            $ah = Get-IniValue $map "allow_http_server"
            Write-LogLine $LogPath ("  http_server_enabled  = {0}" -f $(if ($en -ne "") { $en } else { "(missing)" }))
            Write-LogLine $LogPath ("  http_server_port     = {0}" -f $(if ($po -ne "") { $po } else { "(missing)" }))
            Write-LogLine $LogPath ("  http_server_bindings = {0}" -f $(if ($bi -ne "") { $bi } else { "(empty)" }))
            Write-LogLine $LogPath ("  http_server_username = {0}" -f $(if ($us -ne "") { $us } else { "(empty)" }))
            Write-LogLine $LogPath ("  http_server_password = {0}" -f (Format-Secret $pw $HidePassword))
            if ($ah -ne "") { Write-LogLine $LogPath ("  allow_http_server    = {0}" -f $ah) }
            $raw = Get-Content -LiteralPath $ini -ErrorAction SilentlyContinue |
                Where-Object { $_ -match '^http_server_(enabled|port|username|password|bindings)=' }
            if ($raw) {
                Write-LogLine $LogPath "  raw:"
                foreach ($line in $raw) {
                    if ($HidePassword -and $line -match '^http_server_password=') { $line = "http_server_password=(hidden)" }
                    Write-LogLine $LogPath ("    {0}" -f $line)
                }
            }
            $score = 0
            if ($en -ne "" -or $po -ne "" -or $us -ne "" -or $pw -ne "") { $score += 10 }
            if ($en -eq "1") { $score += 5 }
            if ($ini -like "*\AppData\Roaming\Everything\*") { $score += 20 }
            if ($us -ne "" -or $pw -ne "") { $score += 3 }
            if ($score -gt $bestScore) {
                $bestScore = $score
                $primaryIni = $ini
                $script:HttpEnabled = $en
                $script:HttpBind = $bi
                $script:HttpUser = $us
                $script:HttpPass = $pw
                if ($po -ne "") { try { $script:HttpPort = [int]$po } catch { $script:HttpPort = $Port } }
            }
            Write-LogLine $LogPath ""
        }
    }

    Write-LogLine $LogPath "--- Primary (for SuguSearch) ---"
    if ($primaryIni) {
        Write-LogLine $LogPath "Primary ini: $primaryIni"
        Write-LogLine $LogPath ("Host suggestion : {0}" -f $(if ($script:PrimaryIp) { $script:PrimaryIp } else { "(LAN IP)" }))
        Write-LogLine $LogPath ("Port            : {0}" -f $script:HttpPort)
        Write-LogLine $LogPath ("Username        : {0}" -f $(if ($script:HttpUser) { $script:HttpUser } else { "(blank)" }))
        Write-LogLine $LogPath ("Password        : {0}" -f (Format-Secret $script:HttpPass $HidePassword))
    } else {
        Write-LogLine $LogPath "(no primary HTTP settings)"
    }
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- Listening / probe ---"
    $ports = @(80, 88, 8080, 8888)
    if ($ports -notcontains $script:HttpPort) { $ports += $script:HttpPort }
    $owners = @{}
    try {
        foreach ($l in @(Get-NetTCPConnection -State Listen -EA Stop | Where-Object { $ports -contains $_.LocalPort })) {
            $op = [int]$l.OwningProcess
            $nm = ""; try { $nm = (Get-Process -Id $op -EA SilentlyContinue).ProcessName } catch {}
            Write-LogLine $LogPath ("  {0}:{1} PID={2} {3}" -f $l.LocalAddress, $l.LocalPort, $op, $nm)
            $owners["$($l.LocalPort)"] = $op
        }
        if ($owners.Count -eq 0) { Write-LogLine $LogPath "  (nothing listening on $($ports -join ', '))" }
    } catch { Write-LogLine $LogPath "  (listen query failed)" }
    try {
        $tnc = Test-NetConnection -ComputerName "127.0.0.1" -Port $script:HttpPort -WarningAction SilentlyContinue
        Write-LogLine $LogPath ("127.0.0.1:{0} Tcp={1}" -f $script:HttpPort, $tnc.TcpTestSucceeded)
    } catch {}
    function Probe([string]$Url, [string]$U, [string]$P) {
        try {
            $h = @{}
            if ($U -or $P) {
                $h["Authorization"] = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${U}:${P}"))
            }
            $r = Invoke-WebRequest -Uri $Url -Headers $h -TimeoutSec 5 -UseBasicParsing
            return "HTTP $([int]$r.StatusCode) OK"
        } catch {
            if ($_.Exception.Response) { return "HTTP $([int]$_.Exception.Response.StatusCode)" }
            return "FAIL: $($_.Exception.Message)"
        }
    }
    $url = "http://127.0.0.1:$($script:HttpPort)/"
    Write-LogLine $LogPath ("No auth : {0}" -f (Probe $url "" ""))
    if ($script:HttpUser -or $script:HttpPass) {
        Write-LogLine $LogPath ("With auth: {0}" -f (Probe $url $script:HttpUser $script:HttpPass))
    } else {
        Write-LogLine $LogPath "With auth: (skipped)"
    }
    Write-LogLine $LogPath ""

    $listening = $owners.ContainsKey("$($script:HttpPort)")
    $yes = ($script:HttpEnabled -eq "1") -and $listening -and ($procs.Count -gt 0)
    Write-LogLine $LogPath ("Likely SuguSearch target: {0}" -f $(if ($yes) { "YES" } else { "NO / incomplete" }))
    if ($script:HttpBind -eq "127.0.0.1") {
        Write-LogLine $LogPath "NOTE: bindings=127.0.0.1 — other PCs cannot connect."
    }
    Write-LogLine $LogPath ""
}

function Invoke-Firewall {
    param([int]$UsePort)
    Write-LogLine $LogPath "=== Firewall allow ==="
    Write-LogLine $LogPath "Mode       : Firewall"
    Write-LogLine $LogPath "IsAdmin    : $(Test-IsAdmin)"
    Write-LogLine $LogPath "Port       : TCP $UsePort"
    Write-LogLine $LogPath ""

    if (-not (Test-IsAdmin)) {
        Write-LogLine $LogPath "STATUS: elevating for firewall (UAC)..."
        Save-TempPointer $LogPath
        $self = Get-SelfPath
        if ($self -eq "(unknown)" -or -not (Test-Path -LiteralPath $self)) {
            Write-LogLine $LogPath "ERROR: cannot locate script for elevation"
            return 2
        }
        $local = Join-Path $env:TEMP "everything-http-tool.ps1"
        Copy-Item -LiteralPath $self -Destination $local -Force
        $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$local`" -Mode Firewall -Port $UsePort -LogDirectory `"$LogDir`""
        if ($HidePassword) { $arg += " -HidePassword" }
        try {
            $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arg -PassThru -Wait
            if ($null -eq $proc) { Write-LogLine $LogPath "ERROR: UAC canceled?"; return 3 }
            Save-TempPointer $LogPath
            Write-Host "Elevated exit: $([int]$proc.ExitCode)"
            return [int]$proc.ExitCode
        } catch {
            Write-LogLine $LogPath "ERROR: $($_.Exception.Message)"
            return 3
        }
    }

    $displayName = "Everything HTTP $UsePort"
    Write-LogLine $LogPath "DisplayName: $displayName"
    $existing = @(Get-NetFirewallRule -DisplayName $displayName -ErrorAction SilentlyContinue)
    Write-LogLine $LogPath "Existing rules: $($existing.Count)"
    if ($existing.Count -gt 0) { $existing | Remove-NetFirewallRule }
    New-NetFirewallRule -DisplayName $displayName -Direction Inbound -Protocol TCP -LocalPort $UsePort `
        -Action Allow -Profile Private `
        -Description "Allow LAN clients to reach Everything HTTP (SuguSearch)." | Out-Null
    $created = @(Get-NetFirewallRule -DisplayName $displayName -ErrorAction SilentlyContinue)
    if ($created.Count -eq 0) {
        Write-LogLine $LogPath "ERROR: rule not found after create"
        return 4
    }
    foreach ($r in $created) {
        Write-LogLine $LogPath ("VERIFY: Enabled={0} Action={1} Profile={2}" -f $r.Enabled, $r.Action, $r.Profile)
    }
    try {
        $tnc = Test-NetConnection -ComputerName "127.0.0.1" -Port $UsePort -WarningAction SilentlyContinue
        Write-LogLine $LogPath ("Local listen 127.0.0.1:{0} Tcp={1}" -f $UsePort, $tnc.TcpTestSucceeded)
        if (-not $tnc.TcpTestSucceeded) {
            Write-LogLine $LogPath "NOTE: Enable Everything HTTP Server if clients still cannot connect."
        }
    } catch {}
    Write-LogLine $LogPath "Result: FIREWALL SUCCESS"
    Write-LogLine $LogPath ""
    return 0
}

function ConvertFrom-UnicodeEscape([string]$Text) {
    return [System.Text.RegularExpressions.Regex]::Unescape($Text)
}

function Write-FinalConnectionVerdict {
    # ログ最終行: 他PCからの接続可否（日本語は \u エスケープで書き、PS5.1 の文字化けを避ける）
    $usePort = $script:HttpPort
    if (-not $usePort) { $usePort = $Port }

    $hostIp = $script:PrimaryIp
    if (-not $hostIp) { $hostIp = Get-PreferredIpv4 }

    $enabled = $script:HttpEnabled
    $bind = $script:HttpBind
    $user = $script:HttpUser
    $pass = $script:HttpPass

    if ($enabled -eq "" -or ($null -eq $user)) {
        $ini = Join-Path $env:APPDATA "Everything\Everything.ini"
        if (Test-Path -LiteralPath $ini) {
            $map = Read-IniMap $ini
            if ($enabled -eq "") { $enabled = Get-IniValue $map "http_server_enabled" }
            if (-not $bind) { $bind = Get-IniValue $map "http_server_bindings" }
            if (-not $user) { $user = Get-IniValue $map "http_server_username" }
            if (-not $pass) { $pass = Get-IniValue $map "http_server_password" }
            $po = Get-IniValue $map "http_server_port"
            if ($po -ne "") { try { $usePort = [int]$po } catch {} }
        }
    }

    $listening = $false
    $listenAll = $false
    $listenLocalOnly = $false
    try {
        $listens = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq $usePort })
        if ($listens.Count -gt 0) {
            $listening = $true
            foreach ($l in $listens) {
                $a = [string]$l.LocalAddress
                if ($a -eq "0.0.0.0" -or $a -eq "::" -or $a -eq "*") { $listenAll = $true }
                if ($a -eq "127.0.0.1" -or $a -eq "::1") { $listenLocalOnly = $true }
            }
            if ($listenAll) { $listenLocalOnly = $false }
        }
    } catch {}

    $fwOk = $false
    try {
        $rules = @(Get-NetFirewallRule -DisplayName "Everything HTTP $usePort" -ErrorAction SilentlyContinue |
            Where-Object { $_.Enabled -eq "True" -and $_.Action -eq "Allow" })
        if ($rules.Count -gt 0) { $fwOk = $true }
    } catch {}

    $reasons = New-Object System.Collections.Generic.List[string]
    $ok = $true

    if ($enabled -ne "1") {
        $ok = $false
        [void]$reasons.Add((ConvertFrom-UnicodeEscape '\u30a8\u30d0\u30ea\u30fc\u30b7\u30f3\u30b0\u306e HTTP \u30b5\u30fc\u30d0\u30fc\u304c\u7121\u52b9\uff08http_server_enabled\u22601\uff09'))
    }
    if (-not $listening) {
        $ok = $false
        [void]$reasons.Add((ConvertFrom-UnicodeEscape ("\u30dd\u30fc\u30c8 $usePort \u3067\u5f85\u3061\u53d7\u3051\u3066\u3044\u306a\u3044")))
    } elseif ($listenLocalOnly -or $bind -eq "127.0.0.1") {
        $ok = $false
        [void]$reasons.Add((ConvertFrom-UnicodeEscape '\u30ed\u30fc\u30ab\u30eb\u30db\u30b9\u30c8\u306e\u307f\u5f85\u53d7\uff08\u4ed6PC\u4e0d\u53ef\uff09\u3002bindings \u3092\u7a7a\u306b\u3057\u3066\u304f\u3060\u3055\u3044'))
    }
    if (-not $fwOk) {
        $ok = $false
        [void]$reasons.Add((ConvertFrom-UnicodeEscape '\u30d5\u30a1\u30a4\u30a2\u30a6\u30a9\u30fc\u30eb\u8a31\u53ef\u30eb\u30fc\u30eb\u304c\u7121\u3044\uff0f\u7121\u52b9\uff08Private \u5411\u3051\uff09'))
    }
    if (-not $hostIp) {
        $ok = $false
        [void]$reasons.Add((ConvertFrom-UnicodeEscape '\u3053\u306ePC\u306e LAN IP \u304c\u5206\u304b\u3089\u306a\u3044'))
    }

    Write-LogLine $LogPath (ConvertFrom-UnicodeEscape '\u30fc\u30fc \u63a5\u7d9a\u53ef\u5426\uff08\u6700\u7d42\uff09\u30fc\u30fc')
    if ($ok) {
        if ($user -or $pass) {
            $u = if ($user) { $user } else { ConvertFrom-UnicodeEscape '\uff08\u7a7a\uff09' }
            $authNote = (ConvertFrom-UnicodeEscape '\u8981\u8a8d\u8a3c\uff08\u30e6\u30fc\u30b6\u30fc: ') + $u + (ConvertFrom-UnicodeEscape ' / \u30d1\u30b9\u30ef\u30fc\u30c9\u8a2d\u5b9a\u3042\u308a\uff09')
        } else {
            $authNote = ConvertFrom-UnicodeEscape '\u8a8d\u8a3c\u306a\u3057'
        }
        $msg = (ConvertFrom-UnicodeEscape '\u3010\u63a5\u7d9a\u53ef\u5426\u3011\u4ed6PC\u304b\u3089\u63a5\u7d9a\u3067\u304d\u308b\u898b\u8fbc\u307f\u3067\u3059\u3002\u63a5\u7d9a\u5148 ') +
            "$hostIp`:$usePort" +
            (ConvertFrom-UnicodeEscape ' \uff0f ') + $authNote +
            (ConvertFrom-UnicodeEscape ' \uff0f \u540c\u3058LAN\u30fb\u30cd\u30c3\u30c8\u30ef\u30fc\u30af\u304c\u30d7\u30e9\u30a4\u30d9\u30fc\u30c8\u3067\u3042\u308b\u3053\u3068')
        Write-LogLine $LogPath $msg
        Write-Host $msg
    } else {
        $why = if ($reasons.Count -gt 0) { ($reasons -join (ConvertFrom-UnicodeEscape '\uff1b')) } else { ConvertFrom-UnicodeEscape '\u6761\u4ef6\u4e0d\u8db3' }
        $msg = (ConvertFrom-UnicodeEscape '\u3010\u63a5\u7d9a\u53ef\u5426\u3011\u4ed6PC\u304b\u3089\u306f\u63a5\u7d9a\u3067\u304d\u306a\u3044\u898b\u8fbc\u307f\u3067\u3059\u3002\u7406\u7531: ') + $why
        Write-LogLine $LogPath $msg
        Write-Host $msg
    }
}
function Get-IpSuffixFromHost([string]$HostName) {
    if ($HostName -match '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$') {
        $padded = "{0:D3}{1:D3}{2:D3}{3:D3}" -f ([int]$Matches[1]),([int]$Matches[2]),([int]$Matches[3]),([int]$Matches[4])
        return $padded.Substring($padded.Length - 6)
    }
    return "000000"
}

function Invoke-RemoteCheck {
    $U = { param($s) [regex]::Unescape($s) }
    if (-not $TargetHost) {
        throw "TargetHost is required for RemoteCheck"
    }
    $th = $TargetHost.Trim()
    $user = [string]$Username
    $pass = [string]$Password

    Write-LogLine $LogPath "=== Everything HTTP remote check (from another PC) ==="
    Write-LogLine $LogPath "Mode       : RemoteCheck"
    Write-LogLine $LogPath ("This PC    : {0} ({1})" -f $env:COMPUTERNAME, (Get-PreferredIpv4))
    Write-LogLine $LogPath ("User       : {0}\{1}" -f $env:USERDOMAIN, $env:USERNAME)
    Write-LogLine $LogPath ("Target     : {0}:{1}" -f $th, $Port)
    Write-LogLine $LogPath ("Auth user  : {0}" -f $(if ($user) { $user } else { "(none)" }))
    Write-LogLine $LogPath ("Auth pass  : {0}" -f $(if ($pass) { if ($HidePassword) { "(set)" } else { "***" } } else { "(none)" }))
    Write-LogLine $LogPath "NOTE       : This does NOT read the remote Everything.ini or processes."
    Write-LogLine $LogPath "             It only checks reachability from THIS PC (same as a client)."
    Write-LogLine $LogPath "LogFile    : $LogPath"
    Write-LogLine $LogPath ""

    Write-LogLine $LogPath "--- TCP ---"
    $tcpOk = $false
    try {
        $tnc = Test-NetConnection -ComputerName $th -Port $Port -WarningAction SilentlyContinue
        $tcpOk = [bool]$tnc.TcpTestSucceeded
        Write-LogLine $LogPath ("PingSucceeded={0}  TcpTestSucceeded={1}  RemoteAddress={2}" -f $tnc.PingSucceeded, $tnc.TcpTestSucceeded, $tnc.RemoteAddress)
    } catch {
        Write-LogLine $LogPath ("TCP check failed: {0}" -f $_.Exception.Message)
    }
    Write-LogLine $LogPath ""

    function Probe-Remote([string]$Url, [string]$Uname, [string]$Pwd) {
        try {
            $headers = @{}
            if ($Uname -or $Pwd) {
                $token = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${Uname}:${Pwd}"))
                $headers["Authorization"] = "Basic $token"
            }
            $r = Invoke-WebRequest -Uri $Url -Headers $headers -TimeoutSec 8 -UseBasicParsing
            return "HTTP $([int]$r.StatusCode) OK (len=$($r.RawContentLength))"
        } catch {
            $resp = $_.Exception.Response
            if ($resp) { return "HTTP $([int]$resp.StatusCode) $($resp.StatusDescription)" }
            return "FAIL: $($_.Exception.Message)"
        }
    }

    $url = "http://${th}:${Port}/"
    Write-LogLine $LogPath "--- HTTP ---"
    $noAuth = Probe-Remote $url "" ""
    Write-LogLine $LogPath ("No auth : {0}" -f $noAuth)
    $withAuth = $null
    if ($user -or $pass) {
        $withAuth = Probe-Remote $url $user $pass
        Write-LogLine $LogPath ("With auth: {0}" -f $withAuth)
    } else {
        Write-LogLine $LogPath "With auth: (skipped — username/password not given)"
    }
    Write-LogLine $LogPath ""

    # verdict
    $ok = $false
    $reasons = New-Object System.Collections.Generic.List[string]
    if (-not $tcpOk) {
        [void]$reasons.Add((& $U '\u30dd\u30fc\u30c8\u307e\u3067\u5c4a\u304b\u306a\u3044\uff08FW\u30fbHTTP\u672a\u8d77\u52d5\u30fb\u5225LAN\u30fbAP\u5206\u96e2\u306a\u3069\uff09'))
    } else {
        if ($withAuth -match '^HTTP 200') {
            $ok = $true
        } elseif ($noAuth -match '^HTTP 200') {
            $ok = $true
        } elseif ($noAuth -match '401' -and -not ($user -or $pass)) {
            [void]$reasons.Add((& $U '\u30b5\u30fc\u30d0\u30fc\u306b\u306f\u5c4a\u3044\u3066\u3044\u308b\u304c\u8a8d\u8a3c\u304c\u5fc5\u8981\uff08401\uff09\u3002\u30e6\u30fc\u30b6\u30fc/\u30d1\u30b9\u30ef\u30fc\u30c9\u3092\u5165\u529b\u3057\u3066\u518d\u5b9f\u884c'))
        } elseif ($noAuth -match '401' -and ($withAuth -match '401' -or -not $withAuth)) {
            [void]$reasons.Add((& $U '\u8a8d\u8a3c\u304c\u5408\u308f\u306a\u3044\uff08401\uff09\u3002ID/\u30d1\u30b9\u30ef\u30fc\u30c9\u3092\u78ba\u8a8d'))
        } elseif ($noAuth -match '^FAIL' -and $tcpOk) {
            [void]$reasons.Add((& $U 'TCP\u306f\u901a\u308b\u304c HTTP \u5fdc\u7b54\u304c\u3053\u306a\u3044'))
        } else {
            [void]$reasons.Add(("HTTP result: $noAuth / $withAuth"))
        }
    }

    Write-LogLine $LogPath ((& $U '\u30fc\u30fc \u63a5\u7d9a\u53ef\u5426\uff08\u6700\u7d42\uff09\u30fc\u30fc'))
    if ($ok) {
        $authNote = if ($user -or $pass) {
            (& $U '\u8a8d\u8a3cOK')
        } else {
            (& $U '\u8a8d\u8a3c\u306a\u3057\u3067OK')
        }
        $msg = (& $U '\u3010\u63a5\u7d9a\u53ef\u5426\u3011\u3053\u306ePC\u304b\u3089\u5bfe\u8c61\u30b5\u30fc\u30d0\u30fc\u3078\u63a5\u7d9a\u3067\u304d\u308b\u898b\u8fbc\u307f\u3067\u3059\u3002') +
            (" $th`:$Port ") + $authNote
        Write-LogLine $LogPath $msg
    } else {
        $why = if ($reasons.Count -gt 0) { ($reasons -join (& $U '\uff1b')) } else { (& $U '\u4e0d\u660e') }
        $msg = (& $U '\u3010\u63a5\u7d9a\u53ef\u5426\u3011\u3053\u306ePC\u304b\u3089\u306f\u63a5\u7d9a\u3067\u304d\u306a\u3044\u898b\u8fbc\u307f\u3067\u3059\u3002\u7406\u7531: ') + $why
        Write-LogLine $LogPath $msg
    }
}
$script:SkipFinal = [bool]$SkipFinalVerdict

try {
    if ($Mode -eq "RemoteCheck") {
        Invoke-RemoteCheck
        $script:SkipFinal = $true  # already wrote Japanese verdict
        Save-TempPointer $LogPath
        $exitCode = 0
    }
    if ($Mode -eq "All" -or $Mode -eq "Inspect") {
        Invoke-Inspect
        Save-TempPointer $LogPath
    }
    if ($Mode -eq "All" -or $Mode -eq "Firewall") {
        $fwPort = $script:HttpPort
        if (-not $fwPort) { $fwPort = $Port }
        # UAC 昇格する場合、最終行は昇格後プロセスが書く
        $willElevate = -not (Test-IsAdmin)
        if ($willElevate) { $script:SkipFinal = $true }
        $exitCode = Invoke-Firewall -UsePort $fwPort
        if ($willElevate) {
            $joined = ""
            try {
                if (Test-Path -LiteralPath $LogPath) {
                    $joined = ((Get-Content -LiteralPath $LogPath -Tail 5 -Encoding UTF8 -ErrorAction SilentlyContinue) | Out-String)
                }
            } catch {}
            if ($joined -notmatch [regex]::Escape([regex]::Unescape('\u3010\u63a5\u7d9a\u53ef\u5426\u3011'))) {
                $script:SkipFinal = $false
            }
        }
    }
    if ($Mode -eq "Inspect") {
        Write-LogLine $LogPath "Result: INSPECT DONE"
        $exitCode = 0
    }
}
catch {
    try { Write-LogLine $LogPath "ERROR: $($_.Exception.Message)" } catch {}
    $exitCode = 1
    $script:SkipFinal = $false
}
finally {
    try {
        if (-not $script:SkipFinal) {
            Write-FinalConnectionVerdict
        }
    } catch {
        try { Write-LogLine $LogPath (([regex]::Unescape('\u3010\u63a5\u7d9a\u53ef\u5426\u3011\u5224\u5b9a\u30a8\u30e9\u30fc: ')) + $_.Exception.Message) } catch {}
    }
    try { Save-TempPointer $LogPath } catch {}
    Write-Host ""
    Write-Host "Log: $LogPath"
}
exit $exitCode