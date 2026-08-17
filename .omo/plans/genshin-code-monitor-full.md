# genshin-code-monitor-full - Work Plan

## TL;DR (For humans)
Перестроить текущий каркас в полноценное локальное Windows-приложение: пользователь один раз вручную входит в официальный HoYoLAB через видимое окно браузера, после чего отдельный worker-процесс постоянно проверяет публичные источники, активирует новые коды на выбранный игровой аккаунт и сохраняет историю кодов, попыток, наград и ошибок.

**Почему этот подход:** пароль и CAPTCHA не проходят через приложение; браузер нужен только для ручной авторизации, HTTP-клиенты — для чтения публичных источников и активации. Windows Credential Manager защищает ключ сессии, SQLite хранит зашифрованную сессию и операционные данные, а отдельный worker решает проблему текущего daemon-потока, который умирает после выхода CLI.

**Что это НЕ будет делать:** не будет собирать пароли, обходить 2FA/CAPTCHA, перехватывать весь сетевой трафик, читать приватные форумы или отправлять телеметрию. Мониторинг сети трактуется как периодический HTTP-опрос разрешённых публичных источников.

**Effort:** Large
**Risk:** High — завязка на изменяемые HoYoLAB-сессии/API, сторонние сайты и Windows lifecycle; риск снижается ручной авторизацией, fail-closed режимом и контрактными тестами.
**Decisions to sanity-check:** браузерный ручной login вместо cookie paste/парольного login; Windows Credential Manager; отдельный worker + optional Task Scheduler autostart; только публичные источники; один выбранный аккаунт при схеме, допускающей несколько.

Your next move: запустить отдельную worker-сессию исполнения плана; этот документ сам код не меняет.

---

## TL;DR (machine): Large | High | Secure browser login + encrypted session + persistent Windows worker + public-source redemption history

## Scope
### Must have
- `auth login`: открыть официальную страницу HoYoLAB в headed Chromium; пользователь сам вводит данные и проходит 2FA/CAPTCHA; пароль никогда не передаётся Python-коду и не сохраняется.
- Извлечь authenticated browser storage state после ручного входа, зашифровать его, сохранить локально и получить UID/region/game_biz через endpoint `getUserGameRolesByCookie` с обработкой global/CN host map.
- `auth status`, `auth logout`, повторная авторизация при истечении/отозванной сессии; logout удаляет локальную сессию, но не историю кодов без отдельного destructive-флага.
- Хранить ключ шифрования через Windows Credential Manager (`keyring`), ciphertext — в SQLite; не записывать cookies/session state в TOML, лог или plaintext-файл.
- Разделить CLI и долгоживущий worker-процесс; реализовать single-instance lock, PID identity, heartbeat, stop request, stale-state recovery, graceful stop и forced-stop fallback.
- Публичные источники: существующий Genshin Wiki MediaWiki adapter, официальный/public HoYoLAB/Genshin announcement adapter, Reddit/public forum JSON adapter и configurable generic public HTML adapter.
- Нормализовать коды, валидировать кандидатов, связывать код с несколькими источниками, хранить наблюдения, описание награды/срок действия/URL источника.
- Для каждого выбранного аккаунта выполнять idempotent redemption: один логический код не активируется повторно без явной retry-команды; network errors retryable, permanent invalid/expired/already-used responses не повторяются автоматически.
- Выдерживать provider-safe gap между попытками (default 8 секунд, configurable lower bound 6 секунд), exponential backoff для временных ошибок и общий rate limit.
- Хранить `redemption_attempts` с результатом, retcode, сообщением, reward, временем, retryable-флагом и безопасным response hash без cookies.
- CLI: `auth`, `worker`, `sources`, `codes`, `stats`, `config`, `run-once`, `autostart`; все команды работают с одним источником конфигурации и общим состоянием.
- Операционные настройки в `config.toml`, состояние/история/зашифрованная сессия в SQLite, секретный ключ только в Windows Credential Manager.
- Unit, integration, process-lifecycle, security-redaction и end-to-end tests с mock HTTP/browser; реальный аккаунт не используется в CI.
- `autostart install/status/uninstall` через Windows Task Scheduler для запуска worker в интерактивной сессии текущего пользователя при logon; установка требует явного вызова пользователем.
- README с безопасным login walkthrough, восстановлением сессии, ограничениями источников, командами worker и диагностикой.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- Автоматический ввод username/password, перехват пароля, CAPTCHA/2FA bypass или credential guessing.
- Cookie paste как основной UX; допускается только диагностическая import-команда с явным предупреждением, если она будет добавлена отдельным решением.
- Packet sniffing, proxy interception или чтение произвольного сетевого трафика пользователя.
- Private/authenticated forum scraping, Discord scraping, обход robots/rate limits и источник, требующий отдельной авторизации вне HoYoLAB login flow.
- Plaintext cookies/session state в `config.toml`, SQLite, log, crash dump, test fixture или постоянном browser profile.
- Реальный пароль, cookie value или полный redemption payload в логах, telemetry, exception message или test output.
- Внешний сервер, облачная БД, remote dashboard, telemetry, analytics или публикация найденных кодов.
- Бесконечные retries, параллельная массовая активация и обход provider cooldown.
- Автоматическое удаление истории при logout/migration; destructive purge только отдельной командой с подтверждением.
- Сохранение сломанного `start`/`stop` поведения ради backward compatibility; внутренние CLI-контракты можно заменить целиком.

