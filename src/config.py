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
from typing import Any

import toml


@dataclass
class Settings:
    """Typed application settings. All durations are in seconds."""

    poll_interval_seconds: int = 900
    source_timeout_seconds: int = 30
    redemption_enabled: bool = False
    redemption_min_gap_seconds: int = 8
    max_retry_attempts: int = 3
    retry_backoff_seconds: list[int] = field(default_factory=lambda: [30, 120, 600])
    heartbeat_seconds: int = 5
    heartbeat_timeout_seconds: int = 30
    db_path: str = "data/monitor.db"
    log_level: str = "INFO"
    log_file: str = "logs/app.log"
    max_log_size: int = 10485760
    backup_count: int = 5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConfigManager:
    """Thread-safe TOML-backed settings manager."""

    VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    DEFAULTS = Settings()

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = os.environ.get("CONFIG_PATH", "config.toml")
        self.config_path = Path(config_path)
        self._settings = Settings()
        self._lock = threading.RLock()
        self._loaded = False

    def load(self) -> Settings:
        with self._lock:
            if self.config_path.exists():
                try:
                    raw = toml.load(self.config_path)
                    self._settings = Settings.from_dict({**self.DEFAULTS.to_dict(), **raw})
                except Exception:
                    self._settings = Settings()
            else:
                self._settings = Settings()
                self.save()
            self._validate()
            self._loaded = True
            return self._settings

    def save(self) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                toml.dump(self._settings.to_dict(), f)

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
                raise ValueError(f"Unknown configuration key: {key}")
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
        if key == "poll_interval_seconds":
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"poll_interval_seconds must be a positive integer, got: {value}")
        elif key == "source_timeout_seconds":
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"source_timeout_seconds must be a positive integer, got: {value}")
        elif key == "redemption_enabled":
            if not isinstance(value, bool):
                raise ValueError(f"redemption_enabled must be a boolean, got: {value}")
        elif key == "redemption_min_gap_seconds":
            if not isinstance(value, int) or value < 6:
                raise ValueError(f"redemption_min_gap_seconds must be >= 6, got: {value}")
        elif key == "max_retry_attempts":
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"max_retry_attempts must be a non-negative integer, got: {value}")
        elif key == "retry_backoff_seconds":
            if not isinstance(value, list) or not all(isinstance(x, int) and x > 0 for x in value):
                raise ValueError(f"retry_backoff_seconds must be a list of positive integers, got: {value}")
        elif key == "heartbeat_seconds":
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"heartbeat_seconds must be a positive integer, got: {value}")
        elif key == "heartbeat_timeout_seconds":
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"heartbeat_timeout_seconds must be a positive integer, got: {value}")
        elif key == "db_path":
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"db_path must be a non-empty string, got: {value}")
        elif key == "log_level":
            if not isinstance(value, str) or value.upper() not in self.VALID_LOG_LEVELS:
                raise ValueError(f"log_level must be one of {self.VALID_LOG_LEVELS}, got: {value}")
        elif key == "log_file":
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"log_file must be a non-empty string, got: {value}")
        elif key == "max_log_size":
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"max_log_size must be a positive integer, got: {value}")
        elif key == "backup_count":
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"backup_count must be a non-negative integer, got: {value}")

    def reset_to_defaults(self) -> None:
        with self._lock:
            self._settings = Settings()
            self.save()


_config_manager: ConfigManager | None = None
_config_lock = threading.Lock()


def get_config_manager(config_path: str | Path | None = None) -> ConfigManager:
    global _config_manager
    with _config_lock:
        if _config_manager is None:
            _config_manager = ConfigManager(config_path)
        return _config_manager


def reset_config_manager() -> None:
    global _config_manager
    with _config_lock:
        _config_manager = None


# --- Backward compatibility aliases (to be removed in later todos) ---


def load_config_from_storage(storage: Any) -> SimpleNamespace:
    """Legacy compatibility: load settings from storage as a namespace."""
    cm = ConfigManager()
    cm.load()
    s = cm.settings
    return SimpleNamespace(
        poll_interval_seconds=s.poll_interval_seconds,
        source_timeout_seconds=s.source_timeout_seconds,
        redemption_enabled=storage.get_config("redemption_enabled", str(s.redemption_enabled)).lower() == "true",
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
        cookies=storage.load_cookies() if hasattr(storage, "load_cookies") else {},
    )


# Legacy alias
Config = Settings
