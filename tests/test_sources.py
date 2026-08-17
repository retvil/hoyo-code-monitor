"""Unit tests for the sources module."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sources import (
    EXTRACTORS,
    CSSExtractor,
    JSONExtractor,
    RegexExtractor,
    SourceConfig,
    SourceFetcher,
    XPathExtractor,
    create_default_sources,
    get_extractor,
    register_extractor,
    seed_default_sources,
)
from src.storage import Storage


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
        assert len(codes) == 2

    def test_extract_no_matches(self) -> None:
        extractor = CSSExtractor()
        html = "<html><body><div class='code'>short</div></body></html>"
        codes = extractor.extract(html, ".code")
        assert codes == []

    def test_extract_from_table(self) -> None:
        extractor = CSSExtractor()
        html = '<table><tr><td><code>GENSHIN111</code></td></tr><tr><td><b><code>STARRAIL222</code></b></td></tr></table>'
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
            def extract(self, content: str, selector: str) -> list[str]:
                return ["custom"]

        register_extractor("custom", CustomExtractor())
        assert get_extractor("custom") is not None
        assert get_extractor("custom").extract("", "") == ["custom"]

    def test_get_nonexistent_extractor(self) -> None:
        assert get_extractor("nonexistent") is None


class TestCreateDefaultSources:
    """Tests for default source creation."""

    def test_creates_expected_sources(self) -> None:
        sources = create_default_sources()
        assert len(sources) >= 2
        names = {s.name for s in sources}
        assert "wiki" in names
        assert "wiki_api" in names

    def test_sources_have_required_fields(self) -> None:
        sources = create_default_sources()
        for source in sources:
            assert source.name
            assert source.url
            assert source.selector_type
            assert source.selector
            source.validate()  # Should not raise


class TestSourceFetcher:
    """Tests for SourceFetcher."""

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
    async def test_fetch_with_aiohttp_success(self, storage: Storage, source_config: SourceConfig) -> None:
        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value='<html><div class="code">GENSHIN123</div></html>')
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
        mock_response.text = AsyncMock(return_value='<html><div class="code">GENSHIN123</div></html>')
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
        assert mock_session.get.call_count == 2


class TestSeedDefaultSources:
    """Tests for seeding default sources."""

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
    async def test_seed_creates_sources(self, storage: Storage) -> None:
        count = await seed_default_sources(storage)
        assert count >= 2

        sources = storage.list_sources()
        names = {s["name"] for s in sources}
        assert "wiki" in names
        assert "wiki_api" in names

    @pytest.mark.asyncio
    async def test_seed_idempotent(self, storage: Storage) -> None:
        await seed_default_sources(storage)
        count = await seed_default_sources(storage)
        assert count == 0  # No new sources added


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
