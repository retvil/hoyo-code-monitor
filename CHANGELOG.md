# Changelog

## [Unreleased]

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
