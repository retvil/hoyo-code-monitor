"""Unit tests for the ConfigManager / Settings class."""

import os
import tempfile
from pathlib import Path

import pytest

from src.config import (
    ConfigManager,
    Settings,
    get_config_manager,
    reset_config_manager,
)


@pytest.fixture
def temp_config_file() -> str:
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        config_path = f.name
    yield config_path
    if os.path.exists(config_path):
        os.unlink(config_path)


@pytest.fixture
def config_manager(temp_config_file: str) -> ConfigManager:
    return ConfigManager(temp_config_file)


@pytest.fixture(autouse=True)
def reset_global_config() -> None:
    reset_config_manager()
    yield
    reset_config_manager()


class TestSettingsDefaults:
    def test_default_values_are_seconds_based(self) -> None:
        s = Settings()
        assert s.poll_interval_seconds == 900
        assert s.source_timeout_seconds == 30
        assert s.redemption_enabled is False
        assert s.redemption_min_gap_seconds == 8
        assert s.max_retry_attempts == 3
        assert s.retry_backoff_seconds == [30, 120, 600]
        assert s.heartbeat_seconds == 5
        assert s.heartbeat_timeout_seconds == 30
        assert s.db_path == "data/monitor.db"
        assert s.log_level == "INFO"
        assert s.log_file == "logs/app.log"
        assert s.max_log_size == 10485760
        assert s.backup_count == 5

    def test_no_auth_fields_in_settings(self) -> None:
        s = Settings()
        assert not hasattr(s, "uid")
        assert not hasattr(s, "region")
        assert not hasattr(s, "cookies")
        assert not hasattr(s, "game_biz")

    def test_to_dict_round_trip(self) -> None:
        s = Settings()
        d = s.to_dict()
        s2 = Settings.from_dict(d)
        assert s == s2


class TestConfigManagerInit:
    def test_init_with_explicit_path(self, temp_config_file: str) -> None:
        cm = ConfigManager(temp_config_file)
        assert cm.config_path == Path(temp_config_file)

    def test_init_with_env_var(self, temp_config_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONFIG_PATH", temp_config_file)
        cm = ConfigManager()
        assert cm.config_path == Path(temp_config_file)

    def test_init_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONFIG_PATH", raising=False)
        cm = ConfigManager()
        assert cm.config_path == Path("config.toml")


class TestConfigManagerLoad:
    def test_load_creates_default_config(self, config_manager: ConfigManager) -> None:
        s = config_manager.load()
        assert s.poll_interval_seconds == 900
        assert s.redemption_enabled is False

    def test_load_creates_config_file(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        assert config_manager.config_path.exists()

    def test_load_existing_config(self, config_manager: ConfigManager) -> None:
        custom = {
            "poll_interval_seconds": 3600,
            "redemption_enabled": True,
            "redemption_min_gap_seconds": 10,
        }
        with open(config_manager.config_path, "w", encoding="utf-8") as f:
            import toml
            toml.dump(custom, f)

        s = config_manager.load()
        assert s.poll_interval_seconds == 3600
        assert s.redemption_enabled is True
        assert s.redemption_min_gap_seconds == 10

    def test_load_partial_config_merges_defaults(self, config_manager: ConfigManager) -> None:
        partial = {"poll_interval_seconds": 7200}
        with open(config_manager.config_path, "w", encoding="utf-8") as f:
            import toml
            toml.dump(partial, f)

        s = config_manager.load()
        assert s.poll_interval_seconds == 7200
        assert s.redemption_enabled is False
        assert s.heartbeat_seconds == 5

    def test_load_invalid_toml_falls_back_to_defaults(self, config_manager: ConfigManager) -> None:
        with open(config_manager.config_path, "w", encoding="utf-8") as f:
            f.write("invalid toml content [[[")

        s = config_manager.load()
        assert s == Settings()

    def test_load_idempotent(self, config_manager: ConfigManager) -> None:
        s1 = config_manager.load()
        s2 = config_manager.load()
        assert s1 == s2


class TestConfigManagerSet:
    def test_set_valid_values(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        config_manager.set("poll_interval_seconds", 3600)
        config_manager.set("redemption_enabled", True)
        config_manager.set("redemption_min_gap_seconds", 12)

        assert config_manager.get("poll_interval_seconds") == 3600
        assert config_manager.get("redemption_enabled") is True
        assert config_manager.get("redemption_min_gap_seconds") == 12

    def test_set_invalid_poll_interval_raises(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        with pytest.raises(ValueError, match="poll_interval_seconds must be a positive integer"):
            config_manager.set("poll_interval_seconds", 0)

    def test_set_invalid_redemption_min_gap_raises(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        with pytest.raises(ValueError, match="redemption_min_gap_seconds must be >= 6"):
            config_manager.set("redemption_min_gap_seconds", 3)

    def test_set_invalid_retry_backoff_raises(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        with pytest.raises(ValueError, match="retry_backoff_seconds must be a list"):
            config_manager.set("retry_backoff_seconds", "invalid")

    def test_set_unknown_key_raises(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        with pytest.raises(ValueError, match="Unknown configuration key"):
            config_manager.set("unknown_key", "value")

    def test_set_log_level_normalizes(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        config_manager.set("log_level", "debug")
        assert config_manager.get("log_level") == "DEBUG"


class TestConfigManagerGetAll:
    def test_get_all_returns_dict(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        d = config_manager.get_all()
        assert isinstance(d, dict)
        assert "poll_interval_seconds" in d
        assert "uid" not in d
        assert "cookies" not in d


class TestConfigManagerReset:
    def test_reset_to_defaults(self, config_manager: ConfigManager) -> None:
        config_manager.load()
        config_manager.set("poll_interval_seconds", 3600)
        config_manager.reset_to_defaults()
        assert config_manager.get("poll_interval_seconds") == 900


class TestGlobalConfigManager:
    def test_get_config_manager_returns_same_instance(self, temp_config_file: str) -> None:
        cm1 = get_config_manager(temp_config_file)
        cm2 = get_config_manager(temp_config_file)
        assert cm1 is cm2

    def test_reset_config_manager(self, temp_config_file: str) -> None:
        cm1 = get_config_manager(temp_config_file)
        reset_config_manager()
        cm2 = get_config_manager(temp_config_file)
        assert cm1 is not cm2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
