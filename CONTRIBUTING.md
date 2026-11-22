# Contributing to HoYo Code Monitor

This is a single-author project. PRs and issues are welcome for:

- Bug fixes with a failing test first (see [Testing](#lint--test))
- New data sources (see `src/sources.py`)
- i18n strings for a new language (see `src/i18n.py`)

## Development setup

```powershell
git clone https://github.com/retvil/hoyo-code-monitor
cd hoyo-code-monitor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .[dev]
```

## Lint + test

```powershell
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy src
.venv\Scripts\python.exe -m pytest tests -q
```

All three must be green before opening a PR.

## Release checklist (maintainer)

1. Bump `APP_VERSION` in `src/constants.py`, `version` in `pyproject.toml`,
   and `MyAppVersion` in `installer.iss` (all three must match).
2. Update `CHANGELOG.md` (Keep a Changelog format).
3. Build locally: `pyinstaller genshin-code-monitor.spec --clean && iscc "/DMyAppVersion=<ver>" installer.iss`.
4. Run `pytest` + `ruff` + `mypy` once more.
5. `git tag v<version> && git push --tags` — CI creates a draft release;
   review and publish from the GitHub UI.

## Conventions

- Code, comments, variable names: **English**
- User-facing strings: route through `src/i18n.py` (all 6 languages)
- Don't add dependencies without a reason; the exe is ~132 MB already
- `display_status` (storage) and `STATUS_*` (checkin) are the source of truth
  for code state — don't duplicate that logic

## Documentation layout

```
README.md            # main English README (repo root)
docs/
  README.md          # documentation index
  README.<lang>.md   # 11 localized READMEs
  PROJECT_OVERVIEW.md
  ROADMAP.md
  WORKFLOW.md
  screenshots/
CHANGELOG.md         # single source of truth for release history
CONTRIBUTING.md      # this file
```

- **Localized READMEs** live in `docs/` to keep the repo root clean. When you
  change the English `README.md`, mirror the change into the localized files
  (translations are maintained by hand — see the language table in `docs/README.md`).
- **`CHANGELOG.md` is not localized.** It is the single source of truth for
  release history. Do not create per-language `CHANGELOG.<lang>.md` copies —
  they drift and go stale.
- **Screenshots** are per-language: `docs/screenshots/<screenshot>_<lang>.png`
  (6 shots × 12 languages).
