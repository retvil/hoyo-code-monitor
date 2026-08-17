# genshin-code-monitor - Work Plan

## TL;DR (For humans)
A local Python application that monitors Genshin Impact code sources (websites, forums), automatically redeems valid codes via Hoyolab API using user-provided cookies, and logs redemption statistics (which codes gave what rewards, timestamps). It runs in the background, provides CLI to view stats and manage sources.

**Why this approach:** Python offers rich libraries for HTTP scraping and async operations, easy to deploy locally, and can reuse existing open-source scraper patterns. Using SQLite for persistence ensures low overhead and reliability.

**What it will NOT do:** It will not store or transmit user credentials externally; all data stays local. It will not bypass Hoyolab rate limits or perform malicious actions. Redemption only occurs after user provides valid cookies and opts into auto-redeem.

**Effort:** Medium
**Risk:** Low - main risk is scraping site changes breaking parsers; mitigated by modular scrapers and easy updates.
**Decisions to sanity-check:** Choice of Python vs Node.js; storage format (SQLite vs JSON); whether to include a web dashboard; encryption of stored cookies.

Your next move: approve to proceed with implementation.

---

## TL;DR (machine): Medium | Low | Local code monitor with auto-redeem and stats CLI

## Scope
### Must have
- Scheduler to periodically check code sources (default 30 minutes, configurable)
- Scraper modules for at least three sources: Genshin Impact Wiki, Reddit r/GenshinImpact (via JSON), and a generic forum scraper (e.g., Hoyolab code redemption page)
- Redeemer module that sends code to Hoyolab API endpoint using user-provided cookies (ltuid, ltoken, cookie_token_v2) and logs success/failure with reward details
- Storage layer (SQLite database) tracking: attempted codes, redemption status, reward description, timestamp, source
- CLI interface (using Click or argparse) with commands: start, stop, status, stats, sources add/remove, config
- Logging of all activities to a rotating log file
- Graceful shutdown on SIGINT/SIGTERM
- Configuration file (TOML or JSON) for scheduler interval, sources list, and redemption toggle

### Must NOT have (guardrails, anti-slop, scope boundaries)
- Remote telemetry, analytics, or any data exfiltration
- Automatic redemption without explicit user opt-in (default off; user must enable via CLI)
- Storage of cookies in plain text without protection (will encrypt using a key derived from machine-specific secret or prompt for password each session)
- Web server exposing external interfaces (if a dashboard is added, it will bind to localhost only)
- Dependency on headless browsers ( Selenium, Playwright ) unless absolutely necessary; prefer lightweight HTTP+HTML parsing
- Automatic account creation or credential guessing

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD + pytest
- Evidence: .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-<N>-genshin-code-monitor.xml (JUnit) or .omo/evidence/ for manual
- Unit tests for each module: scraper parsers, redeemer logic, storage CRUD, scheduler jobs
- Integration tests using mocked HTTP servers (responses library) to verify end-to-end flow
- Code coverage threshold: 80%
- Linting: ruff with strictness
- Type checking: mypy (if using type hints)

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. Design storage schema and implement SQLite wrapper | None | 2,3,4 | 5 |
| 2. Implement base scraper class and concrete scraper for Wiki | 1 | 3,4 | 5,6 |
| 3. Implement redeemer module with Hoyolab API communication | 1 | 4 | 5,6,7 |
| 4. Implement scheduler with APScheduler or asyncio loop | 1,2,3 | 5 | 6,7 |
| 5. Implement CLI command group and wiring | 1,2,3,4 | 6,7 | 8 |
| 6. Add configuration loading/saving (TOML) | 1,2,3,4 | 7 | 8 |
| 7. Implement logging and graceful shutdown | 1,2,3,4 | 8 |  |
| 8. Write end-to-end tests and fix flaky issues | 5,6,7 | None |  |
| 9. Create README with usage instructions and disclaimer | 8 | None |  |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] 1. Design storage schema and implement SQLite wrapper
  What to do / Must NOT do: Create SQLite DB with tables: codes (id, code, source, attempted_at, redeemed, reward, redeemed_at); sources (id, name, url, selector_type, selector, enabled); config (key, value). Must NOT store plaintext cookies; store encrypted or prompt each run.
  Parallelization: Wave 1 | Blocked by: None | Blocks: 2,3,4
  References (executor has NO interview context - be exhaustive): 
    - SQLite Python docs: https://docs.python.org/3/library/sqlite3.html
    - SQLAlchemy Core optional but not required; we will use raw SQL for simplicity.
  Acceptance criteria (agent-executable): 
    - python -m pytest tests/test_storage.py -v
    - Test creates DB, inserts/retrieves rows, handles migrations.
  QA scenarios (name the exact tool + invocation): happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-1-genshin-code-monitor.xml
    Happy: Insert a code, retrieve by code, assert fields.
    Failure: Attempt to insert duplicate unique code (if unique constraint) and expect integrity error.
  Commit: Y | feat(storage): add SQLite wrapper with CRUD operations

