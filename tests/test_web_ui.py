"""Smoke tests for the FastAPI Web UI (isolated temp DB)."""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.storage import Storage


@pytest.fixture
def temp_db() -> str:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    for ext in ("", "-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            Path(db_path + ext).unlink(missing_ok=True)


@pytest.fixture
def client(temp_db: str, monkeypatch) -> TestClient:
    from src import (
        web_ui,
    )
    from src.scheduler import (
        SchedulerStatus,
    )
    from src.web import app as web_app
    from src.web.routers import accounts, checkin, codes, sources, system

    async def _mock_seed(*_args, **_kwargs):
        return None

    def _mock_storage(*_a, **_k):
        return Storage(temp_db)

    for _mod in (sources, accounts, codes, checkin, system):
        monkeypatch.setattr(_mod, "Storage", _mock_storage)
    monkeypatch.setattr(web_app, "seed_default_sources", _mock_seed)
    monkeypatch.setattr(
        web_app,
        "create_scheduler_from_storage",
        lambda _storage: __import__("unittest.mock").MagicMock(status=SchedulerStatus()),
    )
    web_app.scheduler = None
    return TestClient(web_ui.app, raise_server_exceptions=False)


class TestPages:
    @pytest.mark.parametrize("path", ["/", "/sources", "/accounts", "/config", "/author"])
    def test_pages_ok(self, client: TestClient, path: str) -> None:
        r = client.get(path)
        assert r.status_code == 200, path

    def test_health(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] in ("healthy", "degraded")

    def test_metrics(self, client: TestClient) -> None:
        # /metrics was removed in the router-based refactor (Prometheus step deferred).
        assert client.get("/metrics").status_code == 404

    @pytest.mark.parametrize(
        "path",
        [
            "/partials/scheduler-status",
            "/partials/stats",
            "/partials/recent-codes",
            "/partials/recent-logs",
            "/partials/health",
        ],
    )
    def test_partials_ok(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 200


class TestSourcesApi:
    def test_add_list_delete(self, client: TestClient) -> None:
        r = client.post(
            "/sources",
            data={
                "name": "t1",
                "url": "https://example.com",
                "selector_type": "css",
                "selector": ".x",
            },
        )
        assert r.status_code == 200
        assert "t1" in client.get("/sources").text
        assert client.delete("/sources/t1").status_code == 200
        assert client.delete("/sources/t1").status_code == 404

    def test_enable_disable(self, client: TestClient) -> None:
        client.post(
            "/sources",
            data={
                "name": "t2",
                "url": "https://example.com",
                "selector_type": "css",
                "selector": ".x",
            },
        )
        assert client.post("/sources/t2/disable").status_code == 200
        assert client.post("/sources/t2/enable").status_code == 200

    def test_unknown_source(self, client: TestClient) -> None:
        assert client.post("/sources/nope/test").status_code == 404


class TestAccountsApi:
    def test_add_cookies_delete(self, client: TestClient) -> None:
        assert (
            client.post(
                "/accounts", data={"name": "a1", "uid": "1", "region": "os_usa"}
            ).status_code
            == 200
        )
        r = client.post("/accounts/a1/cookies", data={"cookies": '{"ltuid": "1", "ltoken": "x"}'})
        assert r.status_code == 200
        r = client.get("/accounts/a1/cookies")
        assert r.status_code == 200
        assert "ltoken" in r.text
        assert "secret" not in r.text
        assert client.delete("/accounts/a1").status_code == 200

    def test_bad_cookies_json(self, client: TestClient) -> None:
        client.post("/accounts", data={"name": "a2", "uid": "2", "region": "os_usa"})
        assert client.post("/accounts/a2/cookies", data={"cookies": "not json"}).status_code == 400

    def test_redeem_toggle(self, client: TestClient) -> None:
        client.post("/accounts", data={"name": "a3", "uid": "3", "region": "os_usa"})
        assert "badge-bad" in client.get("/accounts/a3/redeem-state").text
        assert "badge-ok" in client.post("/accounts/a3/redeem/toggle").text
        assert "badge-bad" in client.post("/accounts/a3/redeem/toggle").text


class TestCheckinsApi:
    def test_checkins_page_and_partials(self, client: TestClient) -> None:
        assert client.get("/checkins").status_code == 200
        assert client.get("/partials/checkin-logs").status_code == 200
        assert client.get("/partials/checkin-progress").status_code == 200
        assert client.get("/api/checkins/status").status_code == 200
        assert client.get("/api/checkins/progress").status_code == 200

    def test_checkin_toggle(self, client: TestClient) -> None:
        assert (
            client.post(
                "/accounts", data={"name": "ca", "uid": "4", "region": "os_usa"}
            ).status_code
            == 200
        )
        assert "badge-ok" in client.get("/accounts/ca/checkin-state").text
        assert "badge-bad" in client.post("/accounts/ca/checkin/toggle").text
        assert "badge-ok" in client.post("/accounts/ca/checkin/toggle").text
        assert client.get("/accounts/nope/checkin-state").status_code == 404
        assert client.post("/accounts/nope/checkin/toggle").status_code == 404

    def test_checkin_settings_validation(self, client: TestClient) -> None:
        valid = {
            "checkin_enabled": "true",
            "checkin_time": "05:30",
            "checkin_jitter_minutes": "10",
        }
        assert client.post("/checkins/settings", data=valid).status_code == 200
        assert (
            client.post(
                "/checkins/settings",
                data={**valid, "checkin_time": "25:99"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/checkins/settings",
                data={**valid, "checkin_jitter_minutes": "121"},
            ).status_code
            == 400
        )


class TestImportExportApi:
    def test_export_import_round_trip(self, client: TestClient, temp_db: str) -> None:
        source = Storage(temp_db)
        source.add_code("EXPORTED1", "backup", game="hsr")
        payload = client.get("/export").json()
        assert payload["app"] == "genshin-code-monitor"
        assert payload["codes"][0]["code"] == "EXPORTED1"

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            target_db = tmp.name
        try:
            from src.web.routers import codes

            original_storage = codes.Storage
            codes.Storage = lambda *_a, **_k: Storage(target_db)
            imported = client.post("/import", data={"payload": json.dumps(payload)})
            assert imported.status_code == 200
            assert "Imported 1" in imported.json()["result"]
            assert Storage(target_db).get_code("EXPORTED1", game="hsr") is not None
        finally:
            codes.Storage = original_storage
            for suffix in ("", "-wal", "-shm", "-journal"):
                with contextlib.suppress(OSError):
                    Path(target_db + suffix).unlink(missing_ok=True)

    def test_import_rejects_invalid_json(self, client: TestClient) -> None:
        response = client.post("/import", data={"payload": "not-json"})
        assert response.status_code == 400


class TestHealthAndSourceStatus:
    def test_health_reports_component_shape(self, client: TestClient) -> None:
        payload = client.get("/health").json()
        assert {"status", "database", "scheduler", "sources", "connectivity"} <= payload.keys()
        assert payload["database"] == "ok"
        assert "state" in payload["scheduler"]
        assert "count" in payload["sources"]

    def test_sources_status_uses_error_count(self, client: TestClient, temp_db: str) -> None:
        source = Storage(temp_db)
        source.add_source("failing", "https://example.com", "css", ".code")
        for _ in range(4):
            source.increment_source_error("failing")
        payload = client.get("/api/sources/status").json()
        assert payload[0]["status"] == "error"


class TestMiscApi:
    def test_language(self, client: TestClient) -> None:
        assert client.post("/language", data={"language": "ru"}).status_code == 200
        assert "Дашборд" in client.get("/").text
        assert client.post("/language", data={"language": "xx"}).status_code == 400
        client.post("/language", data={"language": "en"})

    def test_author_qr(self, client: TestClient) -> None:
        r = client.get("/author/qr?kind=bitcoin")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert client.get("/author/qr?kind=nosuchcoin").status_code == 200  # falls back to bitcoin

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

    def test_sources_status_tolerates_bad_timestamp(self, client: TestClient, temp_db: str) -> None:
        s = Storage(temp_db)
        s.add_source("t1", "https://example.com", "css", ".code")
        with s._connection() as conn:
            conn.execute("UPDATE sources SET last_checked = 'not-a-date' WHERE name = 't1'")
            conn.commit()
        r = client.get("/api/sources/status")
        assert r.status_code == 200
        assert r.json()[0]["status"] == "idle"

    def test_redeem_single_mocked(self, client: TestClient, temp_db: str) -> None:
        from src.redeemer import (
            RedemptionResult,
        )

        s = Storage(temp_db)
        s.add_account("ra", "1", "os_usa")
        s.set_account_redeem("ra", True)
        s.store_account_cookies("ra", {"ltuid": "1", "ltoken": "x"})
        s.add_code("MOCKCODE1", "t1")

        mock_redeemer = AsyncMock()
        mock_redeemer.redeem_code = AsyncMock(
            return_value=RedemptionResult(
                success=True, reward="R", message="OK", raw_response={"retcode": 0}
            )
        )
        mock_redeemer.__aenter__ = AsyncMock(return_value=mock_redeemer)
        mock_redeemer.__aexit__ = AsyncMock(return_value=None)
        with patch("src.redeemer.Redeemer", return_value=mock_redeemer):
            r = client.post("/codes/MOCKCODE1/redeem")
        assert r.status_code == 200
        assert Storage(temp_db).get_code("MOCKCODE1")["redeemed"] == 1


class TestXssEscaping:
    """Regression: user-supplied names/cookie values must be escaped in HTML responses."""

    def test_source_name_with_script_tag_is_escaped(self, client: TestClient, temp_db: str) -> None:
        """A source name containing a script tag must not appear unescaped on the /sources page.

        Guards the audit finding that reflected user input in Jinja templates was
        escaped (autoescape is on for .html). If a future refactor switches to
        raw/unsafe rendering, this test will catch it.
        """
        s = Storage(temp_db)
        s.add_source(
            "<script>alert(1)</script>",
            "https://example.com",
            "css",
            ".code",
        )
        r = client.get("/sources")
        assert r.status_code == 200
        assert "<script>alert(1)</script>" not in r.text
        # The escaped form must be present (proves it was escaped, not deleted)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text

    def test_cookie_value_with_script_tag_is_escaped(
        self, client: TestClient, temp_db: str
    ) -> None:
        """Cookie names/values containing script tags must not appear unescaped
        in the /accounts/{name}/cookies response."""
        s = Storage(temp_db)
        s.add_account("cookie_xss", "9", "os_usa")
        s.store_account_cookies("cookie_xss", {"<script>alert(2)</script>": "value"})
        r = client.get("/accounts/cookie_xss/cookies")
        assert r.status_code == 200
        assert "<script>alert(2)</script>" not in r.text
        assert "&lt;script&gt;alert(2)&lt;/script&gt;" in r.text

    def test_cookie_value_with_script_tag_shows_masked_escaped(
        self, client: TestClient, temp_db: str
    ) -> None:
        """Long cookie values are masked, but the mask result must still be escaped."""
        s = Storage(temp_db)
        s.add_account("cookie_mask", "9", "os_usa")
        malicious_long_value = "A" * 50 + "<script>alert(3)</script>"
        s.store_account_cookies("cookie_mask", {"longkey": malicious_long_value})
        r = client.get("/accounts/cookie_mask/cookies")
        assert r.status_code == 200
        # The raw value must not appear in the HTML response
        assert "<script>alert(3)</script>" not in r.text


class TestImportGameData:
    """Regression: import_data must reject items with unknown game ids."""

    def test_import_skips_invalid_game(self, client: TestClient, temp_db: str) -> None:
        """A code whose game field is not in GAMES is skipped, not imported."""
        payload = {
            "app": "genshin-code-monitor",
            "version": 1,
            "codes": [
                {"code": "INVALIDGAME1", "game": "unknown_game", "sources": ["test"]},
            ],
        }
        r = client.post("/import", data={"payload": json.dumps(payload)})
        assert r.status_code == 200
        assert "Imported 0, skipped 1" in r.json()["result"]
        assert Storage(temp_db).get_code("INVALIDGAME1") is None

    def test_import_accepts_valid_game(self, client: TestClient, temp_db: str) -> None:
        """A code with game='hsr' is imported normally."""
        payload = {
            "app": "genshin-code-monitor",
            "version": 1,
            "codes": [
                {"code": "VALIDHSR1", "game": "hsr", "sources": ["test"]},
            ],
        }
        r = client.post("/import", data={"payload": json.dumps(payload)})
        assert r.status_code == 200
        assert "Imported 1, skipped 0" in r.json()["result"]
        assert Storage(temp_db).get_code("VALIDHSR1", game="hsr") is not None

    def test_redeem_all_no_pending_codes(self, client: TestClient, temp_db: str) -> None:
        """POST /redeem/all with no pending codes returns 'Nothing to redeem'."""
        s = Storage(temp_db)
        s.add_account("ra", "1", "os_usa")
        s.set_account_redeem("ra", True)
        s.add_code("CLAIMED1", "t1")
        s.update_code_redemption("CLAIMED1", redeemed=True)

        r = client.post("/redeem/all")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "Nothing to redeem" in body["result"]

    def test_redeem_all_no_accounts(self, client: TestClient, temp_db: str) -> None:
        """POST /redeem/all with no accounts returns 400."""
        s = Storage(temp_db)
        s.add_code("CODE1", "t1")

        r = client.post("/redeem/all")
        assert r.status_code == 400

    def test_redeem_all_htmx_fragment(self, client: TestClient, temp_db: str) -> None:
        """HTMX request to /redeem/all returns a styled span fragment."""
        from src.redeemer import RedemptionResult

        s = Storage(temp_db)
        s.add_account("ra", "1", "os_usa")
        s.set_account_redeem("ra", True)
        s.store_account_cookies("ra", {"ltuid": "1", "ltoken": "x"})
        s.add_code("PENDING1", "t1")

        # redeem_all filters list_codes(only_unredeemed=True) by display_status.
        # Mock list_codes to return a row with display_status="pending".
        fake_row = {"code": "PENDING1", "game": "genshin", "display_status": "pending"}
        with patch.object(Storage, "list_codes", return_value=[fake_row]):
            mock_redeemer = AsyncMock()
            mock_redeemer.redeem_code = AsyncMock(
                return_value=RedemptionResult(
                    success=True,
                    reward="100 Primogems",
                    message="OK",
                    raw_response={"retcode": 0},
                )
            )
            mock_redeemer.__aenter__ = AsyncMock(return_value=mock_redeemer)
            mock_redeemer.__aexit__ = AsyncMock(return_value=None)
            with patch("src.redeemer.Redeemer", return_value=mock_redeemer):
                r = client.post("/redeem/all", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "redeem-result-ok" in r.text

    def test_redeem_single_htmx_fragment(self, client: TestClient, temp_db: str) -> None:
        """HTMX request to /codes/{code}/redeem returns styled span."""
        from src.redeemer import RedemptionResult

        s = Storage(temp_db)
        s.add_account("ra", "1", "os_usa")
        s.set_account_redeem("ra", True)
        s.store_account_cookies("ra", {"ltuid": "1", "ltoken": "x"})
        s.add_code("MOCKCODE2", "t1")

        mock_redeemer = AsyncMock()
        mock_redeemer.redeem_code = AsyncMock(
            return_value=RedemptionResult(
                success=True,
                reward="R",
                message="OK",
                raw_response={"retcode": 0},
            )
        )
        mock_redeemer.__aenter__ = AsyncMock(return_value=mock_redeemer)
        mock_redeemer.__aexit__ = AsyncMock(return_value=None)
        with patch("src.redeemer.Redeemer", return_value=mock_redeemer):
            r = client.post("/codes/MOCKCODE2/redeem", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "redeem-result-ok" in r.text

    def test_redeem_single_propagates_api_error_message(
        self, client: TestClient, temp_db: str
    ) -> None:
        """When the API returns an error, the actual message must reach the UI.

        Regression: the router previously hardcoded 'error found' instead of
        forwarding the API response message, making every failure look
        identical and hiding the real cause (expired code, already claimed,
        server error, etc.).
        """
        from src.redeemer import RedemptionResult

        s = Storage(temp_db)
        s.add_account("ra", "1", "os_usa")
        s.set_account_redeem("ra", True)
        s.store_account_cookies("ra", {"ltuid": "1", "ltoken": "x"})
        s.add_code("EXPIRED1", "t1")

        mock_redeemer = AsyncMock()
        mock_redeemer.redeem_code = AsyncMock(
            return_value=RedemptionResult(
                success=False,
                reward="",
                message="This code has expired",
                raw_response={"retcode": -2001, "message": "This code has expired"},
            )
        )
        mock_redeemer.__aenter__ = AsyncMock(return_value=mock_redeemer)
        mock_redeemer.__aexit__ = AsyncMock(return_value=None)
        with patch("src.redeemer.Redeemer", return_value=mock_redeemer):
            r = client.post("/codes/EXPIRED1/redeem", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert "This code has expired" in r.text
        assert "error found" not in r.text


class TestBrowserProfileCollision:
    """Regression C-2: per-account profile dirs must not collide."""

    def test_two_accounts_get_different_profile_dirs(self) -> None:
        from src.cookies_login import profile_dir

        a = profile_dir("account-a")
        b = profile_dir("account-b")
        assert a != b

    def test_profile_dir_contains_slug(self) -> None:
        from src.cookies_login import profile_dir

        d = profile_dir("my-game-account")
        assert "my-game-account" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
