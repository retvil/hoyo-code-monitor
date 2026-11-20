# HoYo Code Monitor

[![Release](https://img.shields.io/github/v/release/retvil/hoyo-code-monitor?sort=date)](https://github.com/retvil/hoyo-code-monitor/releases) [![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Platform Windows](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/retvil/hoyo-code-monitor/releases)

**Never miss a HoYoverse promo code again — local monitoring and auto-redeem for 5 games, right on your PC.**

**🇬🇧 English** | [🇷🇺 Русский](README.ru.md) | [🇩🇪 Deutsch](README.de.md) | [🇫🇷 Français](README.fr.md) | [🇯🇵 日本語](README.ja.md) | [🇨🇳 中文](README.zh.md)

## What is this?

HoYoverse games regularly release time-limited promo codes — and they expire fast. **HoYo Code Monitor** watches 16 code sources across 5 games (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Honkai Impact 3rd, Tears of Themis) and redeems new codes to your accounts automatically. Everything runs locally on your PC: SQLite database, encrypted cookies, no telemetry, no cloud.

### How it works

1. The scheduler polls enabled sources, extracts codes (`[A-Z0-9]{8,14}`), stores new ones.
2. For each account with auto-redeem ON: `GET webExchangeCdkey` with the account's cookies, a configurable gap between redemptions (default 8 s).
3. Result recorded: `success` → Done + reward; `-2017/-2018` → already claimed (counts as Done); `-2001` expired, `-2003` invalid/CN-only.
4. Daily HoYoLAB check-ins run on their own schedule (default 04:00 + jitter): `info → sign → home` per account × game, same cookies, results on the Check-ins page.
5. If a check-in fails because the account cookies expired, the scheduler can **auto-refresh them headless** from the saved browser profile (opt-in toggle, per-account cooldown) — no manual re-login needed while the saved session is still valid.

## Security hardening (v1.6.0)

The v1.6.0 audit fixed 45 issues across 4 severity levels. Key changes:

| Area | What changed |
|---|---|
| **SSRF** | Source URLs resolving to private ranges (10.x, 172.16–31.x, 192.168.x, 127.x, 169.254.x, 0.0.0.0) or using non-HTTP schemes are rejected at creation/update |
| **ReDoS** | Regex extractor patterns with nested quantifiers (`(a+)+`, `(.*a)*`) are rejected |
| **XSS** | Source names, cookie values, and error strings rendered in HTML endpoints are escaped before insertion |
| **CSRF** | Per-process token seed is persisted to a date-stamped file; stale seeds rotate daily |
| **Game validation** | `POST /import` rejects payloads with unknown game fields |
| **Timeout passthrough** | Per-source `timeout_seconds` is forwarded to aiohttp (previously ignored) |
| **Reward on empty API** | Redeemer stores `reward=""` instead of the literal string `"Redeemed"` when the API returns no data |
| **Dashboard perf** | Stats path reduced from 20 SQL queries to 1 `GROUP BY`; redeemed codes list now ordered in SQL |

All 45 fixes are covered by 30 new regression tests.

## Features

- **Background monitoring** — checks sources every N minutes (configurable, default 15)
- **Auto-redeem** — redeems new codes via Hoyolab `webExchangeCdkey` API (opt-in, per account)
- **Daily check-ins** — auto sign-in on HoYoLAB for all 5 games: Genshin, Star Rail, ZZZ, HI3, Tears of Themis (opt-in, per account, own schedule, idempotent)
- **Multi-source** — Wiki, Wiki API, community JSON APIs, guide sites (25 presets, see table)
- **Multi-account** — each account has its own encrypted cookies and redeem toggle
- **Auto cookie refresh** — when a check-in fails on expired cookies, re-capture them headless from the saved browser profile (opt-in, per-account cooldown) so monitoring keeps working without a manual re-login
- **Dark theme** — a Light/Dark toggle in the sidebar; the choice persists per browser
- **Statistics** — total / redeemed / failed, per-source breakdown, redemption log
- **Web UI** — local dashboard at `http://127.0.0.1:8000` in 6 languages
- **System tray** — icon with enable/disable, scan-interval submenu, one-click settings
- **Encrypted cookies** — Fernet (AES-128), key in env / OS keyring / local file
- **Autostart** — Windows login autostart (on by default)

## Screenshots

<details>
<summary>Dashboard / Sources / Config / Check-ins / Accounts / Author</summary>

| Dashboard | Sources | Config |
|---|---|---|
| ![Dashboard](docs/screenshots/dashboard_en.png) | ![Sources](docs/screenshots/sources_en.png) | ![Config](docs/screenshots/config_en.png) |

| Author |
|---|
| ![Author](docs/screenshots/author_en.png) |

| Check-ins | Accounts |
|---|---|
| ![Check-ins](docs/screenshots/checkins_en.png) | ![Accounts](docs/screenshots/accounts_en.png) |

</details>

## Sources (verified live)

| Source | Type | Status |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | May return 403 (Fandom protection) |
| Genshin Wiki API | JSON | Working |
| `hoyo-codes.seria.moe` | JSON API | Working |
| `api.ennead.cc` (x2 endpoints) | JSON API | Working |
| Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge | CSS guides | Working |

## Install from the installer

Download the latest release from [GitHub Releases](https://github.com/retvil/hoyo-code-monitor/releases):

| File | Description |
|---|---|
| `hoyo-code-monitor-X.Y.Z-setup.exe` | Inno Setup installer (per-user, no admin rights needed) |

### Interactive install

1. Run the `.exe` — it asks where to install (default: `C:\Users\<you>\AppData\Local\Programs\hoyo-code-monitor`)
2. Click **Next** — two components are included:
   - **Desktop shortcut** — create a desktop icon
   - **Windows autostart** — launch the tray app on login
3. Click **Install** — done in ~30 s. The app starts automatically in the system tray.

### Silent install (scriptable / GPO / SCCM)

```powershell
# Per-user install, no prompts
hoyo-code-monitor-1.5.3-setup.exe /S

# Install to a specific directory
hoyo-code-monitor-1.5.3-setup.exe /S /D=C:\Games\HoYoMonitor

# No desktop shortcut, no autostart
hoyo-code-monitor-1.5.3-setup.exe /S /desktop=no /startup=no
```

### Uninstall

- **Control Panel** → Programs and Features → "HoYo Code Monitor" → Uninstall
- **Silent**: `uninstall.exe /S` (created by the installer in the install dir)
- Or delete the install folder and the registry key `HKCU\Software\HoYoCodeMonitor`

### Data locations (persist across uninstall/reinstall)

| What | Location |
|---|---|
| SQLite database | `%LOCALAPPDATA%\HoYoCodeMonitor\monitor.db` |
| `config.toml` (settings, source definitions) | `%LOCALAPPDATA%\HoYoCodeMonitor\config.toml` |
| Encrypted Fernet key | OS keyring (Windows Credential Manager) |
| Logs | `%LOCALAPPDATA%\HoYoCodeMonitor\logs\` |
| Browser profile (Playwright Chromium) | `%LOCALAPPDATA%\HoYoCodeMonitor\browser-profile\` |

Back up `data/` + `config.toml` before a major version upgrade.

---

## Auto-update

The app checks for new releases on startup (configurable via `update_check_enabled = false` in `config.toml`). A banner appears in the dashboard when a newer release is available.

### Manual auto-update script

`auto-update.ps1` downloads the latest installer, verifies the SHA-256
checksum, optionally checks a PGP signature, stops running instances,
installs silently, and restarts the app. All events are written to
`%LOCALAPPDATA%\HoYoCodeMonitor\logs\auto-update.log`.

```powershell
# One-off update (with PGP signature check if a .sig asset is published)
powershell -ExecutionPolicy Bypass -File auto-update.ps1

# Skip PGP check (SHA-256 still verified)
powershell -ExecutionPolicy Bypass -File auto-update.ps1 -SkipSignature

# Custom log location
powershell -ExecutionPolicy Bypass -File auto-update.ps1 -LogDir "C:\Logs\hcm"
```

| Parameter | Default | Description |
|---|---|---|
| `-SkipSignature` | off | Skip PGP signature verification |
| `-LogDir <path>` | `%LOCALAPPDATA%\HoYoCodeMonitor\logs` | Where `auto-update.log` is written |

**Release signing (maintainer):**

To enable PGP verification, publish two extra release assets alongside the
`.exe` installer:

```bash
# 1. Generate a detached PGP signature
gpg --detach-sign --armor -o installer.exe.sig installer.exe

# 2. Export your public key (users import it automatically if named pubkey.asc)
gpg --armor --export YOUR_KEY_ID > pubkey.asc

# 3. Upload all three as release assets:
#    - installer.exe        (the app)
#    - installer.exe.sig    (detached PGP signature)
#    - pubkey.asc           (public key, auto-imported by the updater)
```

If no `.sig` asset is present, the script logs a warning and continues
without PGP verification. If `sha256.txt` or `checksum.txt` is uploaded,
the SHA-256 is verified against it automatically.

**Check the log:**

```powershell
# Tail the log from the terminal
Get-Content "$env:LOCALAPPDATA\HoYoCodeMonitor\logs\auto-update.log" -Wait

# Search for errors
Select-String -Path "$env:LOCALAPPDATA\HoYoCodeMonitor\logs\auto-update.log" -Pattern "ERROR"
```

### Scheduled auto-update (Windows Task Scheduler)

Run the script daily at 03:00 so the app self-updates without user interaction:

```powershell
# Create the scheduled task (run as admin once)
schtasks /create ^
  /tn "HoYoCodeMonitorUpdate" ^
  /sc daily /st 03:00 ^
  /ru SYSTEM ^
  /tr "powershell -ExecutionPolicy Bypass -File \"C:\Scripts\auto-update.ps1\"" ^
  /f

# Verify
schtasks /query /tn "HoYoCodeMonitorUpdate"

# Remove
schtasks /delete /tn "HoYoCodeMonitorUpdate" /f
```

> The script is idempotent: if the installed version already matches the latest
> release tag, it exits without downloading anything.

## Quick start

```powershell
# 1. Install and launch — the app lives in the system tray
# 2. Add an account (region: os_usa / os_euro / os_asia / os_cht)
hoyo-code-monitor accounts add main <UID> <REGION>

# 3. Capture cookies once (browser opens, you log in once)
hoyo-code-monitor accounts login main

# 4. Enable auto-redeem (or toggle per account in the Web UI)
hoyo-code-monitor config set redemption_enabled true
```

5. Open the dashboard: `http://127.0.0.1:8000` — Dashboard, Sources, Accounts, Config (EN/RU/DE/FR/JA/ZH switcher in sidebar).

## Install from source

Requires Python 3.11+ ([python.org](https://python.org)).

```powershell
pip install -e .
# Playwright browser for JS-rendered sources (optional)
python -m playwright install chromium
```

Run in tray (recommended) / one-shot check / Web UI:

```powershell
hoyo-code-monitor tray
hoyo-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

## FAQ

- **Code shows Pending?** Check cookies (they expire), `redemption_enabled`, per-account toggle, and the error in Redemption log.
- **`-1071 "Please log in"`?** Re-run `accounts login` — the cookie set was incomplete.
- **Data location?** `data/monitor.db`, `config.toml`, `logs/`, `data/.key`. Copy `data/` for backup.

## Author & support

See the "About the author" block in the app dashboard, or below:

**Crypto:**

- BTC: `bc1qunld3rsp37qf5gg69aune50y0qqkd0eugg7j97`
- TON: `UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC`
- USDT (TRC20): `TBPJSSLu1mUcX54g9UyxUohYGf2fuRvbwd`
- USDT (ERC20): `0x25CAED3776Ef5b18E03392bC5b254Bbd78E8180C`
- USDT (SOL): `3qgN5z291CEcj2FUi2Zza5DioxKgNw72kC7P52pCcTrG`

## License

MIT