## Verification strategy
> Zero human intervention for automated checks; real-account login remains an explicitly manual smoke boundary and must never be reported as automated PASS.
- Test decision: TDD/tests-after hybrid + `pytest`, `pytest-asyncio`, `aioresponses`, `pytest` subprocess fixtures.
- Python commands use `F:\SDProject\GIPromoCode\.venv\Scripts\python.exe`; bootstrap creates this venv before tests if absent.
- Required checks: `F:\SDProject\GIPromoCode\.venv\Scripts\python.exe -m pytest tests -q`, `... -m ruff check src tests`, `... -m mypy src`.
- Browser test dependency: `... -m playwright install chromium`; auth tests use a fake headed-login boundary and never real credentials.
- Evidence: `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-<N>-genshin-code-monitor-full.<ext>`; JUnit XML for tests, JSON for worker status, TXT for CLI smoke.
- Every todo contains a happy and failure QA scenario. No criterion may depend on “looks correct”, a subagent report, or an unexecuted command.

## Execution strategy
### Parallel execution waves
> One worker session performs implementation; no delegated agents/subagents. Independent files can be worked in parallel conceptually, but changes are applied in dependency order and verified after each wave.

- **Wave 1 — contracts and secure foundations:** todos 1-6 and 9.
- **Wave 2 — integrations and runtime:** todos 7, 8, 10, 11.
- **Wave 3 — pipeline, commands, and contract tests:** todos 12-14 and 16.
- **Wave 4 — data transition, lifecycle QA, packaging, documentation:** todos 15 and 17-19.
- **Final verification wave:** F1-F4 only after all todos.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. Toolchain and canonical settings | None | 2,3,5,9,11 | 2,5 |
| 2. Domain contracts | 1 | 3,4,6,8,9,10,12 | 5 |
| 3. Database schema and migrations | 1,2 | 4,11,15 | 5,6,9 |
| 4. Repositories and statistics | 3 | 6,11,12,14,15 | 5,9,10 |
| 5. Secret/session store | 1,2 | 6,7,8,13 | 3,9 |
| 6. Account resolver | 2,4,5 | 7,8,13 | 9,10 |
| 7. Browser-assisted login | 5,6 | 13,16 | 8,9,10 |
| 8. HoYoLAB redeem client | 2,5,6 | 12,16 | 7,9,10 |
| 9. Source contract and Wiki adapter | 1,2 | 10,12,16 | 3,5,6,8 |
| 10. Official/Reddit/generic adapters | 9 | 12,16 | 7,8,11 |
| 11. Worker process/control plane | 1,3,4 | 12,13,14,17 | 7,8,9,10 |
| 12. Polling/redemption pipeline | 4,8,9,10,11 | 13,14,15,17 | 7 |
| 13. Auth/config CLI | 5,6,7,11,12 | 14,16,17 | 10 |
| 14. Worker/source/history CLI | 4,11,12,13 | 15,17,18 | 16 |
| 15. Existing DB migration and cleanup | 3,4,12,14 | 17,18 | 16 |
| 16. Module and contract tests | 2,5,6,7,8,9,10 | 17 | 13,14,15 |
| 17. Lifecycle/E2E/security tests | 11,12,13,14,15,16 | 18,19 | 18 |
| 18. Packaging and Task Scheduler autostart | 11,13,17 | 19 | 17 |
| 19. README and operational runbook | 13,14,15,17,18 | Final wave | None |

## Todos
> Implementation + Test = ONE todo. Never separate.

