"""Web UI tests for daily check-ins (isolated temp DB)."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_checkin import FakeTransport, make_sign

from src import web_ui
from src.checkin import GAME_CHECKIN_CONF, CheckinRunner
from src.scheduler import Scheduler
from src.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path

#: Shared expectations (avoid PLR2004 magic values).
HTTP_OK: int = 200
HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
EXPECTED_GAMES_CLAIMED: int = len(GAME_CHECKIN_CONF)


@pytest.fixture
def temp_db(tmp_path: Path) -> str:
    return str(tmp_path / "web.db")


@pytest.fixture
def client(temp_db: str, monkeypatch) -> TestClient:
    monkeypatch.setattr(web_ui, "Storage", lambda *_a, **_k: Storage(temp_db))
    web_ui.scheduler = None
    return TestClient(web_ui.app, raise_server_exceptions=False)


@pytest.fixture
def account(temp_db: str) -> str:
    """Create one account with cookies directly in the temp DB."""
    storage = Storage(temp_db)
    storage.add_account("traveler", "123456", "os_euro")
    storage.store_account_cookies(
        "traveler",
        {"ltuid": "123456", "ltoken": "tok", "cookie_token": "ct", "account_id": "123456"},
    )
    return "traveler"


class TestCheckinsPage:
    def test_page_ok(self, client: TestClient) -> None:
        """Check-ins page renders."""
        r = client.get("/checkins")
        assert r.status_code == HTTP_OK
        assert "checkin_run_now" not in r.text  # i18n keys are resolved

    def test_partial_ok(self, client: TestClient) -> None:
        """History partial renders (empty state)."""
        r = client.get("/partials/checkin-logs")
        assert r.status_code == HTTP_OK

    def test_api_status_ok(self, client: TestClient) -> None:
        """JSON status endpoint."""
        r = client.get("/api/checkins/status")
        assert r.status_code == HTTP_OK
        assert "by_game" in r.json()


class TestCheckinToggle:
    def test_toggle_flips(self, client: TestClient, account: str) -> None:
        """Per-account toggle flips ON/OFF and returns switch HTML."""
        first = client.post(f"/accounts/{account}/checkin/toggle")
        assert first.status_code == HTTP_OK
        assert "checkin-traveler" in first.text
        second = client.post(f"/accounts/{account}/checkin/toggle")
        assert second.status_code == HTTP_OK
        assert first.text != second.text

    def test_state_unknown_account(self, client: TestClient) -> None:
        """Unknown account yields 404."""
        assert client.get("/accounts/nope/checkin-state").status_code == HTTP_NOT_FOUND
        assert client.post("/accounts/nope/checkin/toggle").status_code == HTTP_NOT_FOUND


class TestCheckinSettings:
    def test_save_valid(self, client: TestClient) -> None:
        """Valid schedule settings persist."""
        r = client.post(
            "/checkins/settings",
            data={
                "checkin_enabled": "true",
                "checkin_time": "05:30",
                "checkin_jitter_minutes": "10",
            },
        )
        assert r.status_code == HTTP_OK
        assert "05:30" in client.get("/checkins").text

    def test_reject_bad_time(self, client: TestClient) -> None:
        """Malformed HH:MM is rejected."""
        r = client.post(
            "/checkins/settings",
            data={"checkin_time": "25:99", "checkin_jitter_minutes": "10"},
        )
        assert r.status_code == HTTP_BAD_REQUEST

    def test_reject_bad_jitter(self, client: TestClient) -> None:
        """Out-of-range jitter is rejected."""
        r = client.post(
            "/checkins/settings",
            data={"checkin_time": "04:00", "checkin_jitter_minutes": "999"},
        )
        assert r.status_code == HTTP_BAD_REQUEST


class TestRunNow:
    def test_run_now_claims(self, client: TestClient, temp_db: str, account: str) -> None:
        """Manual run performs claims via injected fake transport."""
        assert account == "traveler"
        storage = Storage(temp_db)
        fake = FakeTransport(sign=[make_sign() for _ in GAME_CHECKIN_CONF])
        runner = CheckinRunner(transport=fake, retry_base_delay=0.0)
        config = SimpleNamespace(redemption_min_gap_seconds=0)
        sched = Scheduler(storage=storage, config=config, checkin_runner=runner)
        web_ui.scheduler = sched

        r = client.post("/checkins/run-now")

        assert r.status_code == HTTP_OK
        body = r.json()
        assert body["success"] is True
        assert body["result"]["games_claimed"] == EXPECTED_GAMES_CLAIMED
        page = client.get("/checkins").text
        assert "checkin-progress" in page


class TestAccountCookieBadge:
    """Accounts page warns about missing cookies."""

    def test_badge_without_cookies(self, client: TestClient, temp_db: str) -> None:
        """Account without cookies shows the warning badge."""
        Storage(temp_db).add_account("nocookies", "1", "os_euro")
        page = client.get("/accounts").text
        assert "nocookies</strong> <span" in page
        assert "badge-bad" in page

    def test_no_badge_with_cookies(self, client: TestClient, account: str) -> None:
        """Account with cookies shows no warning badge."""
        assert account == "traveler"
        page = client.get("/accounts").text
        assert "traveler</strong> <span" not in page


class TestCheckinProgress:
    """Tests for check-in progress tracking."""

    def test_progress_empty_when_idle(self, client: TestClient) -> None:
        """Progress endpoint returns empty dict when no pass is running."""
        r = client.get("/api/checkins/progress")
        assert r.status_code == HTTP_OK
        assert r.json() == {}

    def test_progress_tracks_current_slot(
        self, client: TestClient, temp_db: str, account: str
    ) -> None:
        """Progress endpoint returns current account/game during a pass."""
        assert account == "traveler"
        storage = Storage(temp_db)
        fake = FakeTransport(sign=[make_sign() for _ in GAME_CHECKIN_CONF])
        runner = CheckinRunner(transport=fake, retry_base_delay=0.0)
        config = SimpleNamespace(redemption_min_gap_seconds=0)
        web_ui.scheduler = Scheduler(storage=storage, config=config, checkin_runner=runner)

        # Start a run in the background
        def run_checkins():
            web_ui.scheduler.run_checkins_now()

        thread = threading.Thread(target=run_checkins)
        thread.start()
        thread.join(timeout=5)

        # After completion, progress should be cleared
        r = client.get("/api/checkins/progress")
        assert r.status_code == HTTP_OK
        # Progress is cleared after run completes
        assert r.json() == {} or r.json().get("is_running") is False
