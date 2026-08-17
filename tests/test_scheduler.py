"""Unit tests for the Scheduler class."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.redeemer import RedemptionResult
from src.scheduler import Scheduler, create_scheduler_from_storage
from src.storage import Storage


class TestSchedulerInitialization:
    """Tests for Scheduler initialization."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def storage(self, temp_db: str) -> Storage:
        return Storage(temp_db)

    def test_init_with_storage(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)
        assert scheduler.storage is storage
        assert scheduler.config is not None
        assert scheduler.redeemer is not None

    def test_init_with_custom_config(self, storage: Storage) -> None:
        from src.config import Settings
        custom_config = Settings(poll_interval_seconds=600)
        scheduler = Scheduler(storage=storage, config=custom_config)
        assert scheduler.config.poll_interval_seconds == 600

    def test_init_with_custom_redeemer(self, storage: Storage) -> None:
        mock_redeemer = MagicMock()
        scheduler = Scheduler(storage=storage, redeemer=mock_redeemer)
        assert scheduler.redeemer is mock_redeemer


class TestSchedulerStatus:
    """Tests for Scheduler status."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def storage(self, temp_db: str) -> Storage:
        return Storage(temp_db)

    def test_initial_status(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)
        status = scheduler.status
        assert status.running is False
        assert status.next_run is None
        assert status.last_run is None
        assert status.last_run_success is True
        assert status.last_run_codes_found == 0
        assert status.last_run_codes_redeemed == 0
        assert status.error_message is None

    def test_is_running_false_initially(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)
        assert scheduler.is_running() is False


class TestSchedulerRunOnce:
    """Tests for run_once method."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def storage(self, temp_db: str) -> Storage:
        return Storage(temp_db)

    def test_run_once_no_sources(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)

        # Mock seed_default_sources to avoid real HTTP calls
        with patch("src.scheduler.seed_default_sources", new_callable=AsyncMock) as mock_seed:
            mock_seed.return_value = 0
            result = scheduler.run_once()

        assert result["success"] is True
        assert result["codes_found"] == 0
        assert result["codes_redeemed"] == 0
        assert "No enabled sources configured" in result["errors"]

    def test_run_once_with_mocked_fetcher(self, storage: Storage) -> None:
        storage.add_source("test", "https://example.com", "css", ".code")

        scheduler = Scheduler(storage=storage)

        # Mock the SourceFetcher
        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(return_value={"test": ["GENSHIN123", "STARRAIL456"]})
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            result = scheduler.run_once()

        assert result["success"] is True
        assert result["codes_found"] == 2
        assert result["codes_redeemed"] == 0  # Redemption not enabled by default

    def test_run_once_stores_codes(self, storage: Storage) -> None:
        storage.add_source("test", "https://example.com", "css", ".code")

        scheduler = Scheduler(storage=storage)

        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(return_value={"test": ["GENSHIN123"]})
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            result = scheduler.run_once()

        assert result["codes_found"] == 1
        # Verify code was stored
        code = storage.get_code("GENSHIN123")
        assert code is not None
        assert "test" in code["sources"]