- [ ] 1. Establish Windows Python toolchain and canonical operational settings
  What to do / Must NOT do: Create `pyproject.toml` with Python 3.11+, runtime/dev dependencies (`aiohttp`, `beautifulsoup4`, `click`, `cryptography`, `keyring`, `playwright`, `psutil`, `portalocker`, `pytest`, `pytest-asyncio`, `aioresponses`, `ruff`, `mypy`), console entry point, and strict lint/type settings. Rewrite `src/config.py` around one `Settings` model: `db_path`, `log_file`, `poll_interval_seconds=900`, `source_timeout_seconds=30`, `redemption_enabled=false`, `redemption_min_gap_seconds=8`, `max_retry_attempts=3`, `retry_backoff_seconds=[30,120,600]`, `heartbeat_seconds=5`, `heartbeat_timeout_seconds=30`; secrets and account session never belong in settings. Keep no conflicting seconds/minutes semantics.
  Parallelization: Wave 1 | Blocked by: None | Blocks: 2,3,5,9,11
  References (executor has NO interview context - be exhaustive): `src/config.py:18-195`, `src/config.py:228-418`, `config.toml:1-7`, `requirements.txt`, Python `tomllib`; existing tests `tests/test_config.py`; project Windows path `F:\SDProject\GIPromoCode`.
  Acceptance criteria (agent-executable): `F:\SDProject\GIPromoCode\.venv\Scripts\python.exe -m pytest tests/test_config.py -q` passes with tests proving settings round-trip, type validation, seconds units, and no auth fields; `... -m ruff check src tests` reports zero errors.
  QA scenarios: Happy — load missing config, assert defaults and persist/reload same values. Failure — invalid interval/boolean/unknown key is rejected without changing file. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-1-genshin-code-monitor-full.xml`.
  Commit: Y | chore(tooling): establish canonical Windows settings and project metadata

- [ ] 2. Define typed domain contracts for accounts, codes, sources, attempts, and worker status
  What to do / Must NOT do: Add `src/domain/models.py` with typed dataclasses/enums for `AccountProfile`, `AuthState`, `PromoCodeCandidate`, `CodeObservation`, `RedemptionAttempt`, `WorkerState`, `SourceHealth`, and explicit status/retry enums. Normalize code representation once at the domain boundary. Reject empty/oversized/malformed candidates. Do not put HTTP, SQLite, Playwright, or Click logic in domain models.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3,4,6,8,9,10,12
  References: `src/redeemer.py:15-29`, `src/scheduler.py:23-43`, `src/storage.py:35-57`; Python `dataclasses`; existing test naming conventions in `tests/test_redeemer.py` and `tests/test_storage.py`.
  Acceptance criteria: `... -m pytest tests/test_domain_models.py -q` covers valid normalization, duplicate-equivalent codes, invalid input, retry classification, and worker state transitions; mypy accepts public model signatures.
  QA scenarios: Happy — candidates `abc-123`, `ABC123` normalize according to the documented rule and preserve source metadata. Failure — blank, whitespace-only, too-long, or punctuation-heavy candidate is rejected and never reaches storage. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-2-genshin-code-monitor-full.xml`.
  Commit: Y | feat(domain): define typed code and worker contracts

- [ ] 3. Replace the flat SQLite schema with versioned migrations
  What to do / Must NOT do: Replace `src/storage.py` with `src/persistence/database.py` and `src/persistence/migrations.py`. Create versioned tables: `schema_meta`, `accounts`, `auth_sessions`, `sources`, `promo_codes`, `code_observations`, `redemption_attempts`, `worker_state`. Store encrypted session ciphertext only, never raw cookies. Add foreign keys, unique normalized code, unique `(code_id, source_id)` observation constraint, attempt indexes, timestamps in UTC ISO/SQLite-compatible form, and transaction helpers. Migration must back up existing `data/monitor.db` before altering it and must not drop old history silently.
  Parallelization: Wave 1 | Blocked by: 1,2 | Blocks: 4,11,15
  References: `src/storage.py:31-59`, `src/storage.py:75-185`, `src/storage.py:187-320`, `src/storage.py:322-379`; SQLite docs `https://docs.python.org/3/library/sqlite3.html`.
  Acceptance criteria: `... -m pytest tests/test_persistence_migrations.py -q` creates a fresh schema, verifies constraints/indexes, migrates a fixture of the current `codes/sources/config` schema, and preserves rows; failed migration rolls back and leaves backup available.
  QA scenarios: Happy — migrate old fixture and assert code/source history remains queryable. Failure — corrupt/unsupported schema version stops with a safe error and does not partially rewrite the DB. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-3-genshin-code-monitor-full.xml`.
  Commit: Y | refactor(storage): add versioned persistence schema and migrations

- [ ] 4. Implement repositories and aggregate statistics over the new schema
  What to do / Must NOT do: Add `src/persistence/repositories.py` and `src/persistence/stats.py` with account/session/source/code/observation/attempt/worker repositories. Implement idempotent `upsert_code`, `record_observation`, `claim_code_for_redemption`, `record_attempt`, `set_auth_state`, `set_worker_state`, and queries for pending/failed/expired codes. Statistics must report found codes, unique codes, per-source observations, success/failure/expired/already-used counts, rewards, and last activity. No SQL assembled from user-controlled values except whitelisted column names.
  Parallelization: Wave 1 | Blocked by: 3 | Blocks: 6,11,12,14,15
  References: `src/storage.py:110-185`, `src/storage.py:238-379`, `src/cli.py:200-212`; `src/domain/models.py` from todo 2.
  Acceptance criteria: `... -m pytest tests/test_persistence_repositories.py tests/test_statistics.py -q` proves idempotency, transaction rollback, account isolation, stats correctness, and no duplicate attempts for the same code/account unless explicit retry is requested.
  QA scenarios: Happy — two sources observe the same code and stats count one unique code plus two observations. Failure — concurrent claims allow only one redemption claim and a failed transaction leaves no partial attempt. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-4-genshin-code-monitor-full.xml`.
  Commit: Y | feat(storage): add repositories and redemption statistics

