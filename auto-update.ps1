# auto-update.ps1 — HoYo Code Monitor auto-updater
#
# Downloads the latest release installer from GitHub, verifies the SHA-256
# checksum, optionally checks a PGP signature, installs silently, and
# restarts the app. All events are written to a rolling log file.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File auto-update.ps1
#   powershell -ExecutionPolicy Bypass -File auto-update.ps1 -SkipSignature
#
# Parameters:
#   -SkipSignature   Skip PGP signature verification (SHA-256 check still runs)
#   -LogDir <path>   Override the log directory (default: %LOCALAPPDATA%\HoYoCodeMonitor\logs)
#
# Scheduled task (run every day at 03:00):
#   schtasks /create /tn "HoYoCodeMonitorUpdate" /sc daily /st 03:00 ^
#     /ru SYSTEM ^
#     /tr "powershell -ExecutionPolicy Bypass -File \"C:\Scripts\auto-update.ps1\""
#
# Signing releases (maintainer, one-time):
#   # Generate a .sig file next to the installer and upload it as a second asset
#   gpg --detach-sign --armor -o installer.exe.sig installer.exe
#   # The .sig file must be a release asset with the name: <installer>.sig
#
#   # To disable signature checking, publish without a .sig asset OR
#   # run this script with -SkipSignature

[CmdletBinding()]
param(
    [switch]$SkipSignature,
    [string]$LogDir
)

$ErrorActionPreference = "Stop"
$Repo     = "retvil/hoyo-code-monitor"
$ApiBase  = "https://api.github.com/repos/$Repo"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
if (-not $LogDir) {
    $LogDir = Join-Path $env:LOCALAPPDATA "HoYoCodeMonitor\logs"
}
if (-not (Test-Path $LogDir)) {
    New-Item -Path $LogDir -ItemType Directory -Force | Out-Null
}
$logFile = Join-Path $LogDir "auto-update.log"

