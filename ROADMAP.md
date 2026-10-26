# ROADMAP — HoYo Code Monitor

Конкретные улучшения по кодовой базе. Формат: `file:line` — проблема → что сделать.
Приоритеты: 🔴 высокий (влияет на пользователей/надежность), 🟡 средний, 💭 низкий/косметика.

## Фичи / UX

- 🔴 `src/cli.py:571-574` — `run-once` не выполняет redeem («Redemption enabled but not implemented in run-once»). Подключить redeem-цикл в `run-once`, когда redemption включён.
- 🔴 `templates/recent_codes.html:23` — кнопка «Redeem all» без `hx-confirm`; случайный клик. Добавить `hx-confirm` (по образцу cleanup-кнопки).
- 🟡 `src/web_ui.py:53` — `_test_rate_limit` накапливает ключи без очистки (утечка на долгих ран). Прочийть старые записи по TTL.
- 🟡 `src/web_ui.py:138-143` — `_prime_update_cache` fire-and-forget: ошибки проверки обновлений теряются молча. Логировать warning в failure-путь.
- 🟡 `templates/dashboard.html:33,53` — scheduler/stats partials режутся каждые 5/10s даже когда scheduler остановлен. Делать polling условным по статусу.
- 🟡 `templates/accounts.html:26` — Auto-login кнопка не блокируется при работающем scheduler/tray; конфликт. Disabled-state при активной сессии.
- 💭 `templates/dashboard.html:8` — метка `stats.failed` отображается как «pending» (мизлидинг).
- 💭 Новые языки (es/pt/it) в `src/i18n.py` — опционально.

## Техдолг

- 🔴 `src/scheduler.py:389-582` — `_run_check_cycle` ~200 строк, делает fetch + storage + redeem + notify. Декомпозировать (fetch-фаза / redeem-фаза / notify-фаза).
- 🔴 `src/scheduler.py:395,555` — gap редема хардкодится в двух местах. Оставить только `Settings.redemption_min_gap_seconds`.
- 🟡 `src/storage.py:364-407` — `list_codes` с 4+ условиями. Вынести сборку запроса в helper (WHERE-фрагменты).
- 🟡 `src/storage.py:484-495` — `cleanup_dead_codes` тянет все коды (limit 5000) и фильтрует в Python. Перенести фильтр в SQL.
- 🟡 `src/checkin.py:366-403` — `_call_with_retry`: `max_retries + 1` итераций + `if attempt >= max_retries: break` — off-by-one в чтении. Переписать через `for attempt in range(max_retries)` + последнюю попытку явно.
- 🟡 `src/redeemer.py:176-233` — `_parse_response` с 5+ вариациями форм rewards. Разбить на маленькие парсеры per-shape.

## Надёжность

- 🔴 `src/single_instance.py:56-73` — stale lock: при краше предыдущего экземпляра лок-файл не чистится, новый старт говорит «уже запущен». Детект PID-смерти + автоочистка.
- 🟡 `src/sources.py:392-401` — экспоненциальный backoff без jitter → thundering herd. Добавить random jitter.
- 🟡 `src/cookies_login.py:159-164` — polling цикл с `time.time()` без `await asyncio.sleep(0)`; может голодовать event loop. `asyncio.sleep(0)` на итерацию.
- 🟡 `src/cookies_login.py:99-118` — `SKIP_PREFIXES`/`SKIP_EXACT` захардкожены; новые трекинг-куки HoYoLAB проскакивают. Вынести в config.
- 💭 `src/http_session.py:62-142` — cross-loop `close_all` на debug-логировании; сессии могут оставаться открытыми. Усилить логирование.

## i18n

- 🟡 `templates/sparkline.html:3` — «Codes per day · 14 days» хардкод, мимо `t()`.
- 🟡 `templates/partials/stats.html:2` и `scheduler_status.html:2` — заголовки мимо `t()`.
- 💭 `templates/partials/recent_logs.html:8` — `error_message` логируется raw; экранировать/обрезать перед выводом.

## CI / Release

- 🔴 `.github/workflows/ci-cd.yml:76` — NSIS-инсталятор строится без smoke-теста (запустить exe, проверить health). Добавить step.
- 🟡 `ci-cd.yml:68` — `pip install pyinstaller nsis` на каждый билд; кэш.
- 🟡 `ci-cd.yml:87-100` — assets грузятся только на `release` event; автоматический draft-release на main-тег не работает.
- 🟡 `Dockerfile:25-30` — системный chromium + Playwright-хром → расхождение версий. Fix: только Playwright.
- 💭 `genshin-code-monitor.spec` — 70+ hiddenimports; прогнать анализ, убрать лишнее (уменьшить exe).

## Hygiene

- 🟡 Корень репо: 10+ старых `*-setup.exe` артефактов. Оставить только актуальный (или удалить все — релизы живут на GitHub).
- 💭 Нет `CODEOWNERS`, нет `CONTRIBUTING.md`.
- 💭 README × 6 языков — риск рассинхронизации при изменениях в EN.