- [ ] 5. Implement Windows-protected session encryption and secret lifecycle
  What to do / Must NOT do: Add `src/auth/session_store.py` using Fernet ciphertext for browser storage state and `keyring` Windows Credential Manager for the per-install Fernet key. Store key under a fixed service name and account identifier; store only ciphertext in `auth_sessions`. Provide `save`, `load`, `delete`, `exists`, `validate_payload`, and key rotation. Redact cookies/token values from errors and logs. Use a clean error when keyring is unavailable; do not silently fall back to plaintext.
  Parallelization: Wave 1 | Blocked by: 1,2 | Blocks: 6,7,8,13
  References: `src/storage.py:381-438` (current insecure placeholder to replace); keyring docs `https://keyring.readthedocs.io/en/latest/`; Fernet docs `https://cryptography.io/en/latest/fernet/`; external research recommends Windows Credential Manager for local-only secrets.
  Acceptance criteria: `... -m pytest tests/test_session_store.py -q` uses a fake keyring and asserts ciphertext does not contain cookie values, round-trip works, wrong key/tampering fails, missing backend fails closed, and delete removes both encrypted state and key reference.
  QA scenarios: Happy — save storage state containing `ltoken_v2`, load it, and assert exact in-memory state. Failure — inspect raw SQLite and logs and assert neither contains token value; wrong key yields `AUTH_REQUIRED`, never an unhandled exception. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-5-genshin-code-monitor-full.xml`.
  Commit: Y | feat(auth): protect browser session with keyring and Fernet

- [ ] 6. Implement HoYoLAB account resolution and session validation
  What to do / Must NOT do: Add `src/auth/hoyolab_account.py` with regional endpoint map and async client for `getUserGameRolesByCookie`, using the browser session cookies only in memory. Resolve `hk4e_global`/`hk4e_cn` game roles, reject missing/ambiguous accounts unless user selects one, persist UID/region/game_biz/nickname metadata without cookies, and classify invalid/expired sessions as `AUTH_REQUIRED`. Include request headers and API response parsing as explicit integration contracts; do not invent UID from string heuristics.
  Parallelization: Wave 1 | Blocked by: 2,5 | Blocks: 7,8,13
  References: `src/config.py:363-391` current account loading; source-backed endpoint documentation `https://uigf.org/zh/mihoyo-api-collection/hoyolab/user/game_account_info.html`; current library example `https://github.com/leonismoe/genshin-stats/blob/main/packages/api/src/game-roles.ts`.
  Acceptance criteria: `... -m pytest tests/test_hoyolab_account.py -q` with `aioresponses` covers global/CN response fixtures, multiple roles, no role, invalid cookie, HTTP timeout, and selected account persistence; no cookie value appears in assertion output.
  QA scenarios: Happy — valid fixture returns selected Genshin account and region. Failure — retcode invalid or no Genshin role transitions auth state to `AUTH_REQUIRED` and prevents redemption. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-6-genshin-code-monitor-full.xml`.
  Commit: Y | feat(auth): resolve HoYoLAB game account and session validity

- [ ] 7. Implement headed browser-assisted one-time login and logout
  What to do / Must NOT do: Add `src/auth/browser_login.py` using Playwright Python. `auth login` launches Chromium headed on the official HoYoLAB login page, waits for user completion through a clear terminal prompt/status check, reads `browser_context.storage_state()` in memory, closes the temporary context, encrypts state through todo 5, resolves account through todo 6, and deletes temporary profile artifacts. Do not automate credentials, CAPTCHA, 2FA, or arbitrary page navigation. `auth logout` removes local session and selected account only after confirmation; retain history.
  Parallelization: Wave 2 | Blocked by: 5,6 | Blocks: 13,16
  References: `src/redeemer.py:203-236`; Playwright auth guide `https://playwright.dev/python/docs/auth`; BrowserContext storage state `https://playwright.dev/python/docs/api/class-browsercontext#browser-context-storage-state`; user-approved browser-assisted login decision in `.omo/drafts/genshin-code-monitor-full.md`.
  Acceptance criteria: `... -m pytest tests/test_browser_login.py -q` with a fake Playwright boundary verifies save/close/delete behavior, login timeout, cancellation, invalid session, multiple account selection, and no password argument reaches application code. `... -m src.cli auth --help` exposes login/status/logout.
  QA scenarios: Happy — fake authenticated context produces encrypted state and account metadata. Failure — user closes browser or validation fails; command returns nonzero/`AUTH_REQUIRED`, removes temporary profile, and leaves no plaintext state. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-7-genshin-code-monitor-full.xml`.
  Commit: Y | feat(auth): add manual HoYoLAB browser login flow

- [ ] 8. Refactor the HoYoLAB redemption client around stored session/account context
  What to do / Must NOT do: Update `src/redeemer.py` or move it to `src/integrations/hoyolab_redeemer.py` so it accepts `AccountProfile + in-memory session cookies`, supports global/CN endpoint map, sends required form fields, masks code in logs, parses retcode/message/reward, and returns explicit retry classification. Enforce one request at a time through the pipeline; do not make the redeemer responsible for scheduling or persistence.
  Parallelization: Wave 2 | Blocked by: 2,5,6 | Blocks: 12,16
  References: `src/redeemer.py:41-49`, `src/redeemer.py:130-159`, `src/redeemer.py:161-201`, `src/redeemer.py:203-304`; current endpoint `https://sg-hk4e-api.hoyolab.com/common/apicdkey/api/webExchangeCdkey`; maintained wrapper reference `https://github.com/vermaysha/hoyoapi/blob/2dcd0bc/src/routes/routes.ts`.
  Acceptance criteria: `... -m pytest tests/test_redeemer.py -q` covers success, invalid/expired/already-used, auth failure, timeout, rate-limit response, malformed JSON, global/CN endpoint selection, and exact form fields; every result is serializable without cookies.
  QA scenarios: Happy — mocked retcode 0 yields success and reward. Failure — timeout is retryable, retcode permanent failure is not retried automatically, and no request body/cookie is logged. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-8-genshin-code-monitor-full.xml`.
  Commit: Y | refactor(redeemer): bind redemption to validated account sessions

- [ ] 9. Define source adapter contract and repair the Wiki adapter
  What to do / Must NOT do: Refactor `src/scrapers/base.py` to return typed `PromoCodeCandidate`/`SourceFetchResult`, include source URL, observed timestamp, description, expiry hint, HTTP status and error classification. Keep HTTP public-source polling async. Repair `src/scrapers/wiki.py` to handle MediaWiki API response variants, multiple code cells, expired rows, conditional requests where available, and parser version. Do not use browser automation for public scraping.
  Parallelization: Wave 1 | Blocked by: 1,2 | Blocks: 10,12,16
  References: `src/scrapers/base.py:16-117`, `src/scrapers/wiki.py:19-206`, existing fixtures `wiki_api.json`, `wiki_html.html`, `tests/test_scraper_wiki.py`; BeautifulSoup docs `https://www.crummy.com/software/BeautifulSoup/bs4/doc/`.
  Acceptance criteria: `... -m pytest tests/test_scraper_wiki.py tests/test_source_contract.py -q` covers candidate normalization, parser fixtures, network timeout, API schema change, empty/expired tables, and source health result.
  QA scenarios: Happy — fixture returns only valid active codes with reward metadata. Failure — malformed API or timeout returns a classified source error and does not create codes. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-9-genshin-code-monitor-full.xml`.
  Commit: Y | refactor(scraper): standardize public source adapter contract

- [ ] 10. Add official/public announcement, Reddit, and generic public HTML adapters
  What to do / Must NOT do: Add `src/scrapers/official.py`, `src/scrapers/reddit.py`, `src/scrapers/generic.py`, and `src/scrapers/registry.py`. Official adapter uses a configured public HoYoLAB/Genshin announcement endpoint; Reddit adapter uses public JSON with a descriptive User-Agent and rate limit; generic adapter accepts explicit URL/parser selectors for public pages. Each adapter extracts evidence URL and description, validates candidates, uses conditional/cache headers when supported, and isolates parser failures. No private login or Discord adapter.
  Parallelization: Wave 2 | Blocked by: 9 | Blocks: 12,16
  References: source registry contract from todo 9; `src/scheduler.py:112-146` current generic fallback; `src/storage.py:238-257` current source records; public-source boundary in draft; Reddit public API/rate-limit documentation to be pinned in implementation notes.
  Acceptance criteria: `... -m pytest tests/test_scraper_official.py tests/test_scraper_reddit.py tests/test_scraper_generic.py -q` covers valid posts, duplicate posts, malformed JSON/HTML, HTTP 403/429, source-specific selectors, and public-only validation.
  QA scenarios: Happy — three fixtures yield normalized candidates with distinct source observations. Failure — 429 sets source backoff and no redemption occurs; a URL requiring authentication is rejected as unsupported. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-10-genshin-code-monitor-full.xml`.
  Commit: Y | feat(scraper): add official and public forum source adapters

