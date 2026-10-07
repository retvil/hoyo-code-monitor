# Changelog

## [1.2.0] - 2026-10-07

### Fixed
- **Autostart actually installs**: the NSIS section was off by default and skipped
  on silent installs (no Run entry). Now default-on (opt-out in GUI), plus relative
  icon paths so the installer builds on CI/other machines

### Removed
- Unfinished `dashboard_experiment` slice (routes, templates, static mount, assets),
  internal design notes and stray logs — minus 1172 lines

### Docs
- Planning docs refreshed to v1.1.6 reality; README feature lists cover check-ins
  in all 6 languages

## [1.1.6] - 2026-09-30

### Added
- **Daily HoYoLAB check-ins (auto sign-in)**: second pipeline next to code redemption —
  `GET info → POST sign → GET home` per account x game (MVP: Genshin + HSR, overseas).
  Own schedule (`checkin_time`, default 04:00 + `checkin_jitter_minutes`), per-account
  `Auto check-in` toggles, `/checkins` page with history, manual "Claim now" button
  and `/api/checkins/status` JSON. Idempotent via `UNIQUE(account_id, game, claimed_date)`
  (migration v13, `checkin_log` table); stable per-account `device_id` avoids re-logins.
  Retcode `-5003` treated as already-claimed, expired cookies surface a refresh hint.
  41 new tests (runner, storage, scheduler, web UI)
- **Check-in wave 2**: Zenless Zone Zero and Honkai Impact 3rd (endpoints verified
  against SIMNet/MihoyoBBSTools references; ToT pending — no verified OS act_id).
  HI3 sends no `x-rpc-signgame`, like the reference clients

### Fixed
- **Fresh installs showed an incomplete sources list**: `seed_default_sources` used a
  legacy hardcoded list instead of the full `SOURCE_PRESETS` (25 presets). Now seeds
  all presets with name/URL dedup (upgrades never duplicate) and seeds on app startup,
  so the Sources page is populated before the first scheduler cycle
- **Check-in retries were silently skipped**: slots with a `failed`/`skipped` entry for
  today were treated as done, so pressing "Claim now" after fixing cookies did nothing.
  Only `success`/`already_claimed` now count as done; failed rows are cleared and retried.
  Also fixed `/info` `today` parsing (real API returns `YYYY-MM-DD`, not a day number),
  which crashed claims with `ValueError`
- **Two app instances could run at once**: `portalocker` is missing from the frozen
  build, silently disabling the single-instance guard. The guard now falls back to
  stdlib `msvcrt` locking (5 new tests). Also the tray dashboard showed a dead
  scheduler instance — tray now shares its live scheduler with the embedded web UI

### Fixed
- **Account auto-login crashed with bare 500 in frozen builds**: Playwright looked for
  browsers inside the bundle temp dir (`_MEI...\playwright\driver\package\.local-browsers`).
  Now `PLAYWRIGHT_BROWSERS_PATH` points to `%LOCALAPPDATA%\HoYoCodeMonitor\ms-playwright`
  when frozen, missing Chromium auto-downloads on first login (~170MB, one-time),
  and browser errors return HTTP 502 with detail instead of Internal Server Error
- Browser profile moved to the app-data dir (was CWD-relative `data/browser-profile`)

### Fixed
- **Frozen exe failed to start** (hung silently, no tray, no web UI): missing runtime
  dependencies in the PyInstaller bundle (`aiohttp`, `bs4`, `pystray`, `Pillow`, `qrcode`,
  `python-multipart`) crashed the import chain; `console=False` hid the traceback
- **Web server crashed in windowed builds**: uvicorn's default `dictConfig` calls
  `sys.stdout.isatty()`, unavailable in PyInstaller windowed mode — now runs with
  `log_config=None` and logs through the app's root logger
- **Dashboard returned HTTP 500 in frozen builds**: Jinja2 templates resolved from CWD;
  now resolved from `sys._MEIPASS` when frozen
- **Data written to read-only install dir**: db/config/logs/lock/key now live in
  `%LOCALAPPDATA%\HoYoCodeMonitor` when frozen (repo-relative paths in source mode,
  override with `HCM_DATA_DIR`)
- **Autostart registered a python+cli.py command in frozen builds** — now registers the exe
- **Logging was never initialized** — `setup_logging()` now runs for every CLI command;
  rotating file log at `%LOCALAPPDATA%\HoYoCodeMonitor\logs\app.log`
- UPX disabled in PyInstaller spec (known to corrupt OpenSSL DLLs); PIL image plugins no
  longer excluded (QR codes and tray icon rendering)
- `requirements.txt` / `pyproject.toml` now declare `pystray`, `Pillow`, `qrcode`,
  `python-multipart`

### Added
- Web UI in 6 languages (EN/RU/DE/FR/JA/ZH) with sidebar switcher; default language follows the OS
- Per-account auto-redeem toggles (Accounts page)
- Redeem-all button + per-code redeem buttons
- Honest code statuses: Done / Expired / Invalid / Failed / Pending (from API retcodes)
- Codes table: source/status/search filters, pagination (20 per page)
- Per-code delete + bulk cleanup of dead codes (expired/invalid)
- Published/expiry date columns (migration v10, filled when sources provide them)
- Separate `/author` page: contacts, donate buttons, crypto addresses with copy + QR
- System tray: live enable/disable menu, scan-interval submenu (5/15/30/60 min), one-click settings
- Windows autostart commands (`autostart enable/disable/status`)
- Single-instance guard (no duplicate schedulers)
- Auto cookie capture via browser login (`accounts login`, persistent profile)
- New sources: hoyo-codes API, ennead API (x2), Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge
- Multi-game foundation (variant C): migration v11 `game` columns, `GAME_CONF` x5 with accents, per-game fetch/redeem endpoints (ZZZ Risk POST), game cards + filter on dashboard, HSR/ZZZ/HI3/ToT API presets
- Rename to HoYo Code Monitor (package, CLI, docs, installer)
- Game UI themes groundwork: per-game accent colors, starfield background, primogem brand mark
- Dashboard themes (light/dark/AMOLED), export/import JSON, copy buttons, SVG sparkline, toast notifications, gift-page redeem links
- Telegram notifications (new codes + redemptions)
- Prometheus `/metrics`, `/health` endpoint, HTMX live partials
- Docker support (Dockerfile, docker-compose)
- READMEs in 6 languages

### Fixed
- Redeemer uses GET (was POST → HTTP 405)
- Hoyolab API host corrected to `hoyoverse.com` (+ `x-rpc-*` headers)
- Scheduler now updates `codes.redeemed` flag (dashboard showed Pending forever)
- `-2017/-2018` (already claimed) count as success
- Full cookie set capture (was 6 keys → `-1071` login errors)
- Extractor case/length bugs (`MySnezhnayaCareer` mangled, 22-char codes dropped)
- Stats partials stopped polling after first refresh (missing wrapper)
- Form-data vs JSON mismatches on account/source/cookies/config endpoints
- Account cookies stored unencrypted in two places (now Fernet everywhere)

### Security
- Cookies encrypted at rest (Fernet AES-128, key in env/keyring/local file)
- Web UI binds to `127.0.0.1` only, no auth needed for local use
- Sensitive data filtered from logs

## [0.1.0] - 2026-09-06
- Initial stabilized release: monitoring, 3 sources, auto-redeem, CLI, stats
