# HoYo Code Monitor — Project Overview

## Working title
HoYo Code Monitor (HCM), current release **1.1.6**.

## Problem
HoYoverse promo codes are scattered across wikis, HoYoLAB, socials and streams,
live 24–48h; daily check-ins are easy to miss. Manual checking and copy-paste
redemption are tedious.

## Users
- Primary: HoYoverse player on own Windows PC, wants auto-redeem + auto check-in.
- Secondary: power user (custom sources, stats, multi-account).
- Tertiary: developer of custom sources.

## Use cases
1. Background monitoring every N minutes → new codes in local DB (25 presets).
2. Auto-redeem via Hoyolab API (opt-in per account, encrypted cookies).
3. Daily HoYoLAB check-ins on own schedule (Genshin, HSR, ZZZ, HI3), per-account toggles.
4. Manual `run-once` / "Claim now", stats, source/account management.
5. Local Web UI on 127.0.0.1 only, no server part.

## Key features
- Multi-source scraping (25 presets: wikis, hoyo-codes, ennead, guides), per-game filter.
- Auto-redeem with encrypted cookies, 8s gap, retry 429/5xx.
- Daily check-ins: `info → sign → home`, idempotent log, catch-up on startup, progress API.
- Stats (total/success/failed/by source/by game), logs, Prometheus /metrics.
- CLI + Web UI (6 languages), tray, autostart, graceful shutdown, rotating logs with secret filter.

## Constraints
Local only, single user, offline-capable core, no admin rights, Python 3.11+, Windows 10/11.

## Data
- Frozen: `%LOCALAPPDATA%\HoYoCodeMonitor\monitor.db` (SQLite WAL), `config.toml`, `logs/`.
- Dev: `data/` + `logs/` in repo root.
- Cookies Fernet-encrypted (env → keyring → file). No telemetry, nothing leaves PC
  except requests to sources and Hoyolab API.

## Integrations
Public read-only sources + Hoyolab redeem/check-in APIs (cookies). Cache locally,
fallback Wiki → GitHub → hoyo-codes → ennead.

## NFR
Start <3s, cycle <30s, RAM <200MB, idle CPU <1%, shutdown <10s.

## Scope
In: monitoring, redeem, check-ins, CLI+Web UI, stats, encryption, tray, NSIS installer.
Out: multi-user, cloud, mobile, Discord bot, auto-update, native GUI, plugins, ToT check-in
(no verified OS act_id yet).

## Assumptions (verified live)
- A1: Hoyolab `webExchangeCdkey` stable, ~6-8s gap. ✓
- A2: user refreshes cookies manually (UI warns with no-cookies badge). ✓
- A3: check-in `/info.today` is `YYYY-MM-DD`, `-5003` means already claimed. ✓
- A4: Playwright ~170MB auto-download, browser sources off by default. ✓
