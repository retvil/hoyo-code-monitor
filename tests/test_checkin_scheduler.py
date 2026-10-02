"""Unit tests for daily check-ins in the Scheduler."""

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_checkin import FakeTransport, make_sign

from src.checkin import CheckinResult, CheckinRunner
from src.scheduler import Scheduler
from src.storage import Storage

#: Shared expectations (avoid PLR2004 magic values).
EXPECTED_GAMES_CLAIMED: int = 2
EXPECTED_LOG_COUNT: int = 2
FUTURE_HOUR: int = 23
FUTURE_MINUTE: int = 59
PAST_HOUR: int = 1
PAST_MINUTE: int = 0
FALLBACK_HOUR: int = 4
FALLBACK_MINUTE: int = 0


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    """Create a Storage instance on a pytest-managed temp database."""
    return Storage(str(tmp_path / "test.db"))


@pytest.fixture
def account_id(storage: Storage) -> int:
    """Create one test account with cookies and return its id."""
    row_id = storage.add_account("traveler", "123456", "os_euro")
    storage.store_account_cookies(
        "traveler",
        {"ltuid": "123456", "ltoken": "tok", "cookie_token": "ct", "account_id": "123456"},
    )
    return row_id


def make_scheduler(storage: Storage, transport: FakeTransport) -> Scheduler:
    """Build a Scheduler with instant gaps and an injected check-in runner."""
    config = SimpleNamespace(redemption_min_gap_seconds=0)
    runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
    return Scheduler(storage=storage, config=config, checkin_runner=runner)


@pytest.mark.asyncio
async def test_run_daily_checkins_success(storage: Storage, account_id: int) -> None:
    """One enabled account x MVP games produces success log rows."""
    assert account_id > 0
    transport = FakeTransport(sign=[make_sign(), make_sign()])
    scheduler = make_scheduler(storage, transport)
    result = await scheduler.run_daily_checkins("2026-09-24")

    assert result["games_claimed"] == EXPECTED_GAMES_CLAIMED  # genshin + hsr
    assert result["failed"] == 0
    logs = storage.get_checkin_logs()
    assert len(logs) == EXPECTED_LOG_COUNT
    assert {row["status"] for row in logs} == {"success"}
    assert transport.count("POST", "/sign") == EXPECTED_GAMES_CLAIMED


@pytest.mark.asyncio
async def test_run_daily_checkins_skips_disabled_account(storage: Storage) -> None:
    """Accounts with the check-in toggle off are untouched."""
    storage.add_account("sleeper", "999", "os_usa")
    storage.store_account_cookies("sleeper", {"ltuid": "999", "ltoken": "tok"})
    storage.set_account_checkin("sleeper", False)
    transport = FakeTransport()
    scheduler = make_scheduler(storage, transport)

    await scheduler.run_daily_checkins("2026-09-24")

    assert storage.get_checkin_logs() == []
    assert transport.calls == []


@pytest.mark.asyncio
async def test_run_daily_checkins_idempotent(storage: Storage, account_id: int) -> None:
    """Second run for the same date performs no new claims."""
    assert account_id > 0
    transport = FakeTransport(sign=[make_sign(), make_sign()])
    scheduler = make_scheduler(storage, transport)
    await scheduler.run_daily_checkins("2026-09-24")
    calls_after_first = len(transport.calls)

    result = await scheduler.run_daily_checkins("2026-09-24")

    assert len(transport.calls) == calls_after_first
    assert result["already"] == EXPECTED_GAMES_CLAIMED
    assert len(storage.get_checkin_logs()) == EXPECTED_LOG_COUNT


@pytest.mark.asyncio
async def test_run_daily_checkins_missing_cookies(storage: Storage) -> None:
    """Account without cookies yields failed entries, not exceptions."""
    storage.add_account("ghost", "000", "os_euro")
    transport = FakeTransport()
    scheduler = make_scheduler(storage, transport)
    result = await scheduler.run_daily_checkins("2026-09-24")

    assert result["failed"] == EXPECTED_GAMES_CLAIMED
    assert transport.calls == []
    assert {row["status"] for row in storage.get_checkin_logs()} == {"failed"}


@pytest.mark.asyncio
async def test_run_daily_checkins_updates_status(storage: Storage, account_id: int) -> None:
    """Scheduler status exposes last/next check-in info for the UI."""
    assert account_id > 0
    scheduler = make_scheduler(storage, FakeTransport(sign=[make_sign(), make_sign()]))
    await scheduler.run_daily_checkins("2026-09-24")

    status = scheduler.status
    assert status.last_checkin_run is not None
    assert status.last_checkin_success is True
    assert status.last_checkin_claimed == EXPECTED_GAMES_CLAIMED


