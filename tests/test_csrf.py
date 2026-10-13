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
    from src import web_ui

    monkeypatch.delenv("HCM_TESTING", raising=False)
    monkeypatch.setattr(web_ui, "Storage", lambda *a, **k: Storage(temp_db))
    monkeypatch.setattr(web_ui, "seed_default_sources", _mock_seed)
    monkeypatch.setattr(
        web_ui,
        "create_scheduler_from_storage",
        lambda storage: MagicMock(status=MagicMock()),
    )
    web_ui.scheduler = None
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

    def test_token_differs_across_days(self, client: TestClient, monkeypatch) -> None:
        from src import web_ui

        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-01")
        first = web_ui._csrf_token()
        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-02")
        assert web_ui._csrf_token() != first

    def test_stale_token_rejected_after_rotation(self, client: TestClient, monkeypatch) -> None:
        """A token leaked yesterday must not work today."""
        from src import web_ui

        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-01")
        stale = client.get("/api/csrf-token").json()["csrf_token"]

        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-02")
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": stale},
        )
        assert r.status_code == 403
        assert "CSRF" in r.text

    def test_fresh_token_accepted_after_rotation(self, client: TestClient, monkeypatch) -> None:
        """Rotation must not lock the legitimate client out."""
        from src import web_ui

        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-01")
        client.get("/api/csrf-token")
        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-02")

        fresh = client.get("/api/csrf-token").json()["csrf_token"]
        r = client.post(
            "/language",
            data={"language": "ru"},
            headers={"X-CSRF-Token": fresh},
        )
        assert r.status_code == 200

    def test_token_stable_within_a_day(self, client: TestClient, monkeypatch) -> None:
        """Rotation is per-day, not per-request: one render must not break the next."""
        from src import web_ui

        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-01")
        first = client.get("/api/csrf-token").json()["csrf_token"]
        second = client.get("/api/csrf-token").json()["csrf_token"]
        assert first == second

    def test_derivation_does_not_depend_on_seed_leakage(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Token must be a one-way derivation, not the seed itself."""
        from src import web_ui

        monkeypatch.setattr(web_ui, "_csrf_day", lambda: "2026-01-01")
        assert web_ui._csrf_token() != web_ui._CSRF_SEED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