- [ ] 11. Implement persistent worker process, lock, heartbeat, and control plane
  What to do / Must NOT do: Replace the in-process daemon-thread lifecycle in `src/scheduler.py` with `src/worker/runtime.py`, `src/worker/control.py`, and `src/worker/entrypoint.py`. `worker start` launches a separate Python process; worker owns one asyncio loop and runs immediately then at `poll_interval_seconds`; write runtime JSON with PID, process creation time, state, heartbeat, last/next cycle, and last error. Use `portalocker` single-instance lock, atomic state writes, `stop.request`, graceful wait timeout, and `psutil` terminate fallback. Validate PID identity before stale cleanup; never terminate an unrelated reused PID.
  Parallelization: Wave 2 | Blocked by: 1,3,4 | Blocks: 12,13,14,17
  References: `src/scheduler.py:262-347` current daemon-thread implementation; `src/cli.py:157-197` broken lifecycle; `src/signals.py`; `psutil` and `portalocker` APIs; runtime paths under `data/runtime/`.
  Acceptance criteria: `... -m pytest tests/test_worker_control.py tests/test_worker_runtime.py -q` proves start idempotency, live/stale PID detection, heartbeat timeout, graceful stop, forced-stop classification, lock release, and immediate first cycle.
  QA scenarios: Happy — start returns while worker remains alive after CLI exits; status reports heartbeat and next cycle; stop ends worker within configured timeout. Failure — stale state or dead PID is cleaned without killing another process; hung cycle results in forced stop and diagnostic state. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-11-genshin-code-monitor-full.json`.
  Commit: Y | feat(worker): add persistent Windows worker control plane

- [ ] 12. Implement idempotent polling, queueing, throttling, retry, and redemption pipeline
  What to do / Must NOT do: Add `src/worker/pipeline.py` and replace scheduler business logic with a cycle that loads enabled sources, records observations, upserts codes, selects pending codes, validates auth, waits the provider-safe gap, calls redeemer, records attempt/reward/error, and updates worker/source health. Use a single account by default, support selected profile schema, continue collecting while auth is unavailable, and mark queued codes for later redemption. Retry only classified transient failures with bounded exponential backoff. Protect against overlapping cycles and duplicate code claims.
  Parallelization: Wave 3 | Blocked by: 4,8,9,10,11 | Blocks: 13,14,15,17
  References: `src/scheduler.py:148-260` current partial pipeline; `src/redeemer.py:275-304`; `src/domain/models.py`; `src/persistence/repositories.py`; rate-limit evidence from maintained community implementations and explicit configured minimum 6-second provider gap.
  Acceptance criteria: `... -m pytest tests/test_pipeline.py -q` verifies new code → observation → one redemption attempt → reward persistence; auth missing queues without redeeming; permanent errors are terminal; transient errors retry within cap; duplicate sources produce one code claim.
  QA scenarios: Happy — mocked source finds a new code and mocked HoYoLAB returns reward; database has one code, observations, one success attempt, and stats increment. Failure — 429/timeout backs off, does not spin, and worker remains healthy; invalid session changes state to `AUTH_REQUIRED` without logging cookies. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-12-genshin-code-monitor-full.xml`.
  Commit: Y | feat(worker): add idempotent polling and redemption pipeline

