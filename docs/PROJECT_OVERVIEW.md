# Genshin Code Monitor — Project Overview

## Working title
Genshin Code Monitor (GCM)

## Problem
Genshin Impact promo codes are scattered across Wiki, HoYoLAB, socials and streams, live 24–48h, manual checking is tedious, official redemption is manual copy-paste.

## Users
- Primary: Genshin player on own Windows PC, wants auto-redeem.
- Secondary: power user (custom sources, stats).
- Tertiary: developer of custom sources.

## Use cases
1. Background monitoring every N minutes → new codes in local DB.
2. Auto-redeem via Hoyolab API (opt-in, encrypted cookies).
3. Manual `run-once`, stats, source/account management.
4. Local Web UI on 127.0.0.1 only, no server part.

## Key features
- Multi-source scraping (Wiki, Wiki API, GitHub Archive, hoyo-codes, ennead, HoYoLAB optional).
- Auto-redeem with encrypted cookies, 6s gap, retry 429/5xx.
- Stats (total/success/failed/by source), logs, Prometheus /metrics.
- CLI + Web UI, graceful shutdown, rotating logs with secret filter.

## Constraints
Local only, single user, offline-capable core, no admin rights, Python 3.11+.

## Data
`data/monitor.db` (SQLite WAL), `config.toml`, `logs/`, `data/.key` (600). Cookies Fernet-encrypted (env → keyring → file). No telemetry, nothing leaves PC.

## Integrations
Public read-only sources + Hoyolab redeem API (cookies). Cache locally, fallback Wiki → GitHub → hoyo-codes → ennead.

## NFR
Start <3s, cycle <30s, RAM <200MB, idle CPU <1%, shutdown <10s.

## Scope v1
In: monitoring, 5 sources, redeem, CLI+Web UI, stats, encryption, tray, NSIS installer.
Out: multi-user, cloud, mobile, Discord bot, auto-update, native GUI, plugins.

## Unknowns / assumptions
- A1: Hoyolab webExchangeCdkey stable, ~6s limit.
- A2: user refreshes cookies manually.
- A3: Wiki+GitHub+hoyo-codes cover ~95%.
- A4: Playwright ~150MB optional, browser sources off by default.
