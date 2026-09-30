# HoYo Code Monitor — заметка о программе, референсы и план авто-чек-ина

> Статус: исследование, реализации нет. Ждёт подтверждения пользователя.
> Обновлено: 2026-09-24. Ветка: `design-experiment`.

## 1. О чём эта программа

**HoYo Code Monitor** — локальное Windows-приложение (трей + веб-UI на `127.0.0.1:8000`),
которое автоматизирует рутину вокруг HoYoverse-игр:

1. **Мониторинг промокодов** — периодический опрос настраиваемых источников
   (URL + CSS/XPath-селекторы) через `Scheduler`, сохранение в локальный SQLite.
2. **Автопогашение кодов** — `Redeemer` гасит коды через официальный API,
   используя сохранённые куки аккаунтов (шифр Fernet, захват кук через Playwright).
3. **Веб-UI управления** — FastAPI + HTMX + Jinja, 6 языков, per-account тумблеры,
   страницы дашборда/источников/аккаунтов/настроек/автора.
4. **Только локально**: SQLite, `%LOCALAPPDATA%\HoYoCodeMonitor` во frozen-режиме,
   ноль телеметрии. Сборка: PyInstaller onedir + NSIS-инсталлер. Версия: `1.0.0-beta.3`.

Ключевые модули: `src/scheduler.py`, `src/redeemer.py`, `src/cookies_login.py`,
`src/storage.py`, `src/sources.py`, `src/web_ui.py`, `src/constants.py`
(`GAMES`, `GAME_CONF`), `src/config.py`, `src/i18n.py`.

**Новая задача (этот документ):** добавить второй пайплайн — **ежедневный авто-чек-ин
(HoYoLAB daily sign-in)** теми же куками: `info → sign → home`, по всем аккаунтам
и играм, раз в сутки + ручной запуск + история в БД.

---

## 2. Референсы с GitHub

### 2.1. Таблица сравнения

| Проект | Звёзды | Лицензия | Статус (сен. 2026) | Что решает | Роль для нас |
|---|---|---|---|---|---|
| `seriaati/genshin.py` | ~477 | MIT | Активен, релиз каждый месяц (1.7.30, 01.09.2026) | API-обёртка HoYoLAB/Miyoushe: чек-ин, редим кодов, дневники, витрины | **Главный референс**: DS-алгоритм, таблицы роутов, `x-rpc-signgame`, обработка реткодов |
| `Womsxd/MihoyoBBSTools` | ~1.4k | MIT | Активен (PR май 2026) | Авто-чек-ин игр + миссии форума, уведомления | Референс пайплайна `info→sign→home`, идемпотентности, CN/OS-ветвлений |
| `PaiGramTeam/SIMNet` | ~24 | MIT | Активен (авг 2026), маленький | Форк genshin.py под Telegram-ботов | Запасной источник роутов; архитектура не интересна |
| `seriaati/hoyo-codes` | ~44 | — | Активен | API-выдача актуальных гифт-кодов | Кандидат в **источник кодов** для нашего мониторинга |
| `LmeSzinc/StarRailCopilot` (`dev_tools/exchange_code/`) | — | GPL-3.0 | Активен | Парсинг кодов из постов/стримов HoYoLAB | Референс извлечения кодов из HoYoLAB-постов |
| `Ljzd-PRO/nonebot-plugin-mystool` | — | MIT | Активен | NoneBot-плагин: чек-ины, магазин, миссии | Только сигнатуры API (CN), архитектуру бота не брать |

### 2.2. `seriaati/genshin.py` — главный референс

- **Задачи**: полный клиент HoYoLAB: daily check-in (`client/components/daily.py`),
  redeem кодов, battle chronicle, ledger, enka-интеграция.
- **Архитектура**: `Client` + компоненты (`components/daily.py`, `redemption.py`),
  роуты вынесены в `client/routes.py` (`GameRoute`/`InternationalRoute`: OS vs CN),
  модели на **pydantic v2**, ретраи через **tenacity**, транспорт **aiohttp**, всё async.
- **Технологии**: Python 3.9+, aiohttp, pydantic v2, tenacity; тесты, mkdocs, ruff,
  monthly-релизы, `pip install genshin`.
- **Поддержка**: да, ежемесячно; автор также ведёт `hoyo-buddy`, `hoyo-codes`, `enka-py`.
- **Повторить**: таблицу `REWARD_URL` (base URL + act_id на игру), маппинг
  `x-rpc-signgame` (`hk4e/hkrpg/zzz/nxx/bh3`), `DS`-генератор (`utility/ds.py`),
  трактовку `-5003` как «уже забрано», разделение OS/CN роутов.
- **Избегать**: зависимости целиком — тянет aiohttp+pydantic v2+tenacity и чужой
  релизный цикл; при смене API со стороны HoYoverse чинить придётся ожиданием
  апстрима. Нам нужен только check-in Slice → свой минимальный клиент.

### 2.3. `Womsxd/MihoyoBBSTools` — референс пайплайна

- **Задачи**: ежедневный чек-ин всех игр + форумные миссии, конфиг-файл, пуш-уведомления.
- **Архитектура**: плоские скрипты (`hoyo_checkin.py`, `gamecheckin.py`,
  `setting.py` с act_id), запуск по cron/планировщику, мультиаккаунтность через конфиг.
- **Технологии**: Python, `requests` (синхронный), без UI.
- **Поддержка**: да, живой проект, CN-фокус, но `hoyo_checkin.py` покрывает и OS-игры.
- **Повторить**: порядок `info → sign → home`, проверку `is_sign`/`first_bind`
  до попытки claim, текстовые статусы для логов, отдельные act_id в настройках
  (а не в коде) — у нас это `GAME_CHECKIN_CONF`.
