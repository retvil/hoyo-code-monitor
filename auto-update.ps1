# auto-update.ps1 — HoYo Code Monitor auto-updater
#
# Downloads the latest release installer from GitHub and runs it silently.
# Safe to run repeatedly: it skips the download if the installed version
# matches the latest release.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File auto-update.ps1
#
# Scheduled task (run every day at 03:00):
#   schtasks /create /tn "HoYoCodeMonitorUpdate" /sc daily /st 03:00 ^
#     /tr "powershell -ExecutionPolicy Bypass -File \"C:\Scripts\auto-update.ps1\""

$ErrorActionPreference = "Stop"
$Repo     = "retvil/hoyo-code-monitor"
$ApiBase = "https://api.github.com/repos/$Repo"

function Get-Json {
    param([string]$Url)
    $req  = [System.Net.HttpWebRequest]::Create($Url)
    $req.UserAgent = "hcm-updater/1.0"
    $req.Headers.Add("Accept", "application/vnd.github+json")
    try {
        $resp = $req.GetResponse()
        $stream = $resp.GetResponseStream()
        $reader = [System.IO.StreamReader]::new($stream)
        $body = $reader.ReadToEnd()
        $reader.Dispose()
        $resp.Close()
        return $body | ConvertFrom-Json
    } catch [System.Net.WebException] {
        # Some releases have draft=true — list releases, take latest non-draft
        $list = (Get-Json "$ApiBase/releases?per_page=5")
        $rel  = $list | Where-Object { -not $_.draft } | Select-Object -First 1
        if ($null -eq $rel) { throw "No releases found for $Repo" }
        return $rel
    }
}

# --- Get latest release ---
$rel = Get-Json "$ApiBase/releases/latest"
$tag = $rel.tag_name
Write-Host "Latest release: $tag"

# --- Find the .exe asset ---
$asset = $rel.assets | Where-Object { $_.name -like "*.exe" } | Select-Object -First 1
if ($null -eq $asset) {
    Write-Warning "No .exe asset found in release $tag"
    exit 1
}
$exeName = $asset.name
Write-Host "Asset: $exeName"

# --- Check current installed version ---
$regPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\hoyo-code-monitor"
$current = (Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue).DisplayName -replace ".*?(\d+\.\d+\.\d+).*$", '$1'

if ($current -eq $tag.TrimStart("v")) {
    Write-Host "Already up to date ($current). Nothing to do."
    exit 0
}
Write-Host "Current: $current  →  Updating to $tag"

# --- Download installer to a temp file ---
$tmp = Join-Path $env:TEMP "hcm-installer-$tag.exe"
Write-Host "Downloading to $tmp ..."
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
$webClient = [System.Net.WebClient]::new()
$webClient.DownloadFile($asset.browser_download_url, $tmp)
$size = (Get-Item $tmp).Length
Write-Host "Downloaded $([math]::Round($size/1MB,1)) MB"

# --- Stop running instances ---
$procs = Get-Process -Name "hoyo-code-monitor" -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host "Stopping $($procs.Count) running instance(s)..."
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 3
}

# --- Run installer silently ---
Write-Host "Installing..."
Push-Location $env:TEMP
try {
    & $tmp /S
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Error "Installer exited with code $exitCode"
    exit $exitCode
}

# --- Restart the app ---
Start-Process "$($env:LOCALAPPDATA)\HoYo Code Monitor\hoyo-code-monitor.exe" -ArgumentList "tray"
Remove-Item $tmp -Force -ErrorAction SilentlyContinue
Write-Host "Update to $tag complete."
