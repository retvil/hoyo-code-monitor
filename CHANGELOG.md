# Changelog

## [1.2.4] - 2026-10-14

### Fixed
- **Release notes in the update banner showed raw Markdown**: the banner renders
  notes as plain text, but `_clean_notes()` only collapsed whitespace, so a
  GitHub release body arrived with literal `###` headings and `**bold**` markers
  visible to the user. Inline syntax (headings, emphasis, strikethrough, code,
  links, list markers, blockquotes, images) is now stripped, leaving readable
  prose. Notes stay rendered as text rather than HTML, so upstream-authored
  markdown has no injection surface. Caught by driving a real browser, not by the
  unit suite

## [1.2.3] - 2026-10-11

### Added
- **In-app update check with release banner**: the Web UI now queries the public
  GitHub Releases API and shows a dismissible banner when a newer version exists,
  with the release notes and a download link. Updates are **manual** — the banner
  links to the GitHub Releases page and you download and run the new installer
  yourself; the app never downloads or applies an update on its own. This is the
  only outbound call the app makes beyond the user-configured sources. The check
  is read-only (no token, no telemetry, no device identifiers), cached for
  `UPDATE_CHECK_INTERVAL_SECONDS` (6h, failed attempts included), never raises —
  every failure keeps the banner hidden — and can be disabled with
  `update_check_enabled = false` in config or by dismissing the banner (per
  release, so a newer build re-arms it)

### Fixed
- **`increment_source_error()` crashed on every failed fetch**: the `sources.error_count`
  column was referenced by `storage.increment_source_error()` (`src/storage.py:729`) and
  by `web_ui`'s source-health payload (`error_count` / `"error"` state), but was never
  created by any migration — every call raised `OperationalError: no such column:
  error_count`. The exception was swallowed by a `try/except` in
  `SourceFetcher.fetch_all_enabled()` (`src/sources.py:523`), so the failure was
  invisible and the `"error"` source state in `/health` was dead code. Added migration
  **v14** to create `sources.error_count INTEGER NOT NULL DEFAULT 0` and bumped
  `CURRENT_VERSION` to 14

## [1.2.2] - 2026-10-10

### Added
- **CSRF protection for Web UI**: all state-changing routes (POST/PUT/PATCH/DELETE)
  require a valid `X-CSRF-Token` header; token served via `/api/csrf-token` endpoint
  and double-submit cookie pattern; same-origin check blocks cross-origin mutations
- **Scheduler health in `/health`**: endpoint now reports DB status, active source count,
  scheduler state (running/stopped/missing), and external connectivity probe
- **Config schema migrations**: `ConfigManager.MIGRATIONS` framework with `schema_version`
  field for forward-compatible config upgrades
- **`MAX_MASKED_UID` constant**: configurable UID masking width in CLI `config show`

### Fixed
- **Scheduler leaked HTTP/Playwright sessions on stop**: added async `_cleanup()` that
  closes `checkin_runner` and `redeemer` sessions in the scheduler loop before thread
  exit; removed the unsafe `asyncio.run(self.close())` call from the sync `stop()` path
- **Telegram notifications failed silently on transient errors**: `send_telegram()` now
  retries up to 3 times with exponential backoff (1s/2s/4s); logs HTTP status and
  exception details per attempt
- **Duplicate source-building boilerplate**: extracted `SourceConfig.from_row()` class
  method to normalize legacy JSON-stringified headers and apply safe defaults in one place
- **Win32 registry imports were inside functions**: moved `winreg` imports to module level
  in `autostart.py` (linting/readability)
- **Single-instance guard used `global`**: replaced with mutable list container to avoid
  ruff `PLW0603` (global statement) warning
- **Error messages leaked raw exception strings in API responses**: wrapped all
  `HTTPException(detail=str(e))` with `_safe_detail()` that masks secret values

### Changed
- Test fixtures (`temp_db`, `storage`) moved from individual test classes to shared
  `tests/conftest.py` (DRY, 6 test classes cleaned up)
- Removed inline `import uvicorn`/`import app` from `cli.py` tray() — imported at
  module level with `# noqa: F401` annotations

## [1.2.1] - 2026-10-08

### Fixed
- **Tests broke on modern asyncio**: `signals._stop_scheduler()` used the deprecated
  `loop.run_in_executor(None, ...)` path; updated to `asyncio.to_thread(...)` and
  aligned all related test assertions accordingly

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