- [ ] 13. Replace CLI with auth, worker, config, and autostart command groups
  What to do / Must NOT do: Rewrite `src/cli.py` around commands `auth login/status/logout`, `worker start/stop/status/run-once`, `sources list/add/remove/enable/disable`, `codes list`, `stats`, `config show/set`, and `autostart install/status/uninstall`. Use the same settings/repositories/control services as worker. Mask session/account secrets; return documented exit codes; `run-once` must call `asyncio.run`/worker runtime and use real async adapters. Remove unsupported calls (`remove_source`, `enable_source`, `disable_source`) or implement repository methods consistently.
  Parallelization: Wave 3 | Blocked by: 5,6,7,11,12 | Blocks: 14,16,17
  References: `src/cli.py:13-256` current CLI; `tests/test_cli.py:1-380` current mock-heavy tests; `src/config.py`; `src/persistence/repositories.py`; Click docs `https://click.palletsprojects.com/`.
  Acceptance criteria: `... -m pytest tests/test_cli.py -q` uses fake services and proves every command, exit code, masking, auth-required state, and worker cross-process control contract; `python -m src.cli --help` lists only implemented commands.
  QA scenarios: Happy — `auth status`, `worker start/status/stop`, `codes list`, `stats` work against temp DB/runtime. Failure — no auth returns actionable `AUTH_REQUIRED`, duplicate worker start exits nonzero, invalid config/source returns nonzero without stack trace or secret output. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-13-genshin-code-monitor-full.xml`.
  Commit: Y | refactor(cli): expose complete auth and worker lifecycle commands

- [ ] 14. Implement source/config/history/statistics command behavior
  What to do / Must NOT do: Complete repository-backed output for source health, last check/error, code status (`new/queued/redeemed/failed/expired`), reward details, attempt history, per-source success rates, and auth/worker diagnostics. Add pagination/filtering and safe timestamps. Ensure `config set` writes only canonical settings; source changes are transactional and do not silently delete observations.
  Parallelization: Wave 3 | Blocked by: 4,11,12,13 | Blocks: 15,17
  References: `src/cli.py:53-154`, `src/cli.py:200-212`, `src/storage.py:238-379`, new domain/repository contracts.
  Acceptance criteria: `... -m pytest tests/test_cli_history_stats.py -q` verifies output for empty, populated, failed, expired, and multi-source datasets; sensitive fields are masked and source updates persist across a new process.
  QA scenarios: Happy — stats show unique codes, attempts, reward quantities/descriptions, source counts, and last activity. Failure — missing source/account/history returns empty structured output, not a traceback; config cannot set secret keys. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-14-genshin-code-monitor-full.xml`.
  Commit: Y | feat(cli): add code history and operational statistics

