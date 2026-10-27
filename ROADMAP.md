# ROADMAP — HoYo Code Monitor

Конкретные улучшения по кодовой базе. Формат: `file:line` — проблема → что сделать.
Приоритеты: 🔴 высокий (влияет на пользователей/надежность), 🟡 средний, 💭 низкий/косметика.
Отметки: ✅ сделано (см. git log), ⚠️ переосмыслено (не сделано, обоснование ниже).

## Фичи / UX

- ✅ `src/cli.py:571-574` — `run-once` не выполнял redeem. Подключён redeem-цикл (коммит 488163a + ee0f2b6).
- ✅ `templates/recent_codes.html:23` — кнопка «Redeem all» без `hx-confirm`. Добавлен (коммит f0c7af6).
- ✅ `src/web_ui.py:53` — `_test_rate_limit` накапливал ключи без очистки. In-place TTL-prune (коммит d531b64; баг с global-rebind починен в ee0f2b6).
- ✅ `src/web_ui.py:138-143` — `_prime_update_cache`: ошибки терялись молча. Теперь `logger.warning` (коммит d531b64).
- 🟡 `templates/dashboard.html:33,53` — scheduler/stats partials режутся каждые 5/10s даже когда scheduler остановлен. Делать polling условным по статусу.
- ✅ `templates/accounts.html:26` — Auto-login кнопка не блокировалась при работающем scheduler. Disabled-state добавлен (коммит c35085a).
- ✅ `templates/dashboard.html:8` — метка `stats.failed` отображалась как «pending». Теперь `t('stats_failed')` (коммит c35085a).
- 💭 Новые языки (es/pt/it) в `src/i18n.py` — опционально.

## Техдолг

- ✅ `src/scheduler.py:389-582` — `_run_check_cycle` ~200 строк. Вынесен helper `_redeem_new_codes` (коммит 488163a); полная декомпозиция fetch/redeem/notify фаз осталась open.
- ⚠️ `src/scheduler.py:395,555` — gap: run-once в cli.py теперь читает `redemption_min_gap_seconds` из config (коммит ee0f2b6). Само `scheduler._run_check_cycle` gap-объект не содержит — пункт ROADMAP был неточным.
- ⚠️ `src/storage.py:364-407` — `list_codes` с 4+ условиями. НЕ выносить в helper: 4 фильтра каждый уникальный (по правилу трёх похожих строк < 4 повторений абстракция преждевременна).
- ✅ `src/storage.py:484-495` — `cleanup_dead_codes` делали N отдельных `delete_code` (N транзакций). Заменено на единый batch-DELETE через `delete_codes_by_id` (коммит ef250bf).
- ⚠️ `src/checkin.py:366-403` — `_call_with_retry` НЕ имеет off-by-one: `range(max_retries+1)` + `if attempt >= max_retries: break` корректно дают `max_retries+1` попыток (1 initial + N retries). ROADMAP ошибался.
- ⚠️ `src/redeemer.py:176-233` — `_parse_response` разбивка per-shape — premature: функция 57 строк с двумя ветками (dict/list), читабелен. Не трогать.

## Надёжность

- ✅ `src/single_instance.py:56-73` — stale lock: PID-детект + автоочистка реализован (коммит 6dc58be).
- ✅ `src/sources.py:392-401` — экспоненциальный backoff без jitter. Jitter добавлен (коммит 6dc58be).
- ✅ `src/cookies_login.py:159-164` — polling цикл без yield к event loop. Добавлен `await asyncio.sleep` (коммит 6dc58be).
- 🟡 `src/cookies_login.py:99-118` — `SKIP_PREFIXES`/`SKIP_EXACT` захардкожены; новые трекинг-куки HoYoLAB проскакивают. Вынести в config.
- ⚠️ `src/http_session.py:62-142` — cross-loop `close_all` УЖЕ корректно: `call_soon_threadsafe` + `_close_on_owner` (стр. 129-143) закрывает сессии на чужом loop. ROADMAP переусложнял. Не трогать.

## i18n

- ✅ `templates/sparkline.html:3` — «Codes per day · 14 days» теперь через `t('codes_per_day')` (коммит ad3429a).
- ✅ `templates/partials/stats.html:2` и `scheduler_status.html:2` — заголовки через `t()` (коммит ad3429a).
- ✅ `templates/partials/recent_logs.html:8` — `error_message` обрезается до 300 символов + ellipsis в `Storage.add_redemption_log` (коммит ad3429a).

## CI / Release

- ✅ `.github/workflows/ci-cd.yml:76` — NSIS-инсталятор: smoke-test step добавлен (коммит 4f8502f).
- 🟡 `ci-cd.yml:68` — `pip install pyinstaller nsis` на каждый билд; кэш.
- 🟡 `ci-cd.yml:87-100` — assets грузятся только на `release` event; автоматический draft-release на main-тег не работает.
- ✅ `Dockerfile:25-30` — системный chromium + Playwright-хром. Убран системный chromium, `PLAYWRIGHT_BROWSERS_PATH` (он указывал на файл, а не директорию — сломан), добавлен `playwright install chromium` на build (коммит ef250bf). ⚠️ Билд Docker не верифицирован в этой среде.
- ✅ `genshin-code-monitor.spec` — 70+ hiddenimports: приведено к минимальному набору (только то, что PyInstaller не вытягивает сам). Верифицировано чистым PyInstaller-билдом + `--help` smoke (коммит ef250bf).

## Hygiene

- ✅ Корень репо: 10+ старых `*-setup.exe`. Удалены (коммит ef250bf; `.gitignore` уже покрывает `*.exe`/`dist`/`build`).
- 💭 Нет `CODEOWNERS`, нет `CONTRIBUTING.md`.
- 💭 README × 6 языков — риск рассинхронизации при изменениях в EN.

