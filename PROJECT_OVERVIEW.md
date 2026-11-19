# hoym-code-monitor — Project Overview

> HoYo Code Monitor — локальный инструмент мониторинга промокодов HoYoverse и их автоматического погашения.

## Purpose

Automatically find, store, and redeem promotional codes for HoYoverse games (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Honkai Impact 3rd, Tears of Themis) without manual intervention. Eliminates the daily grind of checking 10+ code-source websites and entering codes into the HoYoverse website.

## Target user

- **Single-user Windows desktop gamer** who plays one or more HoYoverse games
- Does not want to manually check multiple sources and type codes into a web form
- Runs the app as a background tray process alongside the game
- Has accounts on HoYoverse (HoYoLAB) with auto-redeem enabled

## Key scenarios

| # | Scenario | Trigger | Outcome |
|---|----------|---------|---------|
| S1 | **Background polling** | Scheduler runs every `poll_interval_seconds` (default 15 min) | All enabled sources fetched, new codes stored in SQLite, auto-redeemed |
| S2 | **Manual dashboard** | User opens `http://127.0.0.1:8000` in browser | Live view of pending codes, redemption log, source health, per-account stats |
| S3 | **Manual single-code redeem** | User clicks "Redeem" button in dashboard | Code sent to HoYoLAB API via account's stored cookies; result shown as inline badge + toast |
| S4 | **Redeem all pending** | User clicks "Redeem All" button | All pending codes looped with 8-second gap between calls; aggregate result shown |
| S5 | **Daily check-in** | Scheduler reaches configured check-in time window | Auto-claims daily rewards for all accounts with `checkin_enabled` on |
| S6 | **Cookie refresh** | Scheduler detects `cookie-expired` retcode (10001/-100) | Headless Playwright browser re-login using saved profile; cookies re-encrypted and stored |
| S7 | **Telegram notification** | A new code is found OR a check-in succeeds | Optional Telegram bot message sent to user |
| S8 | **Windows toast** | A code is successfully redeemed or check-in completes | WinRT toast notification in system tray area |

## Architecture at a glance

```
                    ┌─────────────────────────────────────────┐
                    │  CLI (Click)  /  Tray (pystray)       │
                    │  · start/stop/status/stats/health     │
                    │  · accounts login/logout/show         │
                    │  · notify test / run-once             │
                    └──────────────┬──────────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────────┐
                    │  Scheduler (asyncio task, 15-min loop) │
                    │  · fetch → dedupe → store → auto-redeem │
                    │  · check-in slots (catch-up on wake)   │
                    │  · cookie-expired → auto headless refresh│
                    └──────┬───────────┬───────────────────────┘
                           │           │
              ┌────────────▼──┐  ┌────▼────────────────────────┐
              │  Sources      │  │  Redeemer (aiohttp)         │
              │  (15+ URL    │  │  · webExchangeCdkey GET     │
              │   fetchers)  │  │  · HoYoLAB retcode parsing  │
              └��──────┬───────┘  └────┬────────────────────────┘
                      │               │
              ┌───────▼───────────────▼────────────────────────┐
              │  Storage (SQLite WAL, Fernet-encrypted cookies)│
              │  · codes / redemption_log / accounts / sources│
              └────────────────────────────────────────────────┘
                      │
              ┌───────▼───────────────┐
              │  Web UI (FastAPI)     │
              │  · HTMX live dashboard│
              │  · 40+ routes         │
              │  · CSRF-protected POST│
              │  · Prometheus /metrics│
              └────────────────────────┘
```

## Module map

| Module | Responsibility | Key invariants |
|--------|----------------|----------------|
| `src/config.py` | TOML config + typed `Settings` dataclass | `cookies` never persisted; legacy `load_config_from_storage` transitional |
| `src/storage.py` | SQLite layer: codes, logs, accounts, sources, Fernet cookie encryption | Single WAL DB; schema versioned via `migrations/`; 5000-row fetch cap |
| `src/redeemer.py` | HoYoLAB API client: `webExchangeCdkey` GET/POST | Defensive retcode parsing; 8s configurable gap; `http_session` pool |
| `src/scheduler.py` | Check cycle: fetch → dedupe → store → auto-redeem; check-in slots | Catches up missed check-ins after PC sleep/wake; auto-disables dead sources |
| `src/sources.py` | 15+ URL fetchers: HTML CSS/regex + JSON API extractors | Per-host rate limit; SSRF guards; ReDoS-safe regex; 3 retries w/ exponential backoff |
| `src/cookies_login.py` | Playwright browser-based cookie capture + Fernet encryption | Headless or visible; persistent Chromium profile; per-game login flow |
| `src/checkin.py` | HoYoLAB check-in API + claim logic | Per-account cooldown; catch-up after missed windows |
| `src/web_ui.py` | FastAPI + HTMX dashboard; 40+ routes; CSRF; Prometheus | 1708 lines (⚠️ monolith — see ROADMAP.md) |
| `src/cli.py` | Click CLI: start/stop/status/stats/health/accounts/notify/run-once | Thin layer over scheduler/storage/redeemer |
| `src/tray.py` | pystray system tray + embedded web server | 127.0.0.1-only binding; port 8000 (frozen) |
| `src/system_notify.py` | WinRT toast notifications (winotify) | Best-effort; never raises |
| `src/i18n.py` | 6-language translations (en/ru/zh/ja/ko/fr) | en-fallback; key-parity test |
| `src/constants.py` | `GAME_CONF` (per-game API host, game_biz), `APP_VERSION`, `WEB_HOST/PORT` | Version read from `pyproject.toml` |
| `src/security.py` | CSRF middleware, `_safe_detail` scrubbing | Same-origin check; token in `X-CSRF-Token` header |
| `src/http_session.py` | Cross-loop aiohttp session pool | Thread-safe; per-event-loop sessions |

