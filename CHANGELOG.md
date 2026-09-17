# Changelog

## [Unreleased]

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
