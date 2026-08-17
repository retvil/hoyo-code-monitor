"""Unit tests for CLI commands using Click's CliRunner."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.cli import cli
from src.config import ConfigManager
from src.scheduler import Scheduler
from src.storage import Storage


@pytest.fixture
def runner() -> CliRunner:
    """Create a Click CliRunner for testing."""
    return CliRunner()


@pytest.fixture
def mock_storage() -> MagicMock:
    """Create a mock Storage instance."""
    storage = MagicMock(spec=Storage)
    return storage


@pytest.fixture
def mock_scheduler() -> MagicMock:
    """Create a mock Scheduler instance."""
    scheduler = MagicMock(spec=Scheduler)
    return scheduler


@pytest.fixture
def mock_config_manager() -> MagicMock:
    """Create a mock ConfigManager instance."""
    config = MagicMock(spec=ConfigManager)
    return config


class TestStartCommand:
    """Tests for the 'start' command."""

    @patch("src.cli.create_scheduler_from_storage")
    def test_start_success(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test successful start command."""
        mock_scheduler = MagicMock()
        mock_scheduler.start.return_value = True
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["start"])

        assert result.exit_code == 0
        assert "Scheduler started" in result.output
        mock_scheduler.start.assert_called_once()

    @patch("src.cli.create_scheduler_from_storage")
    def test_start_already_running(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test start command when scheduler is already running."""
        mock_scheduler = MagicMock()
        mock_scheduler.start.return_value = False
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["start"])

        assert result.exit_code == 0
        assert "already running" in result.output.lower()
        mock_scheduler.start.assert_called_once()

    @patch("src.cli.create_scheduler_from_storage")
    def test_start_exception(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test start command handles exceptions."""
        mock_create_scheduler.side_effect = Exception("Database error")

        result = runner.invoke(cli, ["start"])

        assert result.exit_code != 0
        assert "Error" in result.output or "database error" in result.output.lower()


class TestStopCommand:
    """Tests for the 'stop' command."""

    @patch("src.cli.create_scheduler_from_storage")
    def test_stop_success(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test successful stop command."""
        mock_scheduler = MagicMock()
        mock_scheduler.stop.return_value = True
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["stop"])

        assert result.exit_code == 0
        assert "Scheduler stopped" in result.output
        mock_scheduler.stop.assert_called_once()

    @patch("src.cli.create_scheduler_from_storage")
    def test_stop_not_running(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test stop command when scheduler is not running."""
        mock_scheduler = MagicMock()
        mock_scheduler.stop.return_value = False
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["stop"])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()
        mock_scheduler.stop.assert_called_once()

    @patch("src.cli.create_scheduler_from_storage")
    def test_stop_timeout(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test stop command with timeout."""
        mock_scheduler = MagicMock()
        mock_scheduler.stop.return_value = False  # Timeout
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["stop"])

        assert result.exit_code == 0
        assert "timeout" in result.output.lower() or "not running" in result.output.lower()


class TestStatusCommand:
    """Tests for the 'status' command."""

    @patch("src.cli.create_scheduler_from_storage")
    def test_status_running(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test status command when scheduler is running."""
        mock_scheduler = MagicMock()
        mock_scheduler.is_running.return_value = True
        mock_scheduler.next_run_time.return_value = "2024-01-01 12:00:00"
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Scheduler is running" in result.output
        assert "Next run: 2024-01-01 12:00:00" in result.output

    @patch("src.cli.create_scheduler_from_storage")
    def test_status_stopped(self, mock_create_scheduler: MagicMock, runner: CliRunner) -> None:
        """Test status command when scheduler is stopped."""
        mock_scheduler = MagicMock()
        mock_scheduler.is_running.return_value = False
        mock_create_scheduler.return_value = mock_scheduler

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Scheduler is stopped" in result.output


class TestStatsCommand:
    """Tests for the 'stats' command."""

    @patch("src.cli.Storage")
    def test_stats_success(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test stats command with data."""
        mock_storage = MagicMock()
        mock_storage.get_stats.return_value = {
            "total_codes": 10,
            "successful": 7,
            "failed": 3,
            "by_source": {"wiki": 5, "reddit": 3, "forum": 2},
        }
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["stats"])

        assert result.exit_code == 0
        assert "Total codes: 10" in result.output
        assert "Successful: 7" in result.output
        assert "Failed: 3" in result.output
        assert "wiki: 5" in result.output


class TestRunOnceCommand:
    """Tests for the 'run-once' command."""

    @patch("src.cli.Storage")
    @patch("src.cli.SourceFetcher")
    @patch("src.cli.ConfigManager")
    def test_run_once_success(self, mock_config_class: MagicMock, mock_fetcher_class: MagicMock, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test run-once command success."""
        mock_config = MagicMock()
        mock_config.get_all.return_value = {
            "redemption_enabled": False,
            "db_path": "data/monitor.db",
        }
        mock_config_class.return_value = mock_config

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_enabled = AsyncMock(return_value={"wiki": ["TEST123"]})
        mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
        mock_fetcher.__aexit__ = AsyncMock(return_value=None)
        mock_fetcher_class.return_value = mock_fetcher

        mock_storage = MagicMock()
        mock_storage.get_code.return_value = None
        mock_storage.add_code.return_value = True
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["run-once"])

        assert result.exit_code == 0
        assert "Running single check cycle" in result.output
        assert "Stored 1 new code(s)" in result.output


class TestConfigCommand:
    """Tests for the 'config' command group."""

    @patch("src.cli.ConfigManager")
    def test_config_show(self, mock_config_class: MagicMock, runner: CliRunner) -> None:
        """Test config show command."""
        mock_config = MagicMock()
        mock_config.get_all.return_value = {
            "interval": 1800,
            "redemption_enabled": False,
            "db_path": "data/monitor.db",
            "log_level": "INFO",
            "log_file": "logs/app.log",
            "max_log_size": 10485760,
            "backup_count": 5,
        }
        mock_config_class.return_value = mock_config

        result = runner.invoke(cli, ["config", "show"])

        assert result.exit_code == 0
        # Output is JSON format
        assert '"interval": 1800' in result.output
        assert '"redemption_enabled": false' in result.output

    @patch("src.cli.ConfigManager")
    def test_config_set(self, mock_config_class: MagicMock, runner: CliRunner) -> None:
        """Test config set command."""
        mock_config = MagicMock()
        mock_config.set.return_value = None
        mock_config_class.return_value = mock_config

        result = runner.invoke(cli, ["config", "set", "interval", "3600"])

        assert result.exit_code == 0
        assert "Set interval to 3600" in result.output
        mock_config.set.assert_called_once_with("interval", "3600")

    @patch("src.cli.ConfigManager")
    def test_config_set_invalid_key(self, mock_config_class: MagicMock, runner: CliRunner) -> None:
        """Test config set with invalid key."""
        mock_config = MagicMock()
        mock_config.set.side_effect = ValueError("Unknown config key: invalid")
        mock_config_class.return_value = mock_config

        result = runner.invoke(cli, ["config", "set", "invalid", "value"])

        assert result.exit_code == 1
        assert "Error: Unknown config key: invalid" in result.output


class TestSourcesCommand:
    """Tests for the 'sources' command group."""

    @patch("src.cli.Storage")
    def test_sources_list(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources list command."""
        mock_storage = MagicMock()
        mock_storage.list_sources.return_value = [
            {"name": "wiki", "url": "https://example.com", "selector_type": "css", "selector": "table", "enabled": True},
            {"name": "reddit", "url": "https://reddit.com", "selector_type": "json", "selector": "data", "enabled": False},
        ]
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "list"])

        assert result.exit_code == 0
        assert "wiki" in result.output
        assert "reddit" in result.output
        assert "Enabled" in result.output
        assert "No" in result.output  # Disabled sources show as "No"

    @patch("src.cli.Storage")
    def test_sources_list_empty(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources list when empty."""
        mock_storage = MagicMock()
        mock_storage.list_sources.return_value = []
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "list"])

        assert result.exit_code == 0
        assert "No sources stored" in result.output

    @patch("src.cli.Storage")
    def test_sources_add(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources add command."""
        mock_storage = MagicMock()
        mock_storage.get_source.return_value = None
        mock_storage.add_source.return_value = True
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "add", "test", "https://test.com", "--selector-type", "css", "--selector", "table"])

        assert result.exit_code == 0
        assert "Added source 'test'" in result.output
        mock_storage.add_source.assert_called_once_with(
            name="test",
            url="https://test.com",
            selector_type="css",
            selector="table",
        )

    @patch("src.cli.Storage")
    def test_sources_add_duplicate(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources add with duplicate name."""
        mock_storage = MagicMock()
        mock_storage.get_source.return_value = {"name": "test"}
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "add", "test", "https://test.com"])

        assert result.exit_code == 1
        assert "Error: Source 'test' already exists" in result.output

    @patch("src.cli.Storage")
    def test_sources_remove(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources remove command."""
        mock_storage = MagicMock()
        mock_storage.remove_source.return_value = True
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "remove", "test"])

        assert result.exit_code == 0
        assert "Removed source 'test'" in result.output
        mock_storage.remove_source.assert_called_once_with("test")

    @patch("src.cli.Storage")
    def test_sources_enable(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources enable command."""
        mock_storage = MagicMock()
        mock_storage.enable_source.return_value = True
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "enable", "test"])

        assert result.exit_code == 0
        assert "Enabled source 'test'" in result.output
        mock_storage.enable_source.assert_called_once_with("test")

    @patch("src.cli.Storage")
    def test_sources_disable(self, mock_storage_class: MagicMock, runner: CliRunner) -> None:
        """Test sources disable command."""
        mock_storage = MagicMock()
        mock_storage.disable_source.return_value = True
        mock_storage_class.return_value = mock_storage

        result = runner.invoke(cli, ["sources", "disable", "test"])

        assert result.exit_code == 0
        assert "Disabled source 'test'" in result.output
        mock_storage.disable_source.assert_called_once_with("test")


class TestHelpCommand:
    """Tests for the help command."""

    def test_help(self, runner: CliRunner) -> None:
        """Test help command."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "genshin-code-monitor" in result.output
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output
        assert "stats" in result.output
        assert "sources" in result.output
        assert "config" in result.output
        assert "run-once" in result.output
