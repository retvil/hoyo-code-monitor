"""Unit tests for the sources module."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sources import (
    EXTRACTORS,
    SOURCE_PRESETS,
    CSSExtractor,
    JSONExtractor,
    RegexExtractor,
    SourceConfig,
    SourceFetcher,
    XPathExtractor,
    get_extractor,
    list_presets,
    register_extractor,
    seed_default_sources,
)

if TYPE_CHECKING:
    from src.storage import Storage

#: Same-host inter-start gap asserted in test_fetch_all_enabled_spaces_same_host:
#: the 0.5s configured spacing minus a 0.1s CI-jitter slack.
MIN_INTERVAL_GAP_SLACK: float = 0.4

#: Error count after a single failed fetch (avoids PLR2004 magic value).
EXPECTED_SINGLE_ERROR_COUNT: int = 1


class TestSourceConfig:
    """Tests for SourceConfig dataclass."""

    def test_valid_config(self) -> None:
        config = SourceConfig(
            name="test",
            url="https://example.com",
            selector_type="css",
            selector=".code",
        )
        config.validate()  # Should not raise

    def test_invalid_selector_type_raises(self) -> None:
        config = SourceConfig(
            name="test",
            url="https://example.com",
            selector_type="invalid",
            selector=".code",
        )
        with pytest.raises(ValueError, match="Unknown selector_type"):
            config.validate()

    def test_empty_url_raises(self) -> None:
        config = SourceConfig(
            name="test",
            url="",
            selector_type="css",
            selector=".code",
        )
        with pytest.raises(ValueError, match="url is required"):
            config.validate()

    def test_empty_selector_raises(self) -> None:
        config = SourceConfig(
            name="test",
            url="https://example.com",
            selector_type="css",
            selector="",
        )
        with pytest.raises(ValueError, match="selector is required"):
            config.validate()

    def test_negative_timeout_raises(self) -> None:
        config = SourceConfig(
            name="test",
            url="https://example.com",
            selector_type="css",
            selector=".code",
            timeout_seconds=-1,
        )
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            config.validate()

    def test_negative_rate_limit_raises(self) -> None:
        config = SourceConfig(
            name="test",
            url="https://example.com",
            selector_type="css",
            selector=".code",
            rate_limit_seconds=-1,
        )
        with pytest.raises(ValueError, match="rate_limit_seconds must be non-negative"):
            config.validate()


class TestCSSExtractor:
    """Tests for CSSExtractor."""

    def test_extract_codes_from_html(self) -> None:
        extractor = CSSExtractor()
        html = """
        <html>
            <body>
                <div class="code">GENSHIN123</div>
                <div class="code">STARRAIL456</div>
                <span class="other">not a code</span>
            </body>
        </html>
        """
        codes = extractor.extract(html, ".code")
        assert "GENSHIN123" in codes
        assert "STARRAIL456" in codes
        assert len(codes) == 2  # two .code divs in the fixture HTML

    def test_extract_no_matches(self) -> None:
        extractor = CSSExtractor()
        html = "<html><body><div class='code'>short</div></body></html>"
        codes = extractor.extract(html, ".code")
        assert codes == []

    def test_extract_from_table(self) -> None:
        extractor = CSSExtractor()
        html = "<table><tr><td><code>GENSHIN111</code></td></tr><tr><td><b><code>STARRAIL222</code></b></td></tr></table>"
        codes = extractor.extract(html, "td code")
        assert "GENSHIN111" in codes
        assert "STARRAIL222" in codes


class TestXPathExtractor:
    """Tests for XPathExtractor."""

    def test_extract_codes_from_html(self) -> None:
        extractor = XPathExtractor()
        html = """
        <html>
            <body>
                <div class="code">GENSHIN123</div>
                <div class="code">STARRAIL456</div>
            </body>
        </html>
        """
        codes = extractor.extract(html, "//div[@class='code']")
        assert "GENSHIN123" in codes
        assert "STARRAIL456" in codes

    def test_extract_text_nodes(self) -> None:
        extractor = XPathExtractor()
        html = "<html><body><div>Code: GENSHIN123 here</div></body></html>"
        codes = extractor.extract(html, "//div/text()")
        assert "GENSHIN123" in codes


class TestJSONExtractor:
    """Tests for JSONExtractor."""

    def test_extract_from_json_object(self) -> None:
        extractor = JSONExtractor()
        json_str = '{"codes": ["GENSHIN123", "STARRAIL456"], "other": "data"}'
        codes = extractor.extract(json_str, "codes")
        assert "GENSHIN123" in codes
        assert "STARRAIL456" in codes

    def test_extract_from_nested_json(self) -> None:
        extractor = JSONExtractor()
        json_str = '{"data": {"items": [{"code": "GENSHIN111"}, {"code": "STARRAIL222"}]}}'
        codes = extractor.extract(json_str, "")
        assert "GENSHIN111" in codes
        assert "STARRAIL222" in codes

    def test_extract_from_array(self) -> None:
        extractor = JSONExtractor()
        json_str = '["GENSHIN123", "STARRAIL456", "notacode"]'
        codes = extractor.extract(json_str, "")
        assert "GENSHIN123" in codes
        assert "STARRAIL456" in codes

    def test_extract_active_only(self) -> None:
        extractor = JSONExtractor()
        json_str = '{"active": [{"code": "GENSHIN123"}], "inactive": [{"code": "OLDCODE999"}]}'
        codes = extractor.extract(json_str, "active")
        assert "GENSHIN123" in codes
        assert "OLDCODE999" not in codes

    def test_extract_missing_selector_falls_back(self) -> None:
        extractor = JSONExtractor()
        json_str = '{"active": [{"code": "GENSHIN123"}]}'
        codes = extractor.extract(json_str, "nonexistent.path")
        assert "GENSHIN123" in codes


class TestRegexExtractor:
    """Tests for RegexExtractor."""

    def test_extract_with_pattern(self) -> None:
        extractor = RegexExtractor()
        text = "Code: GENSHIN123 and STARRAIL456 here"
        codes = extractor.extract(text, r"\b[A-Z0-9]{10,}\b")
        assert "GENSHIN123" in codes
        assert "STARRAIL456" in codes

    def test_extract_custom_pattern(self) -> None:
        extractor = RegexExtractor()
        text = "promo-GENSHIN123 promo-STARRAIL456"
        codes = extractor.extract(text, r"promo-([A-Z0-9]+)")
        assert "GENSHIN123" in codes
        assert "STARRAIL456" in codes


class TestExtractorRegistry:
    """Tests for extractor registry."""

    def test_built_in_extractors_exist(self) -> None:
        assert "css" in EXTRACTORS
        assert "xpath" in EXTRACTORS
        assert "json" in EXTRACTORS
        assert "regex" in EXTRACTORS

    def test_register_custom_extractor(self) -> None:
        class CustomExtractor:
            def extract(self, _content: str, _selector: str) -> list[str]:
                return ["custom"]

        register_extractor("custom", CustomExtractor())
        assert get_extractor("custom") is not None
        assert get_extractor("custom").extract("", "") == ["custom"]

    def test_get_nonexistent_extractor(self) -> None:
        assert get_extractor("nonexistent") is None


class TestSourceFetcher:
    """Tests for SourceFetcher."""

    @pytest.fixture
    def source_config(self) -> SourceConfig:
        return SourceConfig(
            name="test",
            url="https://example.com",
            selector_type="css",
            selector=".code",
            timeout_seconds=10,
            rate_limit_seconds=0,
        )

    @pytest.mark.asyncio
    async def test_context_manager(self, storage: Storage) -> None:
        async with SourceFetcher(storage) as fetcher:
            assert fetcher._session is not None

    @pytest.mark.asyncio
    async def test_fetch_with_aiohttp_success(
        self, storage: Storage, source_config: SourceConfig
    ) -> None:
        mock_response = AsyncMock()
        mock_response.text = AsyncMock(
            return_value='<html><div class="code">GENSHIN123</div></html>'
        )
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        async with SourceFetcher(storage, session=mock_session) as fetcher:
            codes = await fetcher.fetch_source(source_config)

        assert "GENSHIN123" in codes
        mock_session.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_http_error(self, storage: Storage, source_config: SourceConfig) -> None:
        import aiohttp

        mock_response = AsyncMock()
        mock_response.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection failed"))
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        async with SourceFetcher(storage, session=mock_session) as fetcher:
            with pytest.raises(aiohttp.ClientError):
                await fetcher.fetch_source(source_config)

    @pytest.mark.asyncio
    async def test_fetch_all_enabled(self, storage: Storage) -> None:
        storage.add_source("source1", "https://example1.com", "css", ".code")
        storage.add_source("source2", "https://example2.com", "css", ".code")
        storage.add_source("source3", "https://example3.com", "css", ".code", enabled=False)

        mock_response = AsyncMock()
        mock_response.text = AsyncMock(
            return_value='<html><div class="code">GENSHIN123</div></html>'
        )
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        async with SourceFetcher(storage, session=mock_session) as fetcher:
            results = await fetcher.fetch_all_enabled()

        assert "source1" in results
        assert "source2" in results
        assert "source3" not in results  # Disabled
        assert mock_session.get.call_count == 2  # only the two enabled sources fetched

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_overlaps_different_hosts(self, storage: Storage) -> None:
        """Unrelated hosts run concurrently instead of waiting sequentially."""
        storage.add_source("one", "https://one.example", "css", ".code", rate_limit_seconds=0)
        storage.add_source("two", "https://two.example", "css", ".code", rate_limit_seconds=0)
        fetcher = SourceFetcher(storage, session=MagicMock())
        started: list[str] = []
        release = asyncio.Event()

        async def fake_fetch(source: SourceConfig) -> list[str]:
            started.append(source.name)
            await release.wait()
            return [source.name]

        fetcher.fetch_source = fake_fetch
        task = asyncio.create_task(fetcher.fetch_all_enabled())
        for _ in range(20):
            if len(started) == 2:  # both hosts have started
                break
            await asyncio.sleep(0)
        assert set(started) == {"one", "two"}
        release.set()
        assert await task == {"one": ["one"], "two": ["two"]}

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_spaces_same_host(self, storage: Storage) -> None:
        """Sources sharing a host keep their configured minimum spacing."""
        storage.add_source("one", "https://same.example/a", "css", ".code", rate_limit_seconds=0.5)
        storage.add_source("two", "https://same.example/b", "css", ".code", rate_limit_seconds=0.5)
        fetcher = SourceFetcher(storage, session=MagicMock())
        starts: list[float] = []
        loop = asyncio.get_running_loop()

        async def fake_fetch(source: SourceConfig) -> list[str]:
            starts.append(loop.time())
            return [source.name]

        fetcher.fetch_source = fake_fetch
        result = await fetcher.fetch_all_enabled()
        assert result == {"one": ["one"], "two": ["two"]}
        assert len(starts) == 2  # both sources started
        # Append order is nondeterministic (two concurrent tasks race to the
        # gate), so sort before asserting the *gap* between the two starts,
        # which is the actual invariant under test: same-host starts are
        # spaced at least the configured min_interval apart. A large interval
        # (0.5s) keeps the assertion far above the noise floor of process-
        # startup / CPU jitter on slow CI runners; the original 0.03s was too
        # tight to be reliable under load. 0.4s leaves the same 0.1s
        # slack (rate_limit_seconds - 0.4 == 0.1) as the original check.
        assert max(starts) - min(starts) >= MIN_INTERVAL_GAP_SLACK

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_failure_isolated(self, storage: Storage) -> None:
        """One failed source returns [] while sibling results survive."""
        storage.add_source("bad", "https://bad.example", "css", ".code", rate_limit_seconds=0)
        storage.add_source("good", "https://good.example", "css", ".code", rate_limit_seconds=0)
        fetcher = SourceFetcher(storage, session=MagicMock())

        async def fake_fetch(source: SourceConfig) -> list[str]:
            if source.name == "bad":
                raise RuntimeError("boom")
            return ["GOODCODE"]

        fetcher.fetch_source = fake_fetch
        result = await fetcher.fetch_all_enabled()
        assert result == {"bad": [], "good": ["GOODCODE"]}

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_failure_increments_error_count(self, storage: Storage) -> None:
        """Regression: a failed fetch must bump ``sources.error_count``.

        The increment used to raise ``OperationalError: no such column:
        error_count`` because no migration created the column. The exception was
        swallowed by the bare ``except Exception`` below, so the counter silently
        stayed at 0 and the ``"error"`` source state in ``/health`` was dead code.
        Asserting on the counter — not just on the returned value — is what keeps
        this from regressing.
        """
        storage.add_source("bad", "https://bad.example", "css", ".code", rate_limit_seconds=0)
        fetcher = SourceFetcher(storage, session=MagicMock())

        async def fake_fetch(_source: SourceConfig) -> list[str]:
            raise RuntimeError("boom")

        fetcher.fetch_source = fake_fetch
        result = await fetcher.fetch_all_enabled()

        assert result == {"bad": []}
        source = storage.get_source("bad")
        assert source is not None
        assert source["error_count"] == EXPECTED_SINGLE_ERROR_COUNT

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_success_does_not_increment_error_count(
        self, storage: Storage
    ) -> None:
        """A healthy fetch must leave the error counter untouched."""
        storage.add_source("good", "https://good.example", "css", ".code", rate_limit_seconds=0)
        fetcher = SourceFetcher(storage, session=MagicMock())

        async def fake_fetch(_source: SourceConfig) -> list[str]:
            return ["GOODCODE"]

        fetcher.fetch_source = fake_fetch
        result = await fetcher.fetch_all_enabled()

        assert result == {"good": ["GOODCODE"]}
        source = storage.get_source("good")
        assert source is not None
        assert source["error_count"] == 0

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_success_records_last_success(self, storage: Storage) -> None:
        """A successful fetch must record a non-NULL last_success timestamp."""
        storage.add_source("good", "https://good.example", "css", ".code", rate_limit_seconds=0)
        assert storage.get_source("good")["last_success"] is None
        fetcher = SourceFetcher(storage, session=MagicMock())

        async def fake_fetch(_source: SourceConfig) -> list[str]:
            return ["GOODCODE"]

        fetcher.fetch_source = fake_fetch
        await fetcher.fetch_all_enabled()

        assert storage.get_source("good")["last_success"] is not None

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_failure_clears_last_success(self, storage: Storage) -> None:
        """A failed fetch must reset last_success to NULL (no stale 'active' state)."""
        storage.add_source("bad", "https://bad.example", "css", ".code", rate_limit_seconds=0)
        storage.mark_source_success("bad")
        assert storage.get_source("bad")["last_success"] is not None

        fetcher = SourceFetcher(storage, session=MagicMock())

        async def failing_fetch(_source: SourceConfig) -> list[str]:
            raise RuntimeError("boom")

        fetcher.fetch_source = failing_fetch
        await fetcher.fetch_all_enabled()

        assert storage.get_source("bad")["last_success"] is None

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_success_clears_stale_error_count(
        self, storage: Storage
    ) -> None:
        """A recovered source must not keep a stale, accumulated error count.

        Simulate a source that failed a few times (high ``error_count``), then
        succeeds on a later call — the success path must call
        ``Storage.clear_source_error`` so the counter resets to 0 instead of
        dragging the dashboard status down to "error" forever.
        """
        storage.add_source("flaky", "https://flaky.example", "css", ".code", rate_limit_seconds=0)

        # Simulate accumulated failures from earlier, now-recovered cycles.
        for _ in range(4):
            storage.increment_source_error("flaky")
        assert storage.get_source("flaky")["error_count"] == 4

        fetcher = SourceFetcher(storage, session=MagicMock())

        async def fake_fetch(_source: SourceConfig) -> list[str]:
            return ["GOODCODE"]

        fetcher.fetch_source = fake_fetch
        result = await fetcher.fetch_all_enabled()

        assert result == {"flaky": ["GOODCODE"]}
        source = storage.get_source("flaky")
        assert source is not None
        # The recovered source must have its stale high error count reset to 0,
        # and a fresh last_success recorded by the same success path.
        assert source["error_count"] == 0
        assert source["last_success"] is not None

    @pytest.mark.asyncio
    async def test_fetch_all_enabled_failure_does_not_clear_error_count(
        self, storage: Storage
    ) -> None:
        """The failure path must not accidentally zero out a real error count."""
        storage.add_source("bad", "https://bad.example", "css", ".code", rate_limit_seconds=0)
        storage.increment_source_error("bad")  # simulate one prior failure
        assert storage.get_source("bad")["error_count"] == 1

        fetcher = SourceFetcher(storage, session=MagicMock())

        async def failing_fetch(_source: SourceConfig) -> list[str]:
            raise RuntimeError("boom")

        fetcher.fetch_source = failing_fetch
        result = await fetcher.fetch_all_enabled()

        assert result == {"bad": []}
        source = storage.get_source("bad")
        assert source is not None
        # Each failure increments the counter; a failure must never clear it.
        assert source["error_count"] == 2

    @pytest.mark.asyncio
    async def test_zero_retries_still_attempts_and_logs_failure(
        self, storage: Storage, source_config: SourceConfig
    ) -> None:
        """A source with max_retries=0 still makes one attempt and raises on failure.

        The failure must surface through the normal error path (aiohttp.ClientError)
        so ``run_one`` in ``fetch_all_enabled`` logs the error and increments the
        source's error counter. Before the fix the retry loop body never executed
        and the function silently returned ``[]`` with no error log.
        """
        import aiohttp

        source_config.max_retries = 0
        source_config.retry_base_delay = 0.0

        mock_response = AsyncMock()
        mock_response.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        async with SourceFetcher(storage, session=mock_session) as fetcher:
            with pytest.raises(aiohttp.ClientError):
                await fetcher.fetch_source(source_config)

        # One attempt was made despite max_retries=0.
        assert mock_session.get.call_count == 1

    @pytest.mark.usefixtures("source_config")
    @pytest.mark.asyncio
    async def test_zero_retries_all_paths_increments_error_count(self, storage: Storage) -> None:
        """``fetch_all_enabled`` with max_retries=0 must still bump the error counter.

        Regression for S4: a 0-retry source that fails on its only attempt must
        surface through the same error path (logger + increment_source_error) as
        a 1-retry source that fails.
        """
        import aiohttp

        storage.add_source(
            "zero",
            "https://zero.example",
            "css",
            ".code",
            max_retries=0,
            retry_base_delay=0.0,
        )
        # Configure the actual aiohttp session so fetch_source runs the real
        # retry loop with max_retries=0 and fails.
        mock_response = AsyncMock()
        mock_response.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)

        async with SourceFetcher(storage, session=mock_session) as fetcher:
            results = await fetcher.fetch_all_enabled()

        assert results == {"zero": []}
        source = storage.get_source("zero")
        assert source is not None
        assert source["error_count"] == EXPECTED_SINGLE_ERROR_COUNT


class TestSeedDefaultSources:
    """Tests for seeding default sources."""

    @pytest.mark.asyncio
    async def test_seed_creates_sources(self, storage: Storage) -> None:
        count = await seed_default_sources(storage)
        assert count == len(SOURCE_PRESETS)

        sources = storage.list_sources()
        names = {s["name"] for s in sources}
        for preset in list_presets():
            assert preset in names

    @pytest.mark.asyncio
    async def test_seed_idempotent(self, storage: Storage) -> None:
        await seed_default_sources(storage)
        count = await seed_default_sources(storage)
        assert count == 0  # No new sources added

    @pytest.mark.asyncio
    async def test_seed_skips_existing_url(self, storage: Storage) -> None:
        # Legacy installs use old names for the same URLs — no duplicates.
        storage.add_source(
            "wiki",
            "https://genshin-impact.fandom.com/wiki/Promotional_Code",
            "css",
            "code",
        )
        count = await seed_default_sources(storage)
        urls = [s["url"] for s in storage.list_sources()]
        assert len(urls) == len(set(urls))
        assert count == len(SOURCE_PRESETS) - 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
