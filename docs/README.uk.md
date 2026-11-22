# HoYo Code Monitor

[![Release](https://img.shields.io/github/v/release/retvil/hoyo-code-monitor?sort=date)](https://github.com/retvil/hoyo-code-monitor/releases) [![License MIT](https://img.shields.io/badge/license-MIT-green)](../LICENSE) [![Platform Windows](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/retvil/hoyo-code-monitor/releases)

[🇬🇧 English](../README.md) | [🇷🇺 Русский](README.ru.md) | **🇺🇦 Українська** | [🇰🇿 Қазақша](README.kk.md) | [🇩🇪 Deutsch](README.de.md) | [🇫🇷 Français](README.fr.md) | [🇪🇸 Español](README.es.md) | [🇯🇵 日本語](README.ja.md) | [🇵🇱 Polski](README.pl.md) | [🇹🇷 Türkçe](README.tr.md) | [🇨🇳 中文](README.zh.md) | [🇹🇼 繁體中文](README.zh-TW.md)

## Що це?

Ігри HoYoverse регулярно випускають промокоди з обмеженим терміном дії — і вони швидко згорають. **HoYo Code Monitor** стежить за 23 джерелами кодів у 5 іграх (Genshin Impact, Honkai: Star Rail, Zenless Zone Zero, Honkai Impact 3rd, Tears of Themis) і автоматично погашає нові коди на ваших акаунтах. Усе працює локально на вашому ПК: база SQLite, зашифровані куки, жодної телеметрії та хмар.

### Як це працює

1. Планувальник опитує увімкнені джерела, витягує коди (`[A-Z0-9]{8,14}`), зберігає нові.
2. Для кожного акаунта з увімкненим автопогашенням: `GET webExchangeCdkey` з куками акаунта, налаштовувана пауза між погашеннями (типово 8 с).
3. Результат записується: `success` → Done + нагорода; `-2017/-2018` → вже погашено (вважається Done); `-2001` прострочено, `-2003` невалідний/тільки Китай.
4. Щоденні відмітки HoYoLAB ідуть за власним розкладом (типово 04:00 + розкид): `info → sign → home` на акаунт × гру, тими самими куками, результат — на сторінці «Чек-іни».
5. Якщо відмітка впала через прострочені куки, планувальник може **автоматично оновити їх у headless-режимі** зі збереженого браузерного профілю (опційний перемикач, пер-акаунт кулдаун) — без ручного повторного входу, поки збережена сесія валідна.

## Можливості

- **Фоновий моніторинг** — перевірка джерел кожні N хвилин (налаштовується, типово 15)
- **Автопогашення** — погашення нових кодів через Hoyolab `webExchangeCdkey` API (опційно, окремо для кожного акаунта)
- **Щоденні відмітки** — авто-чек-ін у HoYoLAB для всіх 5 ігор (опційно, окремо для кожного акаунта, власний розклад, ідемпотентно)
- **Мульти-джерела** — Wiki, Wiki API, community JSON API, гайд-сайти (23 пресети)
- **Мульти-акаунт** — у кожного акаунта свої зашифровані куки та свій перемикач погашення
- **Автооновлення кук** — при падінні відмітки через прострочені куки вони автоматично захоплюються заново в headless-режимі
- **Статус «активний» по джерелах** — джерела, успішно перевірені, відображаються як «активні»
- **Статистика** — всього / погашено / провалено, розбивка по джерелах, журнал погашень
- **Web UI** — локальний дашборд `http://127.0.0.1:8000` на 6 мовах
- **Системний трей** — іконка з вкл/викл, підменю періоду сканування, відкриття налаштувань в один клік
- **Шифрування кук** — Fernet (AES-128), ключ у env / системному сховищі / локальному файлі
- **Темна тема** — перемикач Light/Dark у бічній панелі; вибір запам'ятовується в браузері
- **Автозапуск** — старт при вході в Windows (увімкнено типово)

## Скріншоти

<details>
<summary>Дашборд / Джерела / Налаштування / Чек-іни / Акаунти / Про автора</summary>

| Дашборд | Джерела | Налаштування |
|---|---|---|
| ![Дашборд](screenshots/dashboard_en.png) | ![Джерела](screenshots/sources_en.png) | ![Налаштування](screenshots/config_en.png) |

| Про автора |
|---|
| ![Про автора](screenshots/author_en.png) |

| Чек-іни | Акаунти |
|---|---|
| ![Чек-іни](screenshots/checkins_en.png) | ![Акаунти](screenshots/accounts_en.png) |

</details>

## Джерела (перевірені наживо)

| Джерело | Тип | Статус |
|---|---|---|
| Genshin Wiki (Fandom) | CSS | May return 403 (Fandom protection) |
| Genshin Wiki API | JSON | Working |
| `hoyo-codes.seria.moe` | JSON API | Working |
| `api.ennead.cc` (x2 endpoints) | JSON API | Working |
| Pocket Tactics, TheClick, Eurogamer, MMO Culture, Playnforge | CSS guides | Working |

## Встановлення з інсталятора

Завантажте останній реліз з [GitHub Releases](https://github.com/retvil/hoyo-code-monitor/releases):

| Файл | Опис |
|---|---|
| `hoyo-code-monitor-X.Y.Z-setup.exe` | Inno Setup інсталятор (для поточного користувача, права адміністратора не потрібні) |

### Інтерактивне встановлення

1. Запустіть `.exe` — буде запитано місце встановлення
2. Натисніть **Далі** — доступн�� два компоненти: ярлик на робочому столі та автозапуск Windows
3. Натисніть **Встановити** — готово за ~30 с. Застосунок запускається в системному треї.

### Тихе встановлення (скрипти / GPO / SCCM)

```powershell
# Per-user install, no prompts
hoyo-code-monitor-1.5.3-setup.exe /S

# Install to a specific directory
hoyo-code-monitor-1.5.3-setup.exe /S /D=C:\Games\HoYoMonitor

# No desktop shortcut, no autostart
hoyo-code-monitor-1.5.3-setup.exe /S /desktop=no /startup=no
```

### Видалення

- **Панель керування** → Програми та компоненти → "HoYo Code Monitor" → Видалити
- **Тихо**: `uninstall.exe /S`
- Або видаліть теку встановлення та ключ реєстру `HKCU\Software\HoYoCodeMonitor`

### Розташування даних (зберігаються між видаленням/перевстановленням)

| Що | Де |
|---|---|
| SQLite database | `%LOCALAPPDATA%\HoYoCodeMonitor\monitor.db` |
| `config.toml` (settings, source definitions) | `%LOCALAPPDATA%\HoYoCodeMonitor\config.toml` |
| Encrypted Fernet key | OS keyring (Windows Credential Manager) |
| Logs | `%LOCALAPPDATA%\HoYoCodeMonitor\logs\` |
| Browser profile (Playwright Chromium) | `%LOCALAPPDATA%\HoYoCodeMonitor\browser-profile\` |

> Зробіть резервну копію `data/` + `config.toml` перед мажорним оновленням.

## Швидкий старт

```powershell
# 1. Install and launch - the app lives in the system tray
# 2. Add an account (region: os_usa / os_euro / os_asia / os_cht)
hoyo-code-monitor accounts add main <UID> <REGION>

# 3. Capture cookies once (browser opens, you log in once)
hoyo-code-monitor accounts login main

# 4. Enable auto-redeem (or toggle per account in the Web UI)
hoyo-code-monitor config set redemption_enabled true
```

5. Open the dashboard: `http://127.0.0.1:8000`

## Встановлення з вихідного коду

Потрібен Python 3.11+ ([python.org](https://python.org)).

```powershell
pip install -e .
# Playwright browser for JS-rendered sources (optional)
python -m playwright install chromium
```

Запуск у треї (рекомендовано) / разова перевірка / Web UI:

```powershell
hoyo-code-monitor tray
hoyo-code-monitor run-once
python -m uvicorn src.web_ui:app --host 127.0.0.1 --port 8000
```

## FAQ

- **Код висить у Pending?** Перевірте куки (прострочуються), `redemption_enabled`, перемикач у акаунта та помилку в журналі погашень.
- **`-1071 "Please log in"`?** Повторіть `accounts login` — набір кук неповний.
- **Де дані?** `data/monitor.db`, `config.toml`, `logs/`, `data/.key`. Для бекапу скопіюйте `data/`.

## Автор і підтримка

Див. блок «Про автора» на дашборді застосунку або нижче:

**Криптовалюта:**

- BTC: `bc1qunld3rsp37qf5gg69aune50y0qqkd0eugg7j97`
- TON: `UQDmvr4SKOxSION3Yky6aOgzAnCDXySPuAbG4EKJa5JUT7tC`
- USDT (TRC20): `TBPJSSLu1mUcX54g9UyxUohYGf2fuRvbwd`
- USDT (ERC20): `0x25CAED3776Ef5b18E03392bC5b254Bbd78E8180C`
- USDT (SOL): `3qgN5z291CEcj2FUi2Zza5DioxKgNw72kC7P52pCcTrG`

## Ліцензія

MIT