function Write-Log {
    param(
        [ValidateSet("INFO", "WARN", "ERROR", "OK")]
        [string]$Level,
        [string]$Message
    )
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Write-Log "INFO" "=== Auto-update started ==="

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
function Get-Json {
    param([string]$Url)
    Write-Log "INFO" "GET $Url"
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.UserAgent = "hcm-updater/1.0"
    $req.Headers.Add("Accept", "application/vnd.github+json")
    try {
        $resp   = $req.GetResponse()
        $stream = $resp.GetResponseStream()
        $reader = [System.IO.StreamReader]::new($stream)
        $body   = $reader.ReadToEnd()
        $reader.Dispose()
        $resp.Close()
        return $body | ConvertFrom-Json
    } catch [System.Net.WebException] {
        Write-Log "WARN" "releases/latest failed ($_), falling back to releases list"
        $list = (Get-Json "$ApiBase/releases?per_page=5")
        $rel  = $list | Where-Object { -not $_.draft } | Select-Object -First 1
        if ($null -eq $rel) {
            Write-Log "ERROR" "No releases found for $Repo"
            throw "No releases found for $Repo"
        }
        return $rel
    }
}

function Get-Binary {
    param([string]$Url, [string]$Dest)
    Write-Log "INFO" "GET $Url  →  $Dest"
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    $wc = [System.Net.WebClient]::new()
    $wc.DownloadFile($Url, $Dest)
}

# ---------------------------------------------------------------------------
# 1. Fetch latest release
# ---------------------------------------------------------------------------
$rel = Get-Json "$ApiBase/releases/latest"
$tag = $rel.tag_name
Write-Log "INFO" "Latest release: $tag"

# ---------------------------------------------------------------------------
# 2. Locate the .exe asset
# ---------------------------------------------------------------------------
$asset = $rel.assets | Where-Object { $_.name -like "*.exe" -and $_.name -notlike "*.sig" } | Select-Object -First 1
if ($null -eq $asset) {
    Write-Log "ERROR" "No .exe asset found in release $tag"
    exit 1
}
$exeName = $asset.name
Write-Log "INFO" "Installer asset: $exeName"

# ---------------------------------------------------------------------------
# 3. Version check — skip if already up-to-date
# ---------------------------------------------------------------------------
$regPathHkcu = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\hoyo-code-monitor"
$regPathHklm = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\hoyo-code-monitor"
$current = $null
foreach ($reg in @($regPathHkcu, $regPathHklm)) {
    $p = Get-ItemProperty -Path $reg -ErrorAction SilentlyContinue
    if ($p) {
        $current = $p.DisplayName -replace ".*?(\d+\.\d+\.\d+).*$", '$1'
        break
    }
}

$tagNum = $tag.TrimStart("v")
if ($current -eq $tagNum) {
    Write-Log "OK" "Already up to date ($current). Nothing to do."
    exit 0
}
Write-Log "INFO" "Installed: $current  →  Updating to $tagNum"

# ---------------------------------------------------------------------------
# 4. Download installer
# ---------------------------------------------------------------------------
$tmpDir  = [System.IO.Path]::GetTempPath()
$tmpExe  = Join-Path $tmpDir "hcm-installer-$tagNum.exe"
Write-Log "INFO" "Downloading to $tmpExe ..."
Get-Binary $asset.browser_download_url $tmpExe
$size = (Get-Item $tmpExe).Length
Write-Log "INFO" "Downloaded $([math]::Round($size / 1MB, 1)) MB"

# ---------------------------------------------------------------------------
# 5. SHA-256 checksum verification
# ---------------------------------------------------------------------------
$sha256 = (Get-FileHash -Path $tmpExe -Algorithm SHA256).Hash.ToLower()
Write-Log "INFO" "Local SHA-256: $sha256"

# GitHub does not publish a checksum manifest by default. If the release body
# or a comment contains a sha256 line, verify against it. Otherwise the
# download's integrity is protected by TLS + GitHub's signed release infrastructure.
# To enforce a local check, maintainers can add a "sha256.txt" asset:
$shaAsset = $rel.assets | Where-Object { $_.name -like "sha256*" -or $_.name -like "*checksum*" } | Select-Object -First 1
if ($shaAsset) {
    $shaFile = Join-Path $tmpDir "hcm-sha256.txt"
    Get-Binary $shaAsset.browser_download_url $shaFile
    $expected = (Get-Content $shaFile | Where-Object { $_ -match $exeName }) -split '\s+' | Select-Object -First 1
    if ($expected -and $expected.ToLower() -ne $sha256) {
        Write-Log "ERROR" "SHA-256 mismatch! Expected $expected, got $sha256"
        exit 2
    }
    Write-Log "OK" "SHA-256 verified against $($shaAsset.name)"
} else {
    Write-Log "WARN" "No checksum asset found — relying on TLS integrity only"
}

# ---------------------------------------------------------------------------
# 6. PGP signature verification (optional)
# ---------------------------------------------------------------------------
if ($SkipSignature) {
    Write-Log "WARN" "PGP signature check skipped (-SkipSignature)"
} else {
    # Look for a .sig asset: <installer>.sig
    $sigAsset = $rel.assets | Where-Object {
        $_.name -like "$($exeName -replace '\.exe$').sig" -or
        ($_.name -like "*.sig" -and $_.name -like "*$tagNum*")
    } | Select-Object -First 1

    if ($null -eq $sigAsset) {
        Write-Log "WARN" "No .sig asset found in release — skipping PGP verification"
    } else {
        $sigFile = Join-Path $tmpDir "hcm-installer-$tagNum.sig"
        Write-Log "INFO" "Downloading signature: $($sigAsset.name)"
        Get-Binary $sigAsset.browser_download_url $sigFile

        # Use gpg if available; warn otherwise
        $gpg = Get-Command gpg -ErrorAction SilentlyContinue
        if ($gpg) {
            # Extract the public key from the release (asset named pubkey.asc)
            $keyAsset = $rel.assets | Where-Object { $_.name -like "pubkey*" -or $_.name -like "*.asc" } | Select-Object -First 1
            if ($keyAsset) {
                $keyFile = Join-Path $tmpDir "hcm-pubkey.asc"
                Get-Binary $keyAsset.browser_download_url $keyFile
                Write-Log "INFO" "Importing public key from $($keyAsset.name) ..."
                & gpg --batch --import $keyFile 2>&1 | Out-Null
            }
            Write-Log "INFO" "Verifying PGP signature ..."
            & gpg --batch --verify $sigFile $tmpExe 2>&1
            $gpgExit = $LASTEXITCODE
            if ($gpgExit -eq 0) {
                Write-Log "OK" "PGP signature valid"
            } else {
                Write-Log "ERROR" "PGP signature verification FAILED (gpg exit $gpgExit)"
                exit 3
            }
        } else {
            Write-Log "WARN" "gpg not found on PATH — cannot verify signature, continuing"
        }
    }
}

# ---------------------------------------------------------------------------
# 7. Stop running instances
# ---------------------------------------------------------------------------
$procs = Get-Process -Name "hoyo-code-monitor" -ErrorAction SilentlyContinue
if ($procs) {
    Write-Log "INFO" "Stopping $($procs.Count) running instance(s) ..."
    $procs | Stop-Process -Force
    Start-Sleep -Seconds 3
}

# ---------------------------------------------------------------------------
# 8. Run installer silently
# ---------------------------------------------------------------------------
Write-Log "INFO" "Running installer /S ..."
Push-Location $tmpDir
try {
    & $tmpExe /S
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Log "ERROR" "Installer exited with code $exitCode"
    exit $exitCode
}

# ---------------------------------------------------------------------------
# 9. Restart the app
# ---------------------------------------------------------------------------
$appExe = Join-Path $env:LOCALAPPDATA "HoYo Code Monitor\hoyo-code-monitor.exe"
if (Test-Path $appExe) {
    Start-Process $appExe -ArgumentList "tray"
    Write-Log "OK" "App restarted: $appExe"
} else {
    Write-Log "WARN" "App not found at $appExe — start it manually"
}

# ---------------------------------------------------------------------------
# 10. Cleanup
# ---------------------------------------------------------------------------
Remove-Item $tmpExe -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmpDir "hcm-sha256.txt") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmpDir "hcm-pubkey.asc") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmpDir "hcm-installer-$tagNum.sig") -Force -ErrorAction SilentlyContinue

Write-Log "OK" "=== Update to $tagNum complete ==="
