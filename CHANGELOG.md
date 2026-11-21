# Changelog

## [Unreleased]

## [1.5.3] - 2026-11-19

### Added

- **Styled redemption result** - `/codes/{code}/redeem` and `/redeem/all` now
  return an HTML fragment (when `HX-Request: true`) with a `.redeem-result-ok`
  (green) or `.redeem-result-err` (red) badge, plus a floating toast
  notification in the bottom-right corner (4s success, 8s error). Both inline
  badge and toast show the account name + reward/error message.

- **PROJECT_OVERVIEW.md** - project purpose, 8 key scenarios, architecture
  diagram, module map, data model, technology stack rationale, 10 key
  invariants, and critical known issues (C-1 through C-4) documented.

### Security (from 45-issue audit)

- SSRF source-URL validation (reject private ranges + non-HTTP schemes)
- ReDoS guard for regex source patterns
- XSS: `html.escape` on all user-controlled values in HTML endpoints
- CSRF seed persisted to date-stamped file; stale seeds rotated on startup
- CSRF token URL-encoded in `/api/csrf-token` response
- Game field validated on `/import` (unknown games skipped, not stored)
- Per-source `timeout_seconds` forwarded to `aiohttp.ClientTimeout`
- Empty reward stored as `""` not literal `"Redeemed"` when API returns no data
- `_safe_detail` scrubs cookie/token patterns from all log messages
- `storage.save_source` validates `enabled` is boolean
- `web_ui.delete_account` validates account exists before deleting
- `web_ui` login guard uses `secrets.compare_digest` for timing-safe compare
- `system_notify` WinRT COM errors no longer leak stack traces to console
- `tray.py` web-server thread joined cleanly on `SystemExit` / `KeyboardInterrupt`
- `cookies_login` Playwright browser closed in `finally` block
- `update_checker` polls GitHub with 5s timeout, never raises
- `config.py` Fernet key fallback path `data/.key` deprecated (legacy only)

### Performance

- **`get_all_stats_single_query()`** - the dashboard previously issued
  5 separate `get_stats(game=...)` queries (one per game, each running
  4 SQL statements = 20 queries). Now uses a single `GROUP BY game`
  query, reducing dashboard load by ~80% on the stats path.
- **`order_by_redeemed` in `list_codes`** - the dashboard's redeemed
  codes list was fetched unordered and sorted in Python over up to
  200 rows. `list_codes` now accepts `order_by_redeemed=True` which
  uses `ORDER BY redeemed_at DESC` in SQL.

### Refactoring

- **`_redeem_code_for_account` extracted** - the ~30-line per-account
  redemption block was duplicated in `_run_check_cycle` and
  `_redeem_new_codes`. The shared logic (cookie load, redeemer call,
  claimed-status determination, cookie-expiry handling, storage
  updates, notification) now lives in a single helper method.
- **Bounded error list** - `_run_check_cycle` accumulates errors in an
  unbounded list; now capped at 50 entries to prevent memory growth
  during long check cycles.
- **`reset_config_manager` thread-safety** - confirmed the method is
  wrapped in `_config_lock` (previously identified as a risk).

### CI / Build

- **Inno Setup smoke-test CWD fix** - the Windows installer build
  step now uses `Set-Location $env:GITHUB_WORKSPACE` at the start of
  each step, so ISCC's `out/` directory is always found regardless of
  the runner's per-step CWD. Previous runs failed because each
  `run: |` step got its own CWD context.
- **Absolute GITHUB_WORKSPACE paths** - the smoke test now checks
  `GITHUB_WORKSPACE\out\<name>` first, then `GITHUB_WORKSPACE\<name>`;
  both are absolute and CWD-independent.
- **GitHub Actions Node 24 migration** - all directly-controllable
  actions upgraded to their latest Node 24 versions.
- **Docker `FROM/AS` casing** - `FROM python:3.11-slim AS builder`
  casing normalized.

### Tests

- 30 regression tests added across 4 files covering:
  SSRF (10 cases), ReDoS (11 cases), XSS escaping (3 cases),
  import game validation (2 cases), CSRF seed persistence (2 cases),
  timeout passthrough (1 case), empty-reward parsing (3 cases).
- Time-dependent catch-up check-in tests now mock `datetime.now()`
  so they pass regardless of wall-clock time.

## [1.5.2] - 2026-11-10

### Changed
- CI/CD hardening after GitHub runner image migration to Windows Server 2025.
- **Packaging fix:** `tool.setuptools.packages.find` now uses `where=["."]`
  instead of `where=["src"]`, so the top-level `src` package is actually
  discovered.

### Fixed
- **`test_redeemer.py` unawaited-coroutine `RuntimeWarning`:** switched
  to `MagicMock` so the async context manager is entered synchronously.
- `test_storage.py` rollback test: kept `pytest.raises` on the *outer* side
  of `storage._connection()`.

## [1.5.1] - 2026-11-03

### Fixed
- **Recover source "error" status after a transient failure**: a source's
  `error_count` only ever went up and was never reset, so a source that
  recovered from a transient outage kept showing `error`/`degraded` in the
  dashboard and `/health` indefinitely. `Storage.clear_source_error(name)`
  now resets the counter to 0 on the fetch success path.

[Unreleased]: https://github.com/retvil/hoyo-code-monitor/compare/v1.5.3...HEAD
[1.5.3]: https://github.com/retvil/hoyo-code-monitor/releases/tag/v1.5.3
[1.5.2]: https://github.com/retvil/hoyo-code-monitor/releases/tag/v1.5.2
[1.5.1]: https://github.com/retvil/hoyo-code-monitor/releases/tag/v1.5.1
[0.1.0]: https://github.com/retvil/hoyo-code-monitor/releases/tag/v0.1.0
