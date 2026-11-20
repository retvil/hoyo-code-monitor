"""Tests for CSRF protection on state-changing routes.

These run with enforcement ENABLED — the autouse ``_csrf_test_mode`` fixture
in conftest.py sets ``HCM_TESTING=1``, so each fixture here removes it to
exercise the real middleware path.
"""

from __future__ import annotations

import gc
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.storage import Storage


@pytest.fixture
def temp_db() -> str:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    gc.collect()
    path = Path(db_path)
    if path.exists():
        for _ in range(10):
            try:
                path.unlink()
                break
            except PermissionError:
                time.sleep(0.25)
        else:
            path.unlink()


@pytest.fixture
def client(temp_db: str, monkeypatch) -> TestClient:
    """Client with CSRF enforcement active."""
    from src import (
        web_ui,
    )
    from src.web import app as web_app
    from src.web.routers import accounts, checkin, codes, sources, system

    monkeypatch.delenv("HCM_TESTING", raising=False)

    def _mock_storage(*_a, **_k):
        return Storage(temp_db)

    for _mod in (sources, accounts, codes, checkin, system):
        monkeypatch.setattr(_mod, "Storage", _mock_storage)
    monkeypatch.setattr(web_app, "seed_default_sources", _mock_seed)
    monkeypatch.setattr(
        web_app,
        "create_scheduler_from_storage",
        lambda _storage: MagicMock(status=MagicMock()),
    )
    web_app.scheduler = None
    return TestClient(web_ui.app, raise_server_exceptions=False)


async def _mock_seed(*_args, **_kwargs):
    return None


class TestCsrfEnforcement:
    """The header must be present and correct for mutating verbs."""

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_missing_token_rejected(self, client: TestClient, method: str) -> None:
        r = client.request(method, "/sources/nope/test")
        assert r.status_code == 403, method
        assert "CSRF" in r.text

    def test_wrong_token_rejected(self, client: TestClient) -> None:
        r = client.post("/language", data={"language": "ru"}, headers={"X-CSRF-Token": "wrong"})
        assert r.status_code == 403

    def test_correct_token_accepted(self, client: TestClient) -> None:
        token = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code == 200

    def test_empty_token_rejected(self, client: TestClient) -> None:
        r = client.post("/language", data={"language": "ru"}, headers={"X-CSRF-Token": ""})
        assert r.status_code == 403

    def test_readonly_methods_unaffected(self, client: TestClient) -> None:
        for path in ("/", "/sources", "/accounts", "/config", "/health"):
            assert client.get(path).status_code == 200, path


class TestOriginCheck:
    """Cross-origin requests must be blocked even with a valid token."""

    def test_foreign_origin_rejected(self, client: TestClient) -> None:
        token = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": token, "Origin": "http://evil.example.com"},
        )
        assert r.status_code == 403
        assert "Origin" in r.text

    def test_origin_suffix_lookalike_rejected(self, client: TestClient) -> None:
        """Guards the startswith() bug: 'host.evil.com' must not match 'host'."""
        token = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": token, "Origin": "http://testserver.evil.com"},
        )
        assert r.status_code == 403

    def test_same_origin_accepted(self, client: TestClient) -> None:
        token = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        )
        assert r.status_code == 200

    def test_scheme_downgrade_rejected(self, client: TestClient) -> None:
        token = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": token, "Origin": "https://testserver"},
        )
        assert r.status_code == 403


class TestTokenDelivery:
    """The token must reach the page so the client can echo it back."""

    def test_endpoint_returns_token(self, client: TestClient) -> None:
        r = client.get("/api/csrf-token")
        assert r.status_code == 200
        assert r.json()["csrf_token"]

    def test_double_submit_cookie_matches_token(self, client: TestClient) -> None:
        """The cookie must carry the same secret the endpoint hands out."""
        r = client.get("/api/csrf-token")
        token = r.json()["csrf_token"]
        cookie = r.cookies.get("hcm_csrf")
        assert cookie == token

    def test_cookie_is_readable_by_page_script(self, client: TestClient) -> None:
        """Must NOT be HttpOnly: base.html reads it to rebuild its header."""
        r = client.get("/api/csrf-token")
        set_cookie = r.headers.get("set-cookie", "")
        assert "hcm_csrf=" in set_cookie
        assert "HttpOnly" not in set_cookie
        lowered = set_cookie.lower()
        assert "samesite=strict" in lowered
        assert "path=/" in lowered
        assert "max-age=86400" in lowered

    def test_token_embedded_in_page(self, client: TestClient) -> None:
        token = client.get("/api/csrf-token").json()["csrf_token"]
        assert token in client.get("/").text

    def test_cookie_and_page_agree(self, client: TestClient) -> None:
        """Cookie and embedded token must be the same value within a day."""
        r = client.get("/api/csrf-token")
        assert r.json()["csrf_token"] in client.get("/").text
        assert client.cookies.get("hcm_csrf") == r.json()["csrf_token"]