@pytest.mark.asyncio
async def test_failed_row_today_is_retried(storage: Storage, account_id: int) -> None:
    """A failed entry for today does not block a retry (morning fail, noon cookies)."""
    assert account_id > 0
    storage.add_checkin_log(
        account_id, CheckinResult("genshin", "2026-09-24", "failed", message="no cookies")
    )
    storage.add_checkin_log(
        account_id, CheckinResult("hsr", "2026-09-24", "failed", message="no cookies")
    )
    transport = FakeTransport(sign=[make_sign(), make_sign()])
    scheduler = make_scheduler(storage, transport)
    result = await scheduler.run_daily_checkins("2026-09-24")

    assert result["failed"] == 0
    assert result["games_claimed"] == EXPECTED_GAMES_CLAIMED
    assert transport.count("POST", "/sign") == EXPECTED_GAMES_CLAIMED
    rows = storage.get_checkin_logs()
    assert len(rows) == EXPECTED_LOG_COUNT
    assert {row["status"] for row in rows} == {"success"}


@pytest.mark.asyncio
async def test_success_row_today_is_skipped(storage: Storage, account_id: int) -> None:
    """A success entry for today is never re-claimed."""
    assert account_id > 0
    storage.add_checkin_log(
        account_id,
        CheckinResult("genshin", "2026-09-24", "success", "Primogem", 100),
    )
    storage.add_checkin_log(
        account_id,
        CheckinResult("hsr", "2026-09-24", "already_claimed"),
    )
    transport = FakeTransport(sign=[make_sign(), make_sign()])
    scheduler = make_scheduler(storage, transport)
    result = await scheduler.run_daily_checkins("2026-09-24")

    assert result["already"] == EXPECTED_GAMES_CLAIMED
    assert transport.calls == []


@pytest.mark.asyncio
async def test_run_daily_checkins_sign_failure_logged(
    storage: Storage, account_id: int
) -> None:
    """API-level sign failure is stored with the provider message."""
    assert account_id > 0
    transport = FakeTransport(sign=[make_sign(10001, "Not logged in")] * 2)
    scheduler = make_scheduler(storage, transport)
    result = await scheduler.run_daily_checkins("2026-09-24")

    assert result["failed"] == EXPECTED_GAMES_CLAIMED
    assert storage.get_checkin_logs(status="failed")


class TestNextCheckinDatetime:
    """Tests for _next_checkin_datetime calculation."""

    def test_valid_time_today_future(self, storage: Storage) -> None:
        """Future time today returns today's datetime."""
        storage.set_config("checkin_time", "23:59")
        storage.set_config("checkin_jitter_minutes", "0")
        scheduler = make_scheduler(storage, FakeTransport())
        now = datetime(2026, 9, 24, 10, 0, 0)
        result = scheduler._next_checkin_datetime(now)
        assert result.date() == now.date()
        assert result.hour == FUTURE_HOUR
        assert result.minute == FUTURE_MINUTE

    def test_valid_time_today_past(self, storage: Storage) -> None:
        """Past time today returns tomorrow's datetime."""
        storage.set_config("checkin_time", "01:00")
        storage.set_config("checkin_jitter_minutes", "0")
        scheduler = make_scheduler(storage, FakeTransport())
        now = datetime(2026, 9, 24, 10, 0, 0)
        result = scheduler._next_checkin_datetime(now)
        assert result.date() > now.date()
        assert result.hour == PAST_HOUR
        assert result.minute == PAST_MINUTE

    def test_invalid_time_falls_back(self, storage: Storage) -> None:
        """Invalid time falls back to 04:00."""
        storage.set_config("checkin_time", "25:99")
        storage.set_config("checkin_jitter_minutes", "0")
        scheduler = make_scheduler(storage, FakeTransport())
        now = datetime(2026, 9, 24, 10, 0, 0)
        result = scheduler._next_checkin_datetime(now)
        assert result.hour == FALLBACK_HOUR
        assert result.minute == FALLBACK_MINUTE

    def test_jitter_clamped(self, storage: Storage) -> None:
        """Jitter is clamped to 0..120."""
        storage.set_config("checkin_time", "04:00")
        storage.set_config("checkin_jitter_minutes", "999")
        scheduler = make_scheduler(storage, FakeTransport())
        now = datetime(2026, 9, 24, 10, 0, 0)
        result = scheduler._next_checkin_datetime(now)
        # Should be tomorrow (04:00 + up to 120min jitter is still before 10:00)
        assert result.date() > now.date()


