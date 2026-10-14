"""Unit tests for the read-only GitHub Releases version check."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src import version_check
from src.version_check import (
    check_for_update,
    is_newer,
    parse_version,
    reset_cache,
)


@pytest.fixture(autouse=True)
def clean_cache():
    reset_cache()
    yield
    reset_cache()


class TestParseVersion:
    """Version parsing and comparison semantics."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.2.3", (1, 2, 3)),
            ("v1.2.3", (1, 2, 3)),
            ("1.2.3-beta.4", (1, 2, 3)),
            ("1", (1,)),
            ("", ()),
            ("garbage", (0,)),
        ],
    )
    def test_parse(self, raw: str, expected: tuple[int, ...]) -> None:
        assert parse_version(raw) == expected

    @pytest.mark.parametrize(
        ("latest", "current", "expected"),
        [
            ("1.2.3", "1.2.2", True),
            ("v1.2.3", "1.2.2", True),
            ("1.2.2", "1.2.2", False),
            ("1.2", "1.2.0", False),
            ("1.1.99", "1.2.0", False),
        ],
    )
    def test_is_newer(self, latest: str, current: str, expected: bool) -> None:
        assert is_newer(latest, current) is expected


class TestCheckForUpdate:
    """Network behavior, caching, and failure silence."""

    @pytest.mark.asyncio
    async def test_newer_release_returns_info(self, monkeypatch) -> None:
        payload = {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/example/release",
            "body": "New features",
            "prerelease": False,
        }
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=payload)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(version_check, "get_session", lambda: session)
        monkeypatch.setattr(version_check, "APP_VERSION", "1.0.0")

        result = await check_for_update(force=True)

        assert result is not None
        assert result.latest_version == "9.9.9"
        assert result.url == payload["html_url"]
        assert session.get.call_count == 1

    @pytest.mark.asyncio
    async def test_equal_release_returns_none(self, monkeypatch) -> None:
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={"tag_name": "v1.2.2", "prerelease": False})
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock(get=MagicMock(return_value=response))
        monkeypatch.setattr(version_check, "get_session", lambda: session)
        monkeypatch.setattr(version_check, "APP_VERSION", "1.2.2")

        assert await check_for_update(force=True) is None

    @pytest.mark.asyncio
    async def test_prerelease_hidden_for_stable_build(self, monkeypatch) -> None:
        response = MagicMock(status=200)
        response.json = AsyncMock(
            return_value={"tag_name": "v1.3.0-beta.1", "prerelease": True}
        )
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock(get=MagicMock(return_value=response))
        monkeypatch.setattr(version_check, "get_session", lambda: session)
        monkeypatch.setattr(version_check, "APP_VERSION", "1.2.2")

        assert await check_for_update(force=True) is None

    @pytest.mark.asyncio
    async def test_network_failure_is_silent(self, monkeypatch) -> None:
        session = MagicMock()
        session.get.side_effect = RuntimeError("offline")
        monkeypatch.setattr(version_check, "get_session", lambda: session)

        assert await check_for_update(force=True) is None

    @pytest.mark.asyncio
    async def test_non_200_is_silent(self, monkeypatch) -> None:
        response = MagicMock(status=503)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock(get=MagicMock(return_value=response))
        monkeypatch.setattr(version_check, "get_session", lambda: session)

        assert await check_for_update(force=True) is None

    @pytest.mark.asyncio
    async def test_cache_avoids_second_request(self, monkeypatch) -> None:
        response = MagicMock(status=200)
        response.json = AsyncMock(
            return_value={"tag_name": "v9.9.9", "html_url": "https://x", "prerelease": False}
        )
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock(get=MagicMock(return_value=response))
        monkeypatch.setattr(version_check, "get_session", lambda: session)
        monkeypatch.setattr(version_check, "APP_VERSION", "1.0.0")

        first = await check_for_update()
        second = await check_for_update()

        assert first is not None
        assert second == first
        assert session.get.call_count == 1

    @pytest.mark.asyncio
    async def test_release_notes_are_trimmed(self, monkeypatch) -> None:
        response = MagicMock(status=200)
        response.json = AsyncMock(
            return_value={
                "tag_name": "v9.9.9",
                "html_url": "https://x",
                "body": "line 1\n\nline 2" + "x" * 1000,
                "prerelease": False,
            }
        )
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock(get=MagicMock(return_value=response))
        monkeypatch.setattr(version_check, "get_session", lambda: session)
        monkeypatch.setattr(version_check, "APP_VERSION", "1.0.0")

        result = await check_for_update(force=True)

        assert result is not None
        assert len(result.release_notes) <= version_check.MAX_NOTES_CHARS
        assert "\n" not in result.release_notes