## Data model

```
accounts (name PK, uid, region, game_biz, lang, s_lang_key, games)
  └─ config: cookies_<name> (Fernet-encrypted JSON), redeem_state, checkin_state, device_<name>
  └─ redemption_log (code, account_id FK, status, reward, error_message, attempted_at, redeemed_at)

codes (code PK, game, redeemed, reward, attempted_at, redeemed_at, published_at, expires_at)
  └─ code_sources (code, source)  [junction table]
  └─ display_status = f(redeemed, last_log_retcode)  [computed, not stored]

sources (name PK, url, selector_type, selector, enabled, last_checked, last_success, error_count, ...)
```

## Technology stack (with rationale)

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11 | `tomllib` + `datetime.UTC` native; asyncio maturity |
| Web framework | FastAPI + HTMX | Async routes + server-driven UI with zero JS build step |
| Database | SQLite (WAL) | Single-user local data; `busy_timeout=5000` + WAL for concurrent access |
| HTTP client | aiohttp | Async, connection pooling, `http_session.py` per-loop pool |
| CLI | Click | Thin, no magic; consistent with codebase |
| Browser automation | Playwright (Chromium) | Persistent-profile cookie capture; headless or visible |
| Encryption | Fernet (symmetric) | Local keyring/file key; correct threat model for single-user |
| Tray | pystray | Cross-platform; Windows-only in practice |
| Toasts | winotify (WinRT) | Native Windows notifications; never raises |
| Packaging | PyInstaller + Inno Setup | Single-file bundle + GUI installer |
| CI/CD | GitHub Actions | Lint/test → PyInstaller → Inno Setup → upload artifact → Docker build |
| Container | Docker (python:3.11-slim) | Optional; `playwright install chromium` at build time |

## Key invariants (do not break)

1. **CSRF on every state-changing POST/PUT/PATCH/DELETE** — token in `X-CSRF-Token` header, validated against `secrets.compare_digest`; token rotates at UTC day boundary
2. **Cookies encrypted at rest** — Fernet, key resolved: env `HCM_COOKIE_KEY` → keyring → file → generate
3. **Single instance** — PID lock file + stale-lock auto-cleanup
4. **127.0.0.1 binding only** — web server never exposed to network
5. **No secrets in logs** — `_safe_detail` scrubs cookie/token patterns from exception text
6. **Display status is computed, not stored** — derived from `codes.redeemed` + latest `redemption_log.retcode`
7. **Per-game API hosts** — `GAME_CONF` maps game → API host + `game_biz`; ZZZ uses POST, all others GET
8. **8-second minimum gap between redemption calls** — configurable via `redemption_min_gap_seconds` (min 6)
9. **Catch-up on PC wake** — missed check-in slots are retroactively claimed up to 3 days
10. **Source auto-disable** — 3 consecutive failures flip display to "error"; `error_count` resets on any success

## What is MVP-grade vs over-engineered (from audit)

**MVP-grade (simpler than ideal):**
- Fernet key 4-tier fallback (env → keyring → file → generate) — the `data/.key` alt-path is legacy
- `config.py:load_config_from_storage` — transitional, should be removed once scheduler consumes `Settings`

**Over-engineered for current user base:**
- Prometheus `/metrics` endpoint — single-user tray app has no scrapers
- 24+ `SOURCE_PRESETS` in `sources.py` (Reddit 403, Nitter dead, YouTube JS) — aspirational
- i18n 6 languages — de/fr/ja are maintenance liability; en + ru + zh cover actual users

## Critical known issues (from architecture audit)

| ID | Severity | Description | File |
|----|----------|-------------|------|
| C-1 | ❌ | `web_ui.py` is a 1708-line monolith; redemption write-path duplicated 3× (scheduler, `redeem_single_code`, `redeem_all_codes`) | `web_ui.py`, `scheduler.py` |
| C-2 | ❌ | Shared `browser-profile/` dir — logging in as account B overwrites account A's session | `cookies_login.py` |
| C-3 | ⚠️ | Missing hot-path indexes: `idx_codes_unredeemed(redeemed, attempted_at)`, `idx_redemption_log_code` | `storage.py` |
| C-4 | ❌ | No tests for: `/redeem/all`, HTML-fragment response path, browser profile collision, scheduler catch-up cooldown | `tests/` |

## Version and release

- `APP_VERSION` = `1.5.2` (in `src/constants.py`)
- CI reads version live from `pyproject.toml` and passes to Inno Setup
- Releases tagged `vX.Y.Z` on GitHub; draft-release job on tag push

## Documentation

| File | Purpose |
|------|---------|
| `README.md` (+ 5 translations) | Install, usage, FAQ, screenshots |
| `docs/CHANGELOG.md` | Keep-a-changelog format; `[Unreleased]` + all versions |
| `ROADMAP.md` | Specific improvement items with `file:line` references |
| `CONTRIBUTING.md` | Dev setup, test/lint/typecheck, release checklist |
| `LICENSE` | MIT |
