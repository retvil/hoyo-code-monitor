"""Canonical operational settings for Genshin code monitor.

All runtime durations are expressed in seconds. Secrets, account data and
browser session state never belong here — they live in the session store.
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

from src.constants import MIN_REDEMPTION_GAP
from src.exceptions import ConfigError
from src.paths import default_config_path

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w  # type: ignore[import-not-found]
except ImportError:
    tomli_w = None  # type: ignore[assignment]

try:
    import toml as _toml_legacy  # type: ignore[import-not-found]
except ImportError:
    _toml_legacy = None  # type: ignore[assignment]


def _default(fn_name: str) -> str:
    """Lazy default from src.paths (keeps import graph acyclic)."""
    from importlib import (
        import_module,
    )

    return str(getattr(import_module("src.paths"), fn_name)())


@dataclass
class Settings:
    """Typed application settings. All durations are in seconds."""

    schema_version: int = 1
    poll_interval_seconds: int = 900
    source_timeout_seconds: int = 30
    redemption_enabled: bool = False
    redemption_min_gap_seconds: int = 8
    max_retry_attempts: int = 3
    retry_backoff_seconds: list[int] = field(default_factory=lambda: [30, 120, 600])
    heartbeat_seconds: int = 5
    heartbeat_timeout_seconds: int = 30
    db_path: str = field(default_factory=lambda: _default("default_db_path"))
    log_level: str = "INFO"
    log_file: str = field(default_factory=lambda: _default("default_log_path"))
    max_log_size: int = 10485760
    backup_count: int = 5
    update_check_enabled: bool = True
    # Per-account auth cookies. Populated at runtime by
    # load_config_from_storage (legacy SimpleNamespace path) and read by the
    # scheduler/redeemer. Excluded from TOML persistence below so secrets
    # never land in config.toml.
    cookies: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # ``cookies`` holds per-account secrets, so it must never be persisted
        # to config.toml. Drop it on serialization.
        data = asdict(self)
        data.pop("cookies", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConfigManager:
    """Thread-safe TOML-backed settings manager."""

    VALID_LOG_LEVELS: ClassVar[set[str]] = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    DEFAULTS = Settings()

    # Backward-compat migrations keyed by target version.
    # Each callable receives the raw dict loaded from disk and returns
    # an updated dict. Migrations run in ascending order.
    MIGRATIONS: ClassVar[dict[int, Any]] = {1: lambda d: d}  # baseline

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = os.environ.get("CONFIG_PATH", default_config_path())
        self.config_path = Path(config_path)
        self._settings = Settings()
        self._lock = threading.RLock()
        self._loaded = False

    def load(self) -> Settings:
        with self._lock:
            if self.config_path.exists():
                try:
                    with self.config_path.open("rb") as f:
                        raw = tomllib.load(f)
                    raw = self._migrate(raw)
                    self._settings = Settings.from_dict({**self.DEFAULTS.to_dict(), **raw})
                except Exception:
                    try:
                        if _toml_legacy:
                            raw = _toml_legacy.load(str(self.config_path))
                            raw = self._migrate(raw)
                            self._settings = Settings.from_dict({**self.DEFAULTS.to_dict(), **raw})
                        else:
                            raise
                    except Exception:
                        self._settings = Settings()
            else:
                self._settings = Settings()
                self.save()
            self._validate()
            self._loaded = True
            return self._settings

    def _migrate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Run backward-compat migrations on raw config dict."""
        current = raw.get("schema_version", 0)
        for version in sorted(self.MIGRATIONS):
            if version > current:
                raw = self.MIGRATIONS[version](raw)
                current = version
        raw.setdefault("schema_version", max(self.MIGRATIONS) if self.MIGRATIONS else 1)
        return raw

    def save(self) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            data = self._settings.to_dict()
            if tomli_w:
                with self.config_path.open("wb") as f:
                    tomli_w.dump(data, f)
            elif _toml_legacy:
                with self.config_path.open("w", encoding="utf-8") as f:
                    _toml_legacy.dump(data, f)
            else:
                with self.config_path.open("w", encoding="utf-8") as f:
                    for k, v in data.items():
                        f.write(f"{k} = {v!r}\n")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if not self._loaded:
                self.load()
            return getattr(self._settings, key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if not self._loaded:
                self.load()
            if key not in self.DEFAULTS.to_dict():
                raise ConfigError(f"Unknown configuration key: {key}")  # noqa: TRY003 -- validation message needs interpolation
            self._validate_value(key, value)
            if key == "log_level":
                value = value.upper()
            setattr(self._settings, key, value)
            self.save()

    def get_all(self) -> dict[str, Any]:
        with self._lock:
            if not self._loaded:
                self.load()
            return self._settings.to_dict()

    @property
    def settings(self) -> Settings:
        with self._lock:
            if not self._loaded:
                self.load()
            return self._settings

    def _validate(self) -> None:
        for key in self.DEFAULTS.to_dict():
            self._validate_value(key, getattr(self._settings, key))

    def _validate_value(self, key: str, value: Any) -> None:
        # (checker, error message) per key; one entry per validated setting.
        checkers: dict[str, tuple[Any, str]] = {
            "poll_interval_seconds": (
                lambda v: isinstance(v, int) and v > 0,
                "poll_interval_seconds must be a positive integer",
            ),
            "source_timeout_seconds": (
                lambda v: isinstance(v, int) and v > 0,
                "source_timeout_seconds must be a positive integer",
            ),
            "redemption_enabled": (
                lambda v: isinstance(v, bool),
                "redemption_enabled must be a boolean",
            ),
            "redemption_min_gap_seconds": (
                lambda v: isinstance(v, int) and v >= MIN_REDEMPTION_GAP,
                f"redemption_min_gap_seconds must be >= {MIN_REDEMPTION_GAP}",
            ),
            "max_retry_attempts": (
                lambda v: isinstance(v, int) and v >= 0,
                "max_retry_attempts must be a non-negative integer",
            ),
            "retry_backoff_seconds": (
                lambda v: isinstance(v, list) and all(isinstance(x, int) and x > 0 for x in v),
                "retry_backoff_seconds must be a list of positive integers",
            ),
            "heartbeat_seconds": (
                lambda v: isinstance(v, int) and v > 0,
                "heartbeat_seconds must be a positive integer",
            ),
            "heartbeat_timeout_seconds": (
                lambda v: isinstance(v, int) and v > 0,
                "heartbeat_timeout_seconds must be a positive integer",
            ),
            "db_path": (
                lambda v: isinstance(v, str) and bool(v.strip()),
                "db_path must be a non-empty string",
            ),
            "log_level": (
                lambda v: isinstance(v, str) and v.upper() in self.VALID_LOG_LEVELS,
                f"log_level must be one of {self.VALID_LOG_LEVELS}",
            ),
            "log_file": (
                lambda v: isinstance(v, str) and bool(v.strip()),
                "log_file must be a non-empty string",
            ),
            "update_check_enabled": (
                lambda v: isinstance(v, bool),
                "update_check_enabled must be a boolean",
            ),
            "max_log_size": (
                lambda v: isinstance(v, int) and v > 0,
                "max_log_size must be a positive integer",
            ),
            "backup_count": (
                lambda v: isinstance(v, int) and v >= 0,
                "backup_count must be a non-negative integer",
            ),
        }
        entry = checkers.get(key)
        if entry is None:
            return
        check, message = entry
        if not check(value):
            raise ConfigError(  # noqa: TRY003 -- validation message needs interpolation
                f"{message}, got: {value}"
            )

    def reset_to_defaults(self) -> None:
        with self._lock:
            self._settings = Settings()
            self.save()


# Mutable container instead of a module global: avoids `global` statements
# (ruff PLW0603) while keeping the same singleton semantics.
_config_manager: list[ConfigManager | None] = [None]
_config_lock = threading.Lock()


def get_config_manager(config_path: str | Path | None = None) -> ConfigManager:
    with _config_lock:
        if _config_manager[0] is None:
            _config_manager[0] = ConfigManager(config_path)
        assert _config_manager[0] is not None
        return _config_manager[0]


def reset_config_manager() -> None:
    with _config_lock:
        _config_manager[0] = None


# --- Backward compatibility aliases (to be removed in later todos) ---


def load_config_from_storage(storage: Any) -> SimpleNamespace:
    """Legacy compatibility: load settings from storage as a namespace."""
    cm = ConfigManager()
    cm.load()
    s = cm.settings
    # Get default account for cookie loading
    accounts = storage.list_accounts()
    cookies: dict[str, str] = {}
    if accounts:
        default_account = accounts[0]
        cookies = storage.load_account_cookies(default_account["name"])
        if not cookies:
            cookies = storage.load_cookies() if hasattr(storage, "load_cookies") else {}
    else:
        cookies = storage.load_cookies() if hasattr(storage, "load_cookies") else {}
    return SimpleNamespace(
        poll_interval_seconds=s.poll_interval_seconds,
        source_timeout_seconds=s.source_timeout_seconds,
        redemption_enabled=storage.get_config(
            "redemption_enabled", str(s.redemption_enabled)
        ).lower()
        == "true",
        redemption_min_gap_seconds=s.redemption_min_gap_seconds,
        max_retry_attempts=s.max_retry_attempts,
        retry_backoff_seconds=s.retry_backoff_seconds,
        heartbeat_seconds=s.heartbeat_seconds,
        heartbeat_timeout_seconds=s.heartbeat_timeout_seconds,
        db_path=s.db_path,
        log_level=s.log_level,
        log_file=s.log_file,
        max_log_size=s.max_log_size,
        backup_count=s.backup_count,
        uid=storage.get_config("uid", "") or "",
        region=storage.get_config("region", "") or "",
        game_biz=storage.get_config("game_biz", "hk4e_global") or "hk4e_global",
        lang=storage.get_config("lang", "en-us") or "en-us",
        s_lang_key=storage.get_config("s_lang_key", "en-us") or "en-us",
        cookies=cookies,
    )


# Legacy alias
Config = Settings