- [ ] 2. Implement base scraper class and concrete scraper for Wiki
  What to do / Must NOT do: BaseScraper with fetch() and parse() methods. WikiScraper extracts codes from https://genshin-impact.fandom.com/wiki/Promotional_Code using BeautifulSoup. Must NOT rely on brittle XPath; use CSS selectors with fallbacks.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 3,4
  References: 
    - BeautifulSoup documentation: https://www.crummy.com/software/BeautifulSoup/bs4/doc/
    - Example from GauravM512/genshin-redeem-code (scraping logic)
  Acceptance criteria: 
    - python -m pytest tests/test_scraper_wiki.py -v
    - Given a sample HTML snippet, returns list of dicts with code and description.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-2-genshin-code-monitor.xml
    Happy: Parse known HTML, extract at least one valid code.
    Failure: Return empty list on malformed HTML, log warning.
  Commit: Y | feat(scraper): add base class and WikiScraper

- [ ] 3. Implement redeemer module with Hoyolab API communication
  What to do / Must NOT do: Redeemer class that takes cookies (ltuid, ltoken, cookie_token_v2) and sends POST to https://sg-hk4e-api.hoyolab.com/common/apicdkey/api/webExchangeCdkey with parameters. Must NOT hardcode endpoints; pull from config. Must handle HTTP errors and parse JSON response per IRedeemCode interface.
  Parallelization: Wave 1 | Blocked by: 1,2 | Blocks: 4,5
  References: 
    - hoyolab-api vermaysha/src/modules/redeem/redeem.ts (translated to Python)
    - Hoyolab API documentation (community)
  Acceptance criteria: 
    - python -m pytest tests/test_redeemer.py -v
    - With mocked server, successful redemption returns reward; failure returns error.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-3-genshin-code-monitor.xml
    Happy: Mock 200 response with {"retcode":0, "message":"Success", "game_uid":..., "cdkey":..., "reward":"..."} -> returns success object.
    Failure: Mock 400 or retcode !=0 -> returns failure with error message.
  Commit: Y | feat(redeemer): add Hoyolab redemption client

- [ ] 4. Implement scheduler with APScheduler or asyncio loop
  What to do / Must NOT do: Background scheduler that runs scraper collection at interval, processes new codes, attempts redemption if enabled, logs results. Must NOT block main thread; must support start/stop/pause.
  Parallelization: Wave 2 | Blocked by: 1,2,3 | Blocks: 5,6,7
  References: 
    - APScheduler docs: https://apscheduler.readthedocs.io/
    - Alternative: asyncio.create_task with sleep loop.
  Acceptance criteria: 
    - python -m pytest tests/test_scheduler.py -v
    - Scheduler starts, triggers job, stops gracefully.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-4-genshin-code-monitor.xml
    Happy: Schedule a job that increments a counter; after interval, assert counter increased.
    Failure: Scheduler handles exception in job without crashing.
  Commit: Y | feat(scheduler): add APScheduler-based job runner

