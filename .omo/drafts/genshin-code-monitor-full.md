---
slug: genshin-code-monitor-full
status: plan-generated
intent: clear
review_required: false
pending-action: none
approach: Replace the current mock-oriented CLI flow with a secure manual HoYoLAB browser login, Windows-protected session storage, a persistent worker process, public-source adapters, idempotent redemption, and SQLite statistics.
---

# Draft: genshin-code-monitor-full

## Components (topology ledger)
| id | outcome | status | evidence path |
|---|---|---|---|
| auth | User manually signs in once in the official HoYoLAB page; app stores reusable session securely and resolves UID/region | active | src/redeemer.py:203-236; src/config.py:228-391; config.toml:1-7 |
| ingestion | Public source adapters discover, normalize, validate, and deduplicate promo codes | active | src/scrapers/base.py:16-117; src/scrapers/wiki.py:19-206; src/scheduler.py:190-253 |
| worker | A separate Windows process survives CLI exit and exposes reliable start/stop/status/heartbeat semantics | active | src/cli.py:157-197; src/scheduler.py:262-347 |
| redemption | New codes are rate-limited, redeemed for the selected account, and attempts/rewards are persisted | active | src/scheduler.py:169-244; src/redeemer.py:203-304; src/storage.py:125-185 |
| history | User can inspect codes, sources, attempts, rewards, errors, and aggregate statistics locally | active | src/storage.py:75-185; src/cli.py:200-212 |

## Open assumptions (announced defaults)
| assumption | adopted default | rationale | reversible? |
|---|---|---|---|
| Login bootstrap | Headed browser opens official HoYoLAB login; user enters credentials/2FA manually; app never receives password | Supports one-time login without password scraping or CAPTCHA bypass | yes |
| Secret storage | Windows Credential Manager via keyring; encrypted session state is stored only as a local reference/blob | Local Windows-only target; avoids plaintext cookies and app-managed master passwords | yes |
| Background execution | Separate long-lived worker process with PID/heartbeat/control state; optional Windows Task Scheduler autostart is a later command | CLI process must be able to exit while worker continues; status/stop need cross-process state | yes |
| Source scope | Public HTTP sources only; no packet sniffing, private forums, Discord scraping, or authenticated source adapters in first implementation | Limits privacy, legal, and credential blast radius | yes |
| Configuration authority | One canonical configuration path; runtime worker and CLI read the same store, with schema versioning | Current TOML/SQLite split causes settings to be ignored | yes |
| Test strategy | TDD/tests-after hybrid: unit tests for modules, mocked HTTP/browser boundaries, process lifecycle smoke test; no real account in CI | Verifies actual async and worker behavior without credentials | yes |

## Findings (cited - path:lines)
- No login/auth command exists in src/cli.py:13-216; config.toml:1-7 contains no account/session bootstrap fields.
- Redeemer only works when caller already supplies cookies, uid, and region: src/redeemer.py:203-236.
- Scheduler has conditional redemption logic but depends on manually populated SQLite Config fields: src/scheduler.py:169-244; src/config.py:363-391.
- `start` creates a daemon thread and returns; the process exits and kills the worker: src/cli.py:157-168; src/scheduler.py:309-322.
- `stop` and `status` create new scheduler instances instead of controlling a running process: src/cli.py:171-197; src/scheduler.py:367-390.
- `run-once` explicitly skips redemption: src/cli.py:247-250; it also calls async scrape synchronously at src/cli.py:227 while BaseScraper.scrape is async at src/scrapers/base.py:74-95.
- CLI passes unsupported `description` to Storage.add_code: src/cli.py:238-242; src/storage.py:77-108.
- Cookie "encryption" is JSON serialization, not encryption: src/storage.py:381-438.
- Existing tests mock sync scraper behavior and therefore do not prove real async execution or process persistence: tests/test_cli.py:177-207.
- Existing source management calls methods absent from Storage (remove_source/enable_source/disable_source): src/cli.py:112-154; src/storage.py:259-320.

## Decisions (with rationale)
- Use a browser-assisted manual login rather than collecting the user's HoYoLAB password. This handles 2FA/CAPTCHA without credential interception and gives the user visible control.
- Store authentication material outside plaintext TOML/SQLite. Use Windows Credential Manager as primary secret storage; encrypt or securely reference Playwright storage state and fail closed when session validation fails.
- Refactor worker lifecycle before claiming background operation. A detached process with PID, heartbeat, single-instance lock, stop request, and stale-state recovery is the minimum required contract.
- Treat the current implementation as replaceable scaffolding. Preserve useful tested parsers/redeemer logic only after adapting contracts; do not preserve broken CLI behavior for compatibility.

## Scope IN
- Manual official login flow and session validation/refresh status.
- UID/region/game account discovery and account profile selection.
- Secure local session storage and logout/revoke/delete flow.
- Persistent worker with start/stop/status/log/heartbeat and graceful shutdown.
- Public source adapters: existing Wiki adapter plus official/public announcement source and Reddit/public forum adapter; generic adapter remains configurable and rate-limited.
- Normalization, validation, deduplication, source observations, redemption attempts, reward/error history, and statistics.
- CLI commands and README/config migration for the complete user journey.
- Unit, integration, lifecycle, security-log, and manual smoke checks with mock accounts/endpoints.

## Scope OUT (Must NOT have)
- Password collection, password storage, automated CAPTCHA/2FA bypass, or credential guessing.
- Packet capture or interception of arbitrary network traffic.
- Private/authenticated forum scraping beyond the official account session.
- Multiple accounts in first delivery unless the schema can support profiles without adding UI complexity; default behavior is one selected account.
- Remote telemetry, cloud storage, external dashboard, or public API server.
- Redeeming codes faster than configured provider-safe limits or retrying permanent invalid/expired responses indefinitely.
- Claiming real-account success without a manual smoke test performed by the user.

## Open questions
None. The owner accepted the recommended headed official HoYoLAB browser login with manual credentials/2FA and secure session storage; remaining implementation choices are fixed by the plan defaults.

## Approval gate
status: approved
approved_by_user: continuation after the recommended approach
pending-action: none
approach: Browser-assisted manual login, Windows-protected session storage, persistent worker, public-source boundary, unified configuration, and complete end-to-end verification plan.
