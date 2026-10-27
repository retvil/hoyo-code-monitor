# Contributing to HoYo Code Monitor

This is a single-author project. PRs and issues are welcome for:

- Bug fixes with a failing test first (see [Testing](#testing))
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
   `!define APP_VERSION` in `installer.nsi` (all three must match).
2. Update `CHANGELOG.md` (Keep a Changelog format).
3. Build locally: `pyinstaller genshin-code-monitor.spec --clean && makensis installer.nsi`.
4. Run `pytest` + `ruff` + `mypy` once more.
5. `git tag v<version> && git push --tags` — CI creates a draft release;
   review and publish from the GitHub UI.

## Conventions

- Code, comments, variable names: **English**
- User-facing strings: route through `src/i18n.py` (all 6 languages)
- Don't add dependencies without a reason; the exe is ~132 MB already
- `display_status` (storage) and `STATUS_*` (checkin) are the source of truth
  for code state — don't duplicate that logic