- [ ] 15. Migrate current local data and remove contradictory scaffolding
  What to do / Must NOT do: Run the versioned migration against `data/monitor.db` with an automatic backup, migrate old `codes`, `sources`, and useful config values, then update imports from `src.storage` to persistence services. Remove insecure cookie placeholder methods, obsolete daemon-thread assumptions, duplicate/unsupported source operations, and README claims not backed by behavior. Do not delete old history or temporary fixtures without explicit scope; add `.gitignore` entries for `data/`, `logs/`, browser/session artifacts, caches, and secrets.
  Parallelization: Wave 4 | Blocked by: 3,4,12,14 | Blocks: 17,18
  References: `src/storage.py:31-59`, `src/storage.py:381-438`, `src/scheduler.py:262-347`, `src/cli.py:112-154`, `README.md:30-48`, `README.md:109-114`, `data/monitor.db`.
  Acceptance criteria: `... -m pytest tests/test_migration_existing_db.py -q` verifies backup, preservation, and new-schema queries; `... -m ruff check src tests` and `... -m mypy src` pass; grep confirms no plaintext cookie serializer and no old unsupported lifecycle imports.
  QA scenarios: Happy — copy fixture DB, migrate, and compare old code/source counts with new repository counts. Failure — migration interruption restores/retains backup and refuses to mark success; no user data is silently purged. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-15-genshin-code-monitor-full.json`.
  Commit: Y | refactor(data): migrate local history and remove insecure scaffolding

- [ ] 16. Add unit and contract test coverage for auth, sources, redeemer, and persistence
  What to do / Must NOT do: Replace tests that assume synchronous `scrape()` or mock `Storage` methods that do not exist. Add fixtures for browser storage state, keyring, account API global/CN responses, redemption retcodes, public source payloads, database migrations, and redaction. Keep all credentials synthetic and deterministic.
  Parallelization: Wave 3 | Blocked by: 2,5,6,7,8,9,10 | Blocks: 17
  References: `tests/test_cli.py:177-207` false-confidence run-once test; `tests/test_redeemer.py`; `tests/test_scraper_wiki.py`; `tests/test_storage.py`; `tests/test_logging.py`.
  Acceptance criteria: `... -m pytest tests/test_domain_models.py tests/test_session_store.py tests/test_hoyolab_account.py tests/test_redeemer.py tests/test_scrapers tests/test_persistence_* -q` passes with async boundaries exercised and no warnings about unawaited coroutines; coverage report includes new branches.
  QA scenarios: Happy — all synthetic success fixtures pass. Failure — each auth/network/schema/rate-limit/parser error maps to a documented state and no test output contains a token-like fixture value. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-16-genshin-code-monitor-full.xml`.
  Commit: Y | test(core): cover secure auth and source contracts