- **Избегать**: синхронный `requests` в цикле (у нас async-стек), хранение кук
  в открытом `config.json` (у нас Fernet — keep), отсутствие идемпотентности
  на уровне БД.

### 2.4. Остальные

- **SIMNet** — брать только как зеркало роутов, если `genshin.py` недоступен.
  Звёзд мало, экосистема заточена под Telegram-ботов (AGPL-компоненты рядом) —
  нам не подходит.
- **hoyo-codes** — рассмотреть как готовый источник кодов: вместо парсинга
  сторонних сайтов опрашивать их API. Проверить лицензию/лимиты перед включением.
- **StarRailCopilot/exchange_code** — идеи извлечения кодов из `getPostFull`
  и стримов (`miyolive/index`); лицензия GPL-3.0 — только идеи, не код.
- **nonebot-plugin-mystool** — только CN-сигнатуры (`api-takumi`, mobile-заголовки);
  архитектуру чат-бота игнорировать.

### 2.5. Специфические находки для разработки («скиллы» с GitHub)

1. **DS-подпись** — `genshin.py: genshin/utility/ds.py`:
   `md5("salt={s}&t={t}&r={r}&b={body}&q={query}")`, salt OS публичен в коде lib.
2. **Таблица act_id/OS-URL** — `genshin.py: client/routes.py → REWARD_URL`.
3. **Поток кук login_ticket → stoken → cookie_token/ltoken** —
   `Ljzd-PRO` URL-константы (у нас уже закрыто через Playwright `capture_cookies`).
4. **Коды из HoYoLAB-постов** — `StarRailCopilot: getPostFull?post_id=` + regex кодов.
5. **Готовые коды API** — `seriaati/hoyo-codes` как источник для `sources.py`.

---

## 3. Предлагаемый стек и архитектура

Стек **не меняем** (локальный ПК, всё уже есть): Python 3.11, FastAPI + HTMX + Jinja,
aiohttp (уже в зависимостях), SQLite, Playwright (куки), PyInstaller + NSIS.
Новых тяжёлых зависимостей — ноль; `genshin.py` используем как **референс кода**,
не как зависимость.

Архитектура — **второй пайплайн внутри текущего процесса** (вариант 1 из прошлого
обсуждения): новый модуль `src/checkin.py` (`GAME_CHECKIN_CONF` + `CheckinRunner`
по образцу `SourceFetcher`/`Redeemer`), отдельная таблица `checkin_log`,
отдельный триггер в `Scheduler` (`checkin_time`, дефолт 04:00 + джиттер ±15 мин),
страница `/checkins` + partial логов, per-account тумблер `auto_checkin_enabled`
зеркалом существующего redeem-тумблера.

Почему не отдельный воркер: локальный ПК, один пользователь, SQLite без сервера —
второй процесс добавит только синхронизацию БД и второй пункт в автозагрузку
без выгоды. Выделить воркер можно позже без переписывания `CheckinRunner`.

---

## 4. Границы MVP

**Входит:** overseas-аккаунты; Genshin + HSR; ежедневный авторапуск + кнопка
«Забрать сейчас»; `checkin_log` + страница истории; тумблер на аккаунт;
тесты с моками HTTP; README EN/RU; CHANGELOG.
**Не входит:** CN-регион, ZZZ/HI3/ToT (волна 2 — добавлением строк в конфиг),
уведомления, зависимость `genshin.py`, export/import чек-инов, остальные 4 языка README.

## 5. Последовательность разработки

1. `src/checkin.py`: конфиг-таблица, DS, `CheckinRunner` (HTTP-клиент инъекцируется для моков).
2. `src/storage.py`: миграция `checkin_log` + `UNIQUE(account_id, game, claimed_date)`, методы лога и тумблера.
3. `tests/test_checkin.py` (TDD): success / already_claimed / cookie_expired / rate_limit / идемпотентность.
4. `src/scheduler.py`: `run_daily_checkins()`, конфиг `checkin_enabled/checkin_time/checkin_jitter_minutes`, поля `last_checkin_*` в статус.
5. `src/web_ui.py` + `templates/checkins.html` + `partials/checkin_logs.html`: страница, тумблер, ручной запуск.
6. Проверка TestClient (200 на странице/API/статике) + 1 живой прогон на тестовом аккаунте.
7. CHANGELOG + README EN/RU.
8. Волна 2 (после 3–5 дней стабильности): ZZZ → HI3 → ToT.

## 6. Оценка текущего кода под план

**Ложится хорошо:** паттерны `SourceConfig→SourceFetcher` и `Redeemer` — прямой
образец для `CheckinRunner`; redeem-тумблер — образец для checkin-тумблера;
`run_once()` — образец для `run_daily_checkins()`; TestClient-проверка отработана.

**Поменять/учесть до старта:**
1. В `redeem_single_code`/`redeem_all_codes` задвоен вызов `update_code_redemption` —
   не копировать дефект в чек-ин (один вызов).
2. `api_sources_status` парсит даты без try — в чек-ин-статусах парсить defensive.
3. DS-соль и act_id — в константы с комментарием-источником (`genshin.py`, MIT),
   чинить в одном месте при смене API.
4. `Scheduler.status` один на два пайплайна — добавить `last_checkin_*`, иначе UI врёт.
5. Куки: проверить, что сохранённый набор содержит `ltoken/ltuid/cookie_token`
   (нужны чек-ину); если нет — расширить `capture_cookies`.

---

**Требуется подтверждение:** MVP Genshin + HSR, внутри процесса, свой клиент.
После «да» — начну с п.1 (`src/checkin.py` + тесты).