class TestRotation:
    """The token must expire, so an observed one cannot be replayed forever."""

    @pytest.mark.usefixtures("client")
    def test_token_differs_across_days(self, monkeypatch) -> None:
        from src.web import csrf

        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-01")
        first = csrf._csrf_token()
        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-02")
        assert csrf._csrf_token() != first

    def test_stale_token_rejected_after_rotation(self, client: TestClient, monkeypatch) -> None:
        """A token leaked yesterday must not work today."""
        from src.web import csrf

        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-01")
        stale = client.get("/api/csrf-token").json()["csrf_token"]

        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-02")
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": stale},
        )
        assert r.status_code == 403
        assert "CSRF" in r.text

    def test_fresh_token_accepted_after_rotation(self, client: TestClient, monkeypatch) -> None:
        """Rotation must not lock the legitimate client out."""
        from src.web import csrf

        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-01")
        client.get("/api/csrf-token")
        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-02")

        fresh = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": fresh},
        )
        assert r.status_code == 200

    def test_token_stable_within_a_day(self, client: TestClient, monkeypatch) -> None:
        """Rotation is per-day, not per-request: one render must not break the next."""
        from src.web import csrf

        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-01")
        first = client.get("/api/csrf-token").json()["csrf_token"]
        second = client.get("/api/csrf-token").json()["csrf_token"]
        assert first == second

    @pytest.mark.usefixtures("client")
    def test_derivation_does_not_depend_on_seed_leakage(self, monkeypatch) -> None:
        """Token must be a one-way derivation, not the seed itself."""
        from src.web import csrf

        monkeypatch.setattr(csrf, "_csrf_day", lambda: "2026-01-01")
        assert csrf._csrf_token() != csrf._CSRF_SEED


class TestCsrfSeedPersistence:
    """Regression: the on-disk seed is replaced after a UTC-day rollover."""

    @pytest.mark.usefixtures("client")
    def test_stale_seed_is_replaced(self, monkeypatch, tmp_path) -> None:
        """A seed file from yesterday's UTC date is rewritten, not reused.

        Guards ``_load_or_create_csrf_seed``: the stored format is
        ``<date>|<seed>`` and a date that no longer matches today must not
        be loaded.
        """
        from datetime import UTC, datetime, timedelta

        from src.web import csrf

        monkeypatch.setenv("HCM_DATA_DIR", str(tmp_path))
        try:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
            stale_seed = "stale-seed-value-that-is-not-todays-seed"
            seed_file_in_tmp = tmp_path / csrf._CSRF_SEED_FILE
            seed_file_in_tmp.write_text(f"{yesterday}|{stale_seed}", encoding="utf-8")

            new_seed = csrf._load_or_create_csrf_seed()

            # The stale seed must not be returned.
            assert new_seed != stale_seed
            # The file was rewritten with today's date.
            raw = seed_file_in_tmp.read_text(encoding="utf-8").strip()
            stored_date, stored_seed = raw.split("|", 1)
            assert stored_date == today
            assert stored_seed == new_seed
        finally:
            monkeypatch.delenv("HCM_DATA_DIR", raising=False)

    @pytest.mark.usefixtures("client")
    def test_today_seed_is_reused(self, monkeypatch, tmp_path) -> None:
        """A seed file matching today's date is loaded without being replaced."""
        from datetime import UTC, datetime

        from src.web import csrf

        monkeypatch.setenv("HCM_DATA_DIR", str(tmp_path))
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        known_seed = "k" * 40
        seed_file_in_tmp = tmp_path / csrf._CSRF_SEED_FILE
        seed_file_in_tmp.write_text(f"{today}|{known_seed}", encoding="utf-8")

        try:
            loaded = csrf._load_or_create_csrf_seed()
            assert loaded == known_seed
        finally:
            monkeypatch.delenv("HCM_DATA_DIR", raising=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