- [ ] 17. Add process lifecycle, end-to-end, and security smoke tests
  What to do / Must NOT do: Add `tests/test_worker_process.py`, `tests/test_e2e_pipeline.py`, and `tests/test_security_boundaries.py`. Launch the real worker entrypoint against temp paths and a local mocked HTTP server; use fake encrypted session/account; verify CLI process exits while worker continues; verify stop/status/heartbeat; assert DB/log/config do not contain raw cookies; verify bounded retry and idempotency. Do not contact real HoYoLAB or public websites in automated tests.
  Parallelization: Wave 4 | Blocked by: 11,12,13,14,15,16 | Blocks: 18,19
  References: `src/worker/entrypoint.py`, `src/worker/control.py`, `src/auth/session_store.py`, `src/worker/pipeline.py`; Microsoft Task Scheduler lifecycle docs `https://learn.microsoft.com/en-us/windows/win32/taskschd/starting-an-executable-when-a-user-logs-on`.
  Acceptance criteria: `F:\SDProject\GIPromoCode\.venv\Scripts\python.exe -m pytest tests/test_worker_process.py tests/test_e2e_pipeline.py tests/test_security_boundaries.py -q --junitxml=.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-17-genshin-code-monitor-full.xml` passes; process status transitions are observed from a second process; raw DB/log scan finds no synthetic cookie value.
  QA scenarios: Happy — mock source → worker → mock redemption → SQLite reward/statistics, then graceful stop. Failure — worker crash/stale heartbeat is detected, restart is possible, and invalid auth pauses redemption without losing queued code. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-17-genshin-code-monitor-full.json`.
  Commit: Y | test(worker): verify persistent lifecycle and end-to-end redemption

- [ ] 18. Implement Windows Task Scheduler autostart and local packaging
  What to do / Must NOT do: Add `src/platform/windows_task.py` and CLI `autostart install/status/uninstall`. Register a per-user ONLOGON task pointing to the packaged/current worker command with interactive-token context, no stored password, explicit task name, update/uninstall idempotency, and clear access-denied diagnostics. Add `pyproject.toml` entry points and a documented `python -m playwright install chromium` bootstrap; do not install a system service or require admin privileges by default.
  Parallelization: Wave 4 | Blocked by: 11,13,17 | Blocks: 19
  References: Microsoft `schtasks /create` docs `https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create`; logon trigger docs `https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--scripting-`; task logon type constraints `https://learn.microsoft.com/en-us/windows/win32/api/taskschd/nf-taskschd-itaskfolder-registertask`.
  Acceptance criteria: `... -m pytest tests/test_windows_task.py -q` mocks `schtasks`/Task Scheduler boundary and proves install/update/status/uninstall/error mapping; on a Windows smoke environment, `autostart status` reports exact task state without exposing session data.
  QA scenarios: Happy — install is idempotent and task points to the exact worker entrypoint. Failure — missing executable or access denied returns actionable error and does not claim installed; uninstall missing task is safe. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-18-genshin-code-monitor-full.json`.
  Commit: Y | feat(windows): add per-user worker autostart integration

- [ ] 19. Rewrite README and operational runbook for the real user journey
  What to do / Must NOT do: Rewrite `README.md` with Windows prerequisites, venv/install commands, Playwright browser install, `auth login` walkthrough, account selection, `worker start/status/stop`, autostart, public source configuration, rate-limit behavior, session expiry/re-login, DB backup/migration, stats examples, security boundaries, and troubleshooting. Remove false claims that cookies are already encrypted or that CLI start alone provides persistence until verified by tests.
  Parallelization: Wave 4 | Blocked by: 13,14,15,17,18 | Blocks: Final verification wave
  References: current `README.md:1-134`; Playwright auth guide; keyring docs; Microsoft Task Scheduler docs; all final CLI help output.
  Acceptance criteria: `... -m pytest tests/test_documentation.py -q` checks required headings/commands and absence of plaintext-cookie instructions; every command in README appears in `python -m src.cli --help` or a subgroup help output.
  QA scenarios: Happy — a clean temp checkout can follow documented bootstrap through `auth status`/`worker status` without undocumented steps. Failure — README explicitly explains `AUTH_REQUIRED`, unavailable keyring, expired session, source 429, and migration backup failure. Evidence `.omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-19-genshin-code-monitor-full.txt`.
  Commit: Y | docs: document secure login and persistent worker operations

## Final verification wave
> Runs after all todos in the same worker session; every check must be executed and recorded. No subagent approval is assumed.
- [ ] F1. Plan compliance audit — compare changed files and CLI behavior against every Must have/Must NOT have; verify no unrelated feature or secret handling was introduced.
- [ ] F2. Code quality/security audit — run `... -m ruff check src tests`, `... -m mypy src`, full pytest, raw-secret grep, dependency/license check, and inspect auth/logging/process boundaries.
- [ ] F3. Real local smoke — use temp DB and fake endpoints to run `auth status` without session, `worker start/status/stop`, `run-once`, source management, stats, stale PID recovery, and autostart mock. Real-account login remains manual and must be reported separately, never fabricated.
- [ ] F4. Scope fidelity — verify only public sources, no password automation, no packet capture, no remote telemetry, no plaintext session state, and no destructive history deletion.

## Commit strategy
- One conventional commit per todo, in dependency order; do not squash unrelated foundation/auth/worker/data changes during implementation.
- Commit types: `chore`, `feat`, `refactor`, `test`, `docs`, `security` with scopes `tooling`, `auth`, `storage`, `sources`, `worker`, `cli`, `windows`.
- Before each commit run `git diff --check` and the todo-specific tests; before final handoff run full suite and lint/type checks.
- Do not commit `data/`, `logs/`, `.pytest_cache/`, `.ruff_cache/`, browser state, encrypted session fixtures, `.env`, or test credentials.

## Success criteria
- [ ] User can run `auth login`, manually authenticate in the official browser window, select a Genshin account, and see `auth status` with UID/region but no secret values.
- [ ] Encrypted session survives CLI exit/restart and raw SQLite/config/log inspection contains no cookie value.
- [ ] `worker start` returns while a separate process remains alive; `worker status` reports heartbeat and `worker stop` ends it gracefully; stale state is recoverable.
- [ ] Worker polls all enabled public adapters, records source observations, deduplicates codes, and continues collection while auth is unavailable.
- [ ] With a validated session and mocked HoYoLAB endpoint, a new code is activated once, reward and response status are stored, and statistics reflect the result.
- [ ] Permanent failures are not retried automatically; transient failures obey bounded backoff and provider-safe gap.
- [ ] Session expiry transitions to `AUTH_REQUIRED`, pauses redemption, preserves queued codes, and re-login resumes safely.
- [ ] CLI source/history/stats/config commands use real repositories and work across separate processes.
- [ ] Optional ONLOGON Task Scheduler registration starts the worker in the current user's interactive session without storing an account password.
- [ ] Full automated tests pass with no unawaited-coroutine warnings; ruff and mypy pass; all final verification evidence exists.
