"""Smoke tests for the FastAPI Web UI (isolated temp DB)."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.storage import Storage


@pytest.fixture()
def temp_db() -> str:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    for ext in ("", "-wal", "-shm", "-journal"):
        try:
            os.unlink(db_path + ext)
        except OSError:
            pass


@pytest.fixture()
def client(temp_db: str, monkeypatch) -> TestClient:
    import src.web_ui as web_ui

    monkeypatch.setattr(web_ui, "Storage", lambda *a, **k: Storage(temp_db))
    web_ui.scheduler = None
    return TestClient(web_ui.app, raise_server_exceptions=False)


class TestPages:
    @pytest.mark.parametrize("path", ["/", "/sources", "/accounts", "/config", "/author"])
    def test_pages_ok(self, client: TestClient, path: str) -> None:
        r = client.get(path)
        assert r.status_code == 200, path

    def test_health(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_metrics(self, client: TestClient) -> None:
        r = client.get("/metrics")
        assert r.status_code in (200, 503)

    @pytest.mark.parametrize(
        "path",
        ["/partials/scheduler-status", "/partials/stats", "/partials/recent-codes", "/partials/recent-logs", "/partials/health"],
    )
    def test_partials_ok(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 200


class TestSourcesApi:
    def test_add_list_delete(self, client: TestClient) -> None:
        r = client.post(
            "/sources",
            data={"name": "t1", "url": "https://example.com", "selector_type": "css", "selector": ".x"},
        )
        assert r.status_code == 200
        assert "t1" in client.get("/sources").text
        assert client.delete("/sources/t1").status_code == 200
        assert client.delete("/sources/t1").status_code == 404

    def test_enable_disable(self, client: TestClient) -> None:
        client.post("/sources", data={"name": "t2", "url": "https://example.com", "selector_type": "css", "selector": ".x"})
        assert client.post("/sources/t2/disable").status_code == 200
        assert client.post("/sources/t2/enable").status_code == 200

    def test_unknown_source(self, client: TestClient) -> None:
        assert client.post("/sources/nope/test").status_code == 404


class TestAccountsApi:
    def test_add_cookies_delete(self, client: TestClient) -> None:
        assert client.post("/accounts", data={"name": "a1", "uid": "1", "region": "os_usa"}).status_code == 200
        r = client.post("/accounts/a1/cookies", data={"cookies": '{"ltuid": "1", "ltoken": "x"}'})
        assert r.status_code == 200
        r = client.get("/accounts/a1/cookies")
        assert r.status_code == 200
        assert "ltoken" in r.text and "secret" not in r.text
        assert client.delete("/accounts/a1").status_code == 200

    def test_bad_cookies_json(self, client: TestClient) -> None:
        client.post("/accounts", data={"name": "a2", "uid": "2", "region": "os_usa"})
        assert client.post("/accounts/a2/cookies", data={"cookies": "not json"}).status_code == 400

    def test_redeem_toggle(self, client: TestClient) -> None:
        client.post("/accounts", data={"name": "a3", "uid": "3", "region": "os_usa"})
        assert "badge-bad" in client.get("/accounts/a3/redeem-state").text
        assert "badge-ok" in client.post("/accounts/a3/redeem/toggle").text
        assert "badge-bad" in client.post("/accounts/a3/redeem/toggle").text


class TestMiscApi:
    def test_language(self, client: TestClient) -> None:
        assert client.post("/language", data={"language": "ru"}).status_code == 200
        assert "Дашборд" in client.get("/").text
        assert client.post("/language", data={"language": "xx"}).status_code == 400
        client.post("/language", data={"language": "en"})

    def test_author_qr_missing(self, client: TestClient) -> None:
        assert client.get("/author/qr?kind=bitcoin").status_code == 404

    def test_codes_crud(self, client: TestClient, temp_db: str) -> None:
        s = Storage(temp_db)
        s.add_code("TESTCODE1", "t1")
        assert client.delete("/codes/TESTCODE1").status_code == 200
        assert client.delete("/codes/TESTCODE1").status_code == 404

    def test_cleanup(self, client: TestClient) -> None:
        r = client.post("/codes/cleanup")
        assert r.status_code == 200
        assert "Removed" in r.text

    def test_redeem_no_accounts(self, client: TestClient) -> None:
        assert client.post("/codes/NOPE/redeem").status_code in (400, 404)

    def test_redeem_single_mocked(self, client: TestClient, temp_db: str) -> None:
        from src.redeemer import RedemptionResult

        s = Storage(temp_db)
        s.add_account("ra", "1", "os_usa")
        s.set_account_redeem("ra", True)
        s.store_account_cookies("ra", {"ltuid": "1", "ltoken": "x"})
        s.add_code("MOCKCODE1", "t1")

        mock_redeemer = AsyncMock()
        mock_redeemer.redeem_code = AsyncMock(
            return_value=RedemptionResult(success=True, reward="R", message="OK", raw_response={"retcode": 0})
        )
        mock_redeemer.__aenter__ = AsyncMock(return_value=mock_redeemer)
        mock_redeemer.__aexit__ = AsyncMock(return_value=None)
        with patch("src.redeemer.Redeemer", return_value=mock_redeemer):
            r = client.post("/codes/MOCKCODE1/redeem")
        assert r.status_code == 200
        assert Storage(temp_db).get_code("MOCKCODE1")["redeemed"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
