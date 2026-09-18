# HoYo Code Monitor

[![Release](https://img.shields.io/github/v/release/retvil/hoyo-code-monitor?sort=date)](https://github.com/retvil/hoyo-code-monitor/releases) [![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Platform Windows](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/retvil/hoyo-code-monitor/releases)

**Никогда больше не пропускайте промокоды HoYoverse — локальный мониторинг и автопогашение для 5 игр прямо на вашем ПК.**

[🇬🇧 English](README.md) | **🇷🇺 Русский** | [🇩🇪 Deutsch](README.de.md) | [🇫🇷 Français](README.fr.md) | [🇯🇵 日本語](README.ja.md) | [🇨🇳 中文](README.zh.md)

## Что это?

Игры HoYoverse регулярно выпускают промокоды с ограниченным сроком действия — и они быстро протухают. **HoYo Code Monitor** следит за 16 источниками кодов в 5 играх (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Honkai Impact 3rd, Tears of Themis) и автоматически погашает новые коды на ваших аккаунтах. Всё работает локально на вашем ПК: SQLite-база, зашифрованные куки, никакой телеметрии и облаков.

### Как это работает

1. Планировщик опрашивает включённые источники, извлекает коды (`[A-Z0-9]{8,14}`), сохраняет новые.
2. Для каждого аккаунта с включённым автопогашением: `GET webExchangeCdkey` с куками аккаунта, пауза 8с между погашениями.
3. Результат записывается: `success` → Done + награда; `-2017/-2018` → уже погашен (считается Done); `-2001` протух, `-2003` невалиден/только Китай.

## Возможности

- **Фоновый мониторинг** — проверка источников каждые N минут (настраивается, по умолчанию 15)
- **Автопогашение** — погашение новых кодов через Hoyolab `webExchangeCdkey` API (опционально, отдельно для каждого аккаунта)
- **Мульти-источники** — Wiki, Wiki API, community JSON API, гайд-сайты (16 пресетов, см. таблицу)
- **Мульти-аккаунт** — у каждого аккаунта свои зашифрованные куки и свой тумблер погашения
- **Статистика** — всего / погашено / ожидают, разбивка по источникам, журнал погашений
- **Web UI** — локальный дашборд `http://127.0.0.1:8000` на 6 языках
- **Системный трей** — иконка с вкл/выкл, подменю периода сканирования, открытие настроек в один клик
- **Шифрование куков** — Fernet (AES-128), ключ в env / системном хранилище / локальном файле
- **Автозапуск** — опциональный старт при входе в Windows

## Скриншоты

<details>
<summary>Дашборд / Источники / Настройки / Об авторе</summary>

| Дашборд | Источники | Настройки |
|---|---|---|
| ![Дашборд](docs/screenshots/dashboard_ru.png) | ![Источники](docs/screenshots/sources_ru.png) | ![Настройки](docs/screenshots/config_ru.png) |

| Об авторе |
|---|
| ![Об авторе](docs/screenshots/author_ru.png) |

</details>

## Источники (проверены живьём)

| Источник | Тип | Статус |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | Может отдавать 403 (защита Fandom) |
| Genshin Wiki API | JSON | Работает |
| `hoyo-codes.seria.moe` | JSON API | Работает |
| `api.ennead.cc` (2 эндпоинта) | JSON API | Работает |
| Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge | CSS-гайды | Работают |

## Готовые сборки

Скачайте установщик из [Releases](https://github.com/retvil/hoyo-code-monitor/releases):

- **Windows** — `hoyo-code-monitor-1.0.0-beta.3-setup.exe` (установка для текущего пользователя, права администратора не нужны)

Тихая установка: `setup.exe /S`. Опциональные компоненты: ярлык на рабочем столе, автозагрузка Windows.

> **Примечание:** При первом входе через браузер приложение скачает Chromium (~170 МБ, один раз).

## Быстрый старт

```powershell
# 1. Установите и запустите — приложение живёт в системном трее
# 2. Добавьте аккаунт (регион: os_usa / os_euro / os_asia / os_cht)
genshin-code-monitor accounts add main <UID> <REGION>

# 3. Один раз получите куки (откроется браузер, залогиньтесь один раз)
genshin-code-monitor accounts login main

# 4. Включите автопогашение (или тумблером у аккаунта в Web UI)
genshin-code-monitor config set redemption_enabled true
```

5. Откройте дашборд: `http://127.0.0.1:8000` — Dashboard, Sources, Accounts, Config (переключатель EN/RU/DE/FR/JA/ZH в сайдбаре).

## Установка из исходников

Требуется Python 3.11+ ([python.org](https://python.org)).

```powershell
pip install -e .
# Браузер Playwright для JS-источников (опционально)
python -m playwright install chromium
```

Запуск в трее (рекомендуется) / разовая проверка / Web UI:

```powershell
genshin-code-monitor tray
genshin-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

## FAQ

- **Код висит в Pending?** Проверьте куки (протухают), `redemption_enabled`, тумблер у аккаунта и ошибку в журнале погашений.
- **`-1071 "Please log in"`?** Повторите `accounts login` — набор куков неполный.
- **Где данные?** `data/monitor.db`, `config.toml`, `logs/`, `data/.key`. Для бэкапа скопируйте `data/`.

## Автор и поддержка

См. блок «Об авторе» на дашборде приложения или ниже:

**Криптовалюта:**

- BTC: `bc1qunld3rsp37qf5gg69aune50y0qqkd0eugg7j97`
- TON: `UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC`
- USDT (TRC20): `TBPJSSLu1mUcX54g9UyxUohYGf2fuRvbwd`
- USDT (ERC20): `0x25CAED3776Ef5b18E03392bC5b254Bbd78E8180C`
- USDT (SOL): `3qgN5z291CEcj2FUi2Zza5DioxKgNw72kC7P52pCcTrG`

## Лицензия

MIT
