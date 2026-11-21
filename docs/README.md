# HoYo Code Monitor

[![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Platform Windows](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/retvil/hoyo-code-monitor/releases)

**Never miss a HoYoverse promo code again - local monitoring and auto-redeem for 5 games, right on your PC.**

[🇬🇧 English](../README.md) | [🇷🇺 Русский](README.ru.md) | [🇺🇦 Українська](README.uk.md) | [🇰🇿 Қазақша](README.kk.md) | [🇩🇪 Deutsch](README.de.md) | [🇫🇷 Français](README.fr.md) | [🇪🇸 Español](README.es.md) | [🇯🇵 日本語](README.ja.md) | [🇵🇱 Polski](README.pl.md) | [🇹🇷 Türkçe](README.tr.md) | [🇨🇳 中文](README.zh.md) | [🇹🇼 繁體中文](README.zh-TW.md)

## What is this?

HoYoverse games regularly release time-limited promo codes - and they expire fast. HoYo Code Monitor watches code sources across 5 games (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Honkai Impact 3rd, Tears of Themis) and redeems new codes to your accounts automatically. Everything runs locally on your PC: SQLite database, encrypted cookies, no telemetry, no cloud.

## Features

- **Background monitoring** - checks sources every N minutes (configurable, default 15)
- **Auto-redeem** - redeems new codes via Hoyolab webExchangeCdkey API (opt-in, per account)
- **Daily check-ins** - auto sign-in on HoYoLAB for all 5 games
- **Multi-source** - Wiki, community JSON APIs, guide sites
- **Multi-account** - each account has its own encrypted cookies and redeem toggle
- **Auto cookie refresh** - re-capture cookies headless from saved browser profile
- **Dark theme** - Light/Dark toggle in sidebar
- **Statistics** - total / redeemed / failed, per-source breakdown
- **Web UI** - local dashboard at http://127.0.0.1:8000
- **System tray** - icon with enable/disable, scan-interval submenu
- **Encrypted cookies** - Fernet (AES-128)
- **Autostart** - Windows login autostart

## Quick start

```powershell
# 1. Install and launch - the app lives in the system tray
# 2. Add an account (region: os_usa / os_euro / os_asia / os_cht)
hoyo-code-monitor accounts add main <UID> <REGION>

# 3. Capture cookies once (browser opens, you log in once)
hoyo-code-monitor accounts login main

# 4. Enable auto-redeem
hoyo-code-monitor config set redemption_enabled true
```

5. Open the dashboard: http://127.0.0.1:8000

## Install from source

Requires Python 3.11+.

```powershell
pip install -e .
python -m playwright install chromium
```

Run in tray / one-shot check / Web UI:

```powershell
hoyo-code-monitor tray
hoyo-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

## Author & support

**[Nod33Eset](https://github.com/retvil)** | [sdinc.dev](https://sdinc.dev)
Never miss a HoYoverse promo code again - local monitoring and auto-redeem for 5 games, right on your PC.

**Support**
- **Issues / PRs:** [github.com/retvil/hoyo-code-monitor/issues](https://github.com/retvil/hoyo-code-monitor/issues)
- **Telegram:** [@Nod33Eset](https://t.me/Nod33Eset)
- **Email:** [hello@sdinc.dev](mailto:hello@sdinc.dev)

**Crypto**
- BTC: `bc1qunld3rsp37qf5gg69aune50y0qqkd0eugg7j97`
- TON: `UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC`
- USDT (TRC20): `TBPJSSLu1mUcX54g9UyxUohYGf2fuRvbwd`
- USDT (ERC20): `0x25CAED3776Ef5b18E03392bC5b254Bbd78E8180C`
- USDT (SOL): `3qgN5z291CEcj2FUi2Zza5DioxKgNw72kC7P52pCcTrG`

## License

MIT License - see [LICENSE](LICENSE) for details.
