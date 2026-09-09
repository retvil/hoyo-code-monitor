# HoYo Code Monitor

Local Windows app that monitors Genshin Impact promo-code sources and auto-redeems new codes via the Hoyolab API. Everything stays on your PC: SQLite database, encrypted cookies, no telemetry, no cloud.

> Read this in: [Русский](README.ru.md) · [Deutsch](README.de.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [中文](README.zh.md)

## Features

- **Background monitoring** — checks sources every N minutes (configurable, default 15)
- **Auto-redeem** — redeems new codes via Hoyolab `webExchangeCdkey` API (opt-in, per account)
- **Multi-source** — Wiki, Wiki API, community JSON APIs, guide sites (16 presets, see table)
- **Multi-account** — each account has its own encrypted cookies and redeem toggle
- **Statistics** — total / redeemed / pending, per-source breakdown, redemption log
- **Web UI** — local dashboard at `http://127.0.0.1:8000` in 6 languages
- **System tray** — icon with enable/disable, scan-interval submenu, one-click settings
- **Encrypted cookies** — Fernet (AES-128), key in env / OS keyring / local file
- **Autostart** — optional Windows login autostart

## Sources (verified live)

| Source | Type | Status |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | May return 403 (Fandom protection) |
| Genshin Wiki API | JSON | Working |
| `hoyo-codes.seria.moe` | JSON API | Working |
| `api.ennead.cc` (x2 endpoints) | JSON API | Working |
| Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge | CSS guides | Working |

## Install

Requires Python 3.11+.

```powershell
pip install -e .
# Playwright browser for JS-rendered sources (optional)
python -m playwright install chromium
```

## Usage

```powershell
# Add account + auto-capture cookies (browser opens, you log in once)
genshin-code-monitor accounts add main <UID> <REGION>   # region: os_usa / os_euro / os_asia / os_cht
genshin-code-monitor accounts login main

# Enable auto-redeem (or toggle per account in Web UI)
genshin-code-monitor config set redemption_enabled true

# Run in tray (recommended) / one-shot check / Web UI
genshin-code-monitor tray
genshin-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

Web UI: `http://127.0.0.1:8000` — Dashboard, Sources, Accounts, Config (EN/RU/DE/FR/JA/ZH switcher in sidebar).

## How redemption works

1. Scheduler fetches enabled sources, extracts codes (`[A-Z0-9]{8,14}`), stores new ones.
2. For each account with auto-redeem ON: `GET webExchangeCdkey` with account cookies, 8s gap.
3. Result recorded: `success` → Done + reward; `-2017/-2018` → already claimed (counts as Done); `-2001` expired, `-2003` invalid/CN-only.

## FAQ

- **Code shows Pending?** Check cookies (they expire), `redemption_enabled`, per-account toggle, and the error in Redemption log.
- **`-1071 "Please log in"`?** Re-run `accounts login` — the cookie set was incomplete.
- **Data location?** `data/monitor.db`, `config.toml`, `logs/`, `data/.key`. Copy `data/` for backup.

## Author & support

See the About block in the app dashboard (contacts, donation links and crypto addresses are configured there).

## License

MIT