class TestMaybeRunDailyCheckins:
    """Tests for _maybe_run_daily_checkins trigger logic."""

    def test_disabled_skips(self, storage: Storage) -> None:
        """Disabled check-ins never fire."""
        storage.set_config("checkin_enabled", "false")
        scheduler = make_scheduler(storage, FakeTransport())
        scheduler._loop = None  # no loop needed
        scheduler._maybe_run_daily_checkins()
        assert storage.get_checkin_logs() == []

    def test_already_run_today_skips(self, storage: Storage) -> None:
        """Already-run today never re-fires."""
        scheduler = make_scheduler(storage, FakeTransport())
        scheduler._loop = None
        scheduler._last_checkin_date = "2026-09-24"
        scheduler._maybe_run_daily_checkins()
        assert storage.get_checkin_logs() == []

    def test_not_yet_time_skips(self, storage: Storage) -> None:
        """Before scheduled time never fires."""
        storage.set_config("checkin_time", "23:59")
        storage.set_config("checkin_jitter_minutes", "0")
        scheduler = make_scheduler(storage, FakeTransport())
        scheduler._loop = None
        with patch("src.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 24, 10, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)  # noqa: PLW0108
            scheduler._maybe_run_daily_checkins()
        assert storage.get_checkin_logs() == []


class TestCatchUpMissedCheckins:
    """Tests for catch_up_missed_checkins (PC was off during scheduled time)."""

    @pytest.mark.asyncio
    async def test_catch_up_runs_when_time_passed(self, storage: Storage, account_id: int) -> None:
        """If scheduled time passed and no log for today, catch-up runs."""
        assert account_id > 0
        storage.set_config("checkin_time", "01:00")  # already passed
        storage.set_config("checkin_jitter_minutes", "0")
        transport = FakeTransport(sign=[make_sign(), make_sign()])
        scheduler = make_scheduler(storage, transport)
        result = await scheduler.catch_up_missed_checkins()
        assert result is not None
        assert result["games_claimed"] == EXPECTED_GAMES_CLAIMED
        assert len(storage.get_checkin_logs()) == EXPECTED_LOG_COUNT

    @pytest.mark.asyncio
    async def test_catch_up_skips_when_disabled(self, storage: Storage) -> None:
        """Disabled check-ins never catch up."""
        storage.set_config("checkin_enabled", "false")
        storage.set_config("checkin_time", "01:00")
        scheduler = make_scheduler(storage, FakeTransport())
        result = await scheduler.catch_up_missed_checkins()
        assert result is None
        assert storage.get_checkin_logs() == []

    @pytest.mark.asyncio
    async def test_catch_up_skips_when_already_logged(self, storage: Storage, account_id: int) -> None:
        """If log for today exists, catch-up skips."""
        assert account_id > 0
        storage.set_config("checkin_time", "01:00")
        storage.set_config("checkin_jitter_minutes", "0")
        today = date.today().isoformat()
        storage.add_checkin_log(
            account_id, CheckinResult("genshin", today, "success")
        )
        scheduler = make_scheduler(storage, FakeTransport())
        result = await scheduler.catch_up_missed_checkins()
        assert result is None

    @pytest.mark.asyncio
    async def test_catch_up_runs_with_failed_row_today(
        self, storage: Storage, account_id: int
    ) -> None:
        """A failed entry for today does not block catch-up."""
        assert account_id > 0
        storage.set_config("checkin_time", "01:00")  # already passed
        storage.set_config("checkin_jitter_minutes", "0")
        storage.add_checkin_log(
            account_id, CheckinResult("genshin", date.today().isoformat(), "failed")
        )
        transport = FakeTransport(sign=[make_sign(), make_sign()])
        scheduler = make_scheduler(storage, transport)
        result = await scheduler.catch_up_missed_checkins()
        assert result is not None
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_catch_up_skips_when_time_not_passed(self, storage: Storage) -> None:
        """If scheduled time hasn't passed yet, catch-up skips."""
        storage.set_config("checkin_time", "23:59")
        storage.set_config("checkin_jitter_minutes", "0")
        scheduler = make_scheduler(storage, FakeTransport())
        result = await scheduler.catch_up_missed_checkins()
        assert result is None
        assert storage.get_checkin_logs() == []
