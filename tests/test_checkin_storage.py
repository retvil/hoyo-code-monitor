"""Unit tests for daily check-in storage (migration v13 + log CRUD)."""

import sqlite3
from pathlib import Path

import pytest

from src.checkin import CheckinResult
from src.migrations import CURRENT_VERSION
from src.storage import Storage

#: Shared expectations (avoid PLR2004 magic values).
EXPECTED_SCHEMA_VERSION: int = 13
EXPECTED_REWARD_AMOUNT: int = 100
EXPECTED_LOG_COUNT: int = 2
UUID_HEX_LENGTH: int = 32


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    """Create a Storage instance on a pytest-managed temp database.

    tmp_path needs no manual cleanup (avoids Windows file-lock teardown errors).
    """
    return Storage(str(tmp_path / "test.db"))


@pytest.fixture
def account_id(storage: Storage) -> int:
    """Create one test account and return its id."""
    return storage.add_account("traveler", "123456", "os_euro")


def success_result(game: str = "genshin", date: str = "2026-09-24") -> CheckinResult:
    """Build a success CheckinResult for storage tests."""
    return CheckinResult(
        game=game,
        claimed_date=date,
        status="success",
        reward_name="Primogem",
        reward_amount=EXPECTED_REWARD_AMOUNT,
        total_sign_day=3,
        message="OK",
    )


class TestCheckinMigration:
    """Tests for migration v13."""

    def test_current_version_covers_checkin(self) -> None:
        """Schema version covers the check-in log."""
        assert CURRENT_VERSION == EXPECTED_SCHEMA_VERSION

    def test_checkin_log_table_exists(self, storage: Storage) -> None:
        """Fresh databases contain checkin_log with the uniqueness guard."""
        with storage._connection() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "checkin_log" in tables
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='checkin_log'"
            ).fetchone()[0]
            assert "UNIQUE(account_id, game, claimed_date)" in sql


class TestCheckinLogCRUD:
    """Tests for check-in log methods."""

    def test_add_and_get_log(self, storage: Storage, account_id: int) -> None:
        """Round-trip of one success entry."""
        row_id = storage.add_checkin_log(account_id, success_result())
        assert row_id == 1
        logs = storage.get_checkin_logs()
        assert len(logs) == 1
        assert logs[0]["game"] == "genshin"
        assert logs[0]["reward_name"] == "Primogem"
        assert logs[0]["reward_amount"] == EXPECTED_REWARD_AMOUNT
        assert logs[0]["error_message"] is None

    def test_duplicate_date_rejected(self, storage: Storage, account_id: int) -> None:
        """Second entry for the same account x game x date fails (idempotency guard)."""
        storage.add_checkin_log(account_id, success_result())
        with pytest.raises(sqlite3.IntegrityError):
            storage.add_checkin_log(account_id, success_result())
        # Same date but different game is fine.
        storage.add_checkin_log(account_id, success_result(game="hsr"))
        assert len(storage.get_checkin_logs()) == EXPECTED_LOG_COUNT

    def test_filters(self, storage: Storage, account_id: int) -> None:
        """Filter by game and status; failed entries keep the error text."""
        storage.add_checkin_log(account_id, success_result())
        failed = CheckinResult(
            game="hsr",
            claimed_date="2026-09-24",
            status="failed",
            message="boom",
        )
        storage.add_checkin_log(account_id, failed)
        assert len(storage.get_checkin_logs(game="hsr")) == 1
        assert len(storage.get_checkin_logs(status="failed")) == 1
        assert storage.get_checkin_logs(status="failed")[0]["error_message"] == "boom"

    def test_last_status(self, storage: Storage, account_id: int) -> None:
        """Most recent entry per account x game."""
        assert storage.last_checkin_status(account_id, "genshin") is None
        storage.add_checkin_log(account_id, success_result(date="2026-09-23"))
        storage.add_checkin_log(
            account_id,
            CheckinResult(
                game="genshin", claimed_date="2026-09-24", status="already_claimed"
            ),
        )
        last = storage.last_checkin_status(account_id, "genshin")
        assert last is not None
        assert last["status"] == "already_claimed"


class TestCheckinToggles:
    """Tests for per-account check-in flags and device ids."""

    def test_toggle_defaults_to_global(self, storage: Storage) -> None:
        """No override means the global flag decides (default on)."""
        assert storage.is_account_checkin_enabled("traveler") is True
        storage.set_config("checkin_enabled", "false")
        assert storage.is_account_checkin_enabled("traveler") is False

    def test_toggle_override(self, storage: Storage) -> None:
        """Per-account override wins over the global flag."""
        storage.set_account_checkin("traveler", False)
        assert storage.is_account_checkin_enabled("traveler") is False
        storage.set_account_checkin("traveler", True)
        assert storage.is_account_checkin_enabled("traveler") is True

    def test_device_id_stable_and_unique(self, storage: Storage) -> None:
        """Device id is generated once and differs per account."""
        first = storage.get_account_device_id("traveler")
        assert len(first) == UUID_HEX_LENGTH
        assert storage.get_account_device_id("traveler") == first
        assert storage.get_account_device_id("other") != first