- [ ] 5. Implement CLI command group and wiring
  What to do / Must NOT do: CLI using Click (or argparse) with commands: start, stop, status, stats, sources add/remove, config set/show. Must NOT expose sensitive data in output (e.g., mask cookies).
  Parallelization: Wave 2 | Blocked by: 1,2,3,4 | Blocks: 6,7,8
  References: 
    - Click documentation: https://click.palletsprojects.com/
    - Existing CLI apps in repo (none)
  Acceptance criteria: 
    - python -m pytest tests/test_cli.py -v
    - CLI parses commands, calls appropriate functions, returns correct exit codes.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-5-genshin-code-monitor.xml
    Happy: `genshin-code-monitor start` launches scheduler in background and returns immediately.
    Failure: Invalid command shows help and exits 2.
  Commit: Y | feat(cli): add Click-based interface with subcommands

- [ ] 6. Add configuration loading/saving (TOML)
  What to do / Must NOT do: Load config from config.toml (sources list, interval, redemption_enabled, db_path). Save changes via CLI. Must NOT write cookies to config; cookies prompted via CLI or env var.
  Parallelization: Wave 2 | Blocked by: 1,2,3,4 | Blocks: 7,8
  References: 
    - toml library: https://pypi.org/project/toml/
  Acceptance criteria: 
    - python -m pytest tests/test_config.py -v
    - Config loads defaults, can be updated, persists.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-6-genshin-code-monitor.xml
    Happy: Set interval to 60, reload config, assert interval changed.
    Failure: Invalid TOML raises error and leaves config unchanged.
  Commit: Y | feat(config): add TOML config manager

- [ ] 7. Implement logging and graceful shutdown
  What to do / Must NOT do: Rotating file handler (size-based) logging to ./logs/app.log. Capture SIGINT/SIGTERM to stop scheduler and exit. Must NOT log cookies or redemption payloads.
  Parallelization: Wave 2 | Blocked by: 1,2,3,4 | Blocks: 8
  References: 
    - logging.handlers.RotatingFileHandler
    - signal module
  Acceptance criteria: 
    - python -m pytest tests/test_logging.py -v
    - Log file rotates, signals handled.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-7-genshin-code-monitor.xml
    Happy: Send SIGINT, app exits with log entry "Shutting down".
    Failure: Logging does not crash on disk full (handled gracefully).
  Commit: Y | feat(logging): add rotating logs and signal handlers

- [ ] 8. Write end-to-end tests and fix flaky issues
  What to do / Must NOT do: Full integration test with mocked HTTP servers for sources and Hoyolab endpoint, verifying that a new code found leads to redemption attempt and storage update.
  Parallelization: Wave 3 | Blocked by: 5,6,7 | Blocks: None
  References: 
    - responses library: https://pypi.org/project/responses/
    - pytest-mock
  Acceptance criteria: 
    - python -m pytest tests/test_e2e.py -v
    - End-to-end flow passes with 90% success rate.
  QA scenarios: happy + failure, Evidence .omo/evidence/ulw/<session>/<goalId>/a<attempt>/task-8-genshin-code-monitor.xml
    Happy: Mocked wiki returns new code, Hoyolab mock accepts and returns reward; DB shows redeemed.
    Failure: Network timeout leads to retry logic (if implemented) or graceful error.
  Commit: Y | feat(test): add end-to-end scenario

- [ ] 9. Create README with usage instructions and disclaimer
  What to do / Must NOT do: README.md with quick start, configuration guide, CLI reference, privacy disclaimer (no data leaves machine), and legal notice about code scraping.
  Parallelization: Wave 3 | Blocked by: 8 | Blocks: None
  References: 
    - Existing READMEs from similar projects.
  Acceptance criteria: 
    - File exists and contains required sections.
    - Spellcheck passes (optional).
  QA scenarios: N/A (documentation)
  Commit: Y | docs: add README.md

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

## Commit strategy
- Use conventional commits: feat(<scope>): <description>
- Squash merge into main after review.
- Tag releases with semantic versioning.

## Success criteria
- [ ] Application starts without errors, reads config, initializes DB.
- [ ] Scheduler runs scraper jobs at defined interval.
- [ ] Scrapers return at least one code from each source (when mocked).
- [ ] Redeemer successfully sends request to Hoyolab mock and logs result.
- [ ] CLI commands start, stop, status, stats respond correctly.
- [ ] Logs rotate and contain expected entries.
- [ ] All unit tests pass with coverage >=80%.
- [ ] Manual QA: run with real cookies (optional) and verify no data exfiltration (network monitor).