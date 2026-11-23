# HoYo Code Monitor — Project Overview

> Локальный инструмент мониторинга промокодов HoYoverse и их автоматического погашения.
> Current release: **v1.6.0**.

## Problem

HoYoverse promo codes are scattered across wikis, HoYoLAB, socials and streams,
live 24–48h; daily check-ins are easy to miss. Manual checking and copy-paste
redemption are tedious.

## Users

- **Primary** — HoYoverse player on own Windows PC, wants auto-redeem + auto check-in.
- **Secondary** — power user (custom sources, stats, multi-account, multi-game).
- **Tertiary** — developer of custom sources.

## Key scenarios

| # | Scenario | Trigger | Outcome |
|---|----------|---------|---------|
| S1 | **Background polling** | Scheduler runs every `poll_interval_seconds` (default 15 min) | All enabled sources fetched, new codes stored in SQLite, auto-redeemed |
| S2 | **Auto-redeem** | New code detected | `GET webExchangeCdkey` per enabled account, configurable gap (default 8 s) |
| S3 | **Daily check-ins** | Cron-like schedule (default 04:00 + jitter) | `info → sign → home` per account × game, idempotent |
| S4 | **Auto cookie refresh** | Check-in fails with expired cookies | Headless re-capture from saved browser profile (opt-in, per-account cooldown) |
| S5 | **Manual run-once** | `hoyo-code-monitor run-once` or dashboard "Claim now" | Single fetch + redeem cycle, result printed to console / web UI |
| S6 | **Stats / dashboard** | Open `http://127.0.0.1:8000` | Total / redeemed / failed, per-source breakdown, redemption log |
| S7 | **Source management** | Add / edit / delete source in Web UI | SSRF + ReDoS validation, health status (`last_success`) |
| S8 | **Update check** | App startup | Read-only GitHub Releases poll, in-app banner (disableable) |

## Key features

- **Multi-source scraping** (23 presets: wikis, hoyo-codes, ennead, community JSON, guide sites), per-game filter.
- **Auto-redeem** with encrypted cookies (Fernet/AES-128), configurable gap, retry on 429/5xx.
- **Daily check-ins**: `info → sign → home`, idempotent log, catch-up on startup, progress API.
- **Per-source "active" health status**: a source only shows "active" after a real successful fetch (`sources.last_success`); a fresh failure drops it out immediately.
- **Auto cookie refresh**: when a check-in fails on expired cookies, the scheduler optionally re-captures cookies headless from the saved browser profile (opt-in, per-account cooldown), so monitoring keeps working without a manual re-login while the session is still valid.
- **Per-account enabled-games filter**: an account only checks the games it actually plays (avoids daily `-10002` "no character" skipped rows for unplayed games).
- **Notifications**: optional Telegram bot + local Windows toasts for new codes / successful redemptions; in-app GitHub Releases update banner (manual, read-only, disableable via `update_check_enabled = false` in config).
- **Statistics**: total / redeemed / failed, per-source breakdown, redemption log.
- **Web UI** on 127.0.0.1 only, 6 languages (EN/RU/DE/FR/JA/ZH) with a full translation of the check-in pages in all six.
- **CLI + system tray**, Windows autostart, graceful shutdown, rotating logs with secret filter.
- **Encrypted cookies** — Fernet (AES-128), key in env / OS keyring / local file.
- **Dark theme** — Light/Dark toggle in the sidebar; choice persists per browser.

## Constraints

Local only, single user, offline-capable core, no admin rights, Python 3.11+, Windows 10/11.

## Data locations

- **Frozen (installed)**: `%LOCALAPPDATA%\HoYoCodeMonitor\monitor.db` (SQLite WAL), `config.toml`, `logs/`, `data/.key`, `browser-profile/<account_slug>/`
- **Dev (from source)**: `data/` + `logs/` in repo root.
- Cookies Fernet-encrypted. No telemetry; nothing leaves the PC except requests to sources and the Hoyolab API.

## Integrations

Public read-only sources + Hoyolab redeem/check-in APIs (cookies). Cache locally;
fallback chain: Wiki → hoyo-codes → ennead.

## NFR

Start < 3 s, cycle < 30 s, RAM < 200 MB, idle CPU < 1 %, shutdown < 10 s.

## Scope

- **In**: monitoring, redeem, check-ins, CLI + Web UI, stats, encryption, tray,
  Inno Setup installer, Telegram/toast notifications, auto cookie refresh,
  in-app update banner.
- **Out**: multi-user, cloud, mobile, Discord bot, self-applying auto-update,
  native GUI, Prometheus /metrics (removed in v1.6.0).

## Assumptions (verified live)

- A1: Hoyolab `webExchangeCdkey` stable, ~6–8 s gap. ✓
- A2: user refreshes cookies manually (UI warns with no-cookies badge); optional headless auto-refresh covers the still-valid-session case without manual re-login. ✓
- A3: check-in `/info.today` is `YYYY-MM-DD`, `-5003` means already claimed. ✓
- A4: Playwright ~170 MB auto-download, browser sources off by default. ✓
- A5: ToT (Tears of Themis) check-in OS `act_id` verified live against HoYoLAB (no longer an open "no verified act_id" gap). ✓

## v1.6.0 security hardening

The v1.6.0 audit fixed 45 issues across 4 severity levels. Highlights:

| Area | What changed |
|---|---|
| **SSRF** | Source URLs resolving to private ranges (10.x, 172.16–31.x, 192.168.x, 127.x, 169.254.x, 0.0.0.0) or using non-HTTP schemes are rejected at creation/update |
| **ReDoS** | Regex extractor patterns with nested quantifiers (`(a+)+`, `(.*a)*`) are rejected |
| **XSS** | Source names, cookie values, and error strings rendered in HTML endpoints are escaped before insertion |
| **CSRF** | Per-process token seed is persisted to a date-stamped file; stale seeds rotate daily |
| **Game validation** | `POST /import` rejects payloads with unknown game fields |
| **Timeout passthrough** | Per-source `timeout_seconds` is forwarded to aiohttp |
| **Empty reward** | Redeemer stores `reward=""` instead of the literal `"Redeemed"` when the API returns no data |
| **Dashboard perf** | Stats path reduced from 20 SQL queries to 1 `GROUP BY`; redeemed codes list ordered in SQL |

All 45 fixes are covered by 30 new regression tests (see `CHANGELOG.md` v1.6.0 entry).