class TestSchedulerRedemption:
    """Tests for redemption logic in scheduler."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def storage(self, temp_db: str) -> Storage:
        return Storage(temp_db)

    def test_redemption_disabled_by_default(self, storage: Storage) -> None:
        storage.add_source("test", "https://example.com", "css", ".code")

        mock_redeemer = AsyncMock()
        scheduler = Scheduler(storage=storage, redeemer=mock_redeemer)

        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(return_value={"test": ["GENSHIN123"]})
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            with patch("src.scheduler.seed_default_sources", new_callable=AsyncMock) as mock_seed:
                mock_seed.return_value = 0
                result = scheduler.run_once()

        assert result["codes_redeemed"] == 0
        # Redeemer should not be called
        mock_redeemer.redeem_code.assert_not_called()

    def test_redemption_enabled_with_cookies(self, storage: Storage) -> None:
        storage.add_source("test", "https://example.com", "css", ".code")
        storage.set_config("uid", "12345")
        storage.set_config("region", "os_usa")
        storage.set_config("redemption_enabled", "true")
        storage.store_cookies({"ltuid": "12345", "ltoken": "abcdef"})

        from src.config import load_config_from_storage
        config = load_config_from_storage(storage)
        scheduler = Scheduler(storage=storage, config=config)

        mock_redeemer = AsyncMock()
        mock_redeemer.redeem_code = AsyncMock(return_value=RedemptionResult(
            success=True,
            reward="Primogems x100",
            message="OK",
            raw_response={"retcode": 0, "message": "OK", "data": {"award": "Primogems x100"}},
        ))
        scheduler.redeemer = mock_redeemer

        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(return_value={"test": ["GENSHIN123"]})
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            with patch("src.scheduler.seed_default_sources", new_callable=AsyncMock) as mock_seed:
                mock_seed.return_value = 0
                result = scheduler.run_once()

        assert result["codes_redeemed"] == 1
        mock_redeemer.redeem_code.assert_called_once()
        call_args = mock_redeemer.redeem_code.call_args
        assert call_args.kwargs["code"] == "GENSHIN123"
        assert call_args.kwargs["cookies"]["ltuid"] == "12345"

    def test_redemption_failure_logged(self, storage: Storage) -> None:
        storage.add_source("test", "https://example.com", "css", ".code")
        storage.set_config("uid", "12345")
        storage.set_config("region", "os_usa")
        storage.set_config("redemption_enabled", "true")
        storage.store_cookies({"ltuid": "12345", "ltoken": "abcdef"})

        from src.config import load_config_from_storage
        config = load_config_from_storage(storage)
        scheduler = Scheduler(storage=storage, config=config)

        mock_redeemer = AsyncMock()
        mock_redeemer.redeem_code = AsyncMock(return_value=RedemptionResult(
            success=False,
            reward=None,
            message="Invalid code",
            raw_response={"retcode": -1, "message": "Invalid code"},
        ))
        scheduler.redeemer = mock_redeemer

        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(return_value={"test": ["GENSHIN123"]})
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            with patch("src.scheduler.seed_default_sources", new_callable=AsyncMock) as mock_seed:
                mock_seed.return_value = 0
                result = scheduler.run_once()

        assert result["codes_redeemed"] == 0
        assert result["success"] is True  # Cycle succeeds even if redemption fails
        # Check redemption log was created
        logs = storage.get_redemption_logs()
        assert len(logs) == 1
        assert logs[0]["status"] == "failed"
        assert logs[0]["error_message"] == "Invalid code"


class TestSchedulerStartStop:
    """Tests for scheduler start/stop."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def storage(self, temp_db: str) -> Storage:
        return Storage(temp_db)

    def test_start_stop(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)
        assert scheduler.start() is True
        assert scheduler.is_running() is True
        assert scheduler.stop() is True
        assert scheduler.is_running() is False

    def test_start_already_running(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)
        scheduler.start()
        assert scheduler.start() is False  # Already running
        scheduler.stop()

    def test_stop_not_running(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)
        assert scheduler.stop() is False


class TestCreateSchedulerFromStorage:
    """Tests for create_scheduler_from_storage factory."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    def test_create_scheduler(self, temp_db: str) -> None:
        scheduler = create_scheduler_from_storage(temp_db)
        assert isinstance(scheduler, Scheduler)
        assert scheduler.storage is not None
        assert scheduler.config is not None
        assert scheduler.redeemer is not None


class TestSchedulerCheckCycle:
    """Tests for _run_check_cycle internal method."""

    @pytest.fixture
    def temp_db(self) -> str:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def storage(self, temp_db: str) -> Storage:
        return Storage(temp_db)

    @pytest.mark.asyncio
    async def test_check_cycle_seeds_default_sources(self, storage: Storage) -> None:
        scheduler = Scheduler(storage=storage)

        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(return_value={})
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            result = await scheduler._run_check_cycle()

        # Should have seeded default sources
        sources = storage.list_sources()
        assert len(sources) >= 2
        names = {s["name"] for s in sources}
        assert "wiki" in names
        assert "wiki_api" in names

    @pytest.mark.asyncio
    async def test_check_cycle_handles_fetch_errors(self, storage: Storage) -> None:
        storage.add_source("test", "https://example.com", "css", ".code")

        scheduler = Scheduler(storage=storage)

        with patch("src.scheduler.SourceFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_all_enabled = AsyncMock(side_effect=Exception("Network error"))
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            with patch("src.scheduler.seed_default_sources", new_callable=AsyncMock) as mock_seed:
                mock_seed.return_value = 0
                result = await scheduler._run_check_cycle()

        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert "Network error" in result["errors"][0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
