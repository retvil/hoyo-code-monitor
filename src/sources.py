"""Source registry and HTTP fetchers for Genshin code monitor.

Provides pluggable source configuration and extraction strategies.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import aiohttp
from bs4 import BeautifulSoup

from src.storage import Storage

logger = logging.getLogger(__name__)


class Extractor(Protocol):
    """Protocol for code extractors."""

    def extract(self, content: str, selector: str) -> list[str]:
        """Extract codes from content using selector."""
        ...


class CSSExtractor:
    """Extract codes using CSS selectors."""

    def extract(self, content: str, selector: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        elements = soup.select(selector)
        codes = []
        for el in elements:
            text = el.get_text(strip=True)
            matches = re.findall(r"\b[A-Z0-9]{10,}\b", text)
            codes.extend(matches)
        return codes


class XPathExtractor:
    """Extract codes using XPath selectors (via lxml)."""

    def extract(self, content: str, selector: str) -> list[str]:
        from lxml import html

        tree = html.fromstring(content)
        elements = tree.xpath(selector)
        codes = []
        for el in elements:
            if isinstance(el, str):
                text = el
            else:
                text = el.text_content() if hasattr(el, "text_content") else str(el)
            matches = re.findall(r"\b[A-Z0-9]{10,}\b", text)
            codes.extend(matches)
        return codes


class JSONExtractor:
    """Extract codes from JSON using JSONPath-like selectors."""

    def extract(self, content: str, selector: str) -> list[str]:
        import json

        data = json.loads(content)
        codes = []

        def find_codes(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    find_codes(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    find_codes(v, f"{path}[{i}]")
            elif isinstance(obj, str):
                matches = re.findall(r"\b[A-Z0-9]{10,}\b", obj)
                codes.extend(matches)

        find_codes(data)
        return codes


class RegexExtractor:
    """Extract codes using regex pattern."""

    def extract(self, content: str, selector: str) -> list[str]:
        pattern = re.compile(selector)
        return pattern.findall(content)


EXTRACTORS: dict[str, Extractor] = {
    "css": CSSExtractor(),
    "xpath": XPathExtractor(),
    "json": JSONExtractor(),
    "regex": RegexExtractor(),
}


@dataclass
class SourceConfig:
    """Configuration for a code source."""

    name: str
    url: str
    selector_type: str  # css, xpath, json, regex
    selector: str
    enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30
    rate_limit_seconds: float = 1.0
    requires_browser: bool = False
    browser_wait_selector: str | None = None
    browser_wait_seconds: int = 5
    max_retries: int = 3
    retry_base_delay: float = 1.0

    def validate(self) -> None:
        """Validate source configuration."""
        if self.selector_type not in EXTRACTORS:
            raise ValueError(f"Unknown selector_type: {self.selector_type}")
        if not self.url:
            raise ValueError("url is required")
        if not self.selector:
            raise ValueError("selector is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.rate_limit_seconds < 0:
            raise ValueError("rate_limit_seconds must be non-negative")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_base_delay <= 0:
            raise ValueError("retry_base_delay must be positive")


class SourceFetcher:
    """Fetches and extracts codes from configured sources."""

    def __init__(
        self,
        storage: Storage,
        session: aiohttp.ClientSession | None = None,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    ):
        self.storage = storage
        self._session = session
        self._own_session = session is None
        self.user_agent = user_agent
        self._browser = None

    async def __aenter__(self) -> SourceFetcher:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self.user_agent},
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._own_session and self._session:
            await self._session.close()
            self._session = None
        if self._browser:
            await self._browser.close()
            self._browser = None

    async def _get_browser(self):
        """Lazy-initialize Playwright browser."""
        if self._browser is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def fetch_source(self, source: SourceConfig) -> list[str]:
        """Fetch and extract codes from a single source."""
        if source.requires_browser:
            return await self._fetch_with_browser(source)
        return await self._fetch_with_aiohttp(source)

    async def _fetch_with_aiohttp(self, source: SourceConfig) -> list[str]:
        """Fetch using aiohttp with exponential backoff retry."""
        if not self._session:
            raise RuntimeError("Session not initialized. Use async context manager.")

        headers = {"User-Agent": self.user_agent}
        headers.update(source.headers)

        max_retries = getattr(source, "max_retries", 3)
        base_delay = getattr(source, "retry_base_delay", 1.0)

        for attempt in range(max_retries):
            try:
                async with self._session.get(source.url, headers=headers) as response:
                    response.raise_for_status()
                    content = await response.text()

                extractor = EXTRACTORS[source.selector_type]
                codes = extractor.extract(content, source.selector)

                logger.info(
                    "Fetched %d codes from %s (%s)",
                    len(codes),
                    source.name,
                    source.selector_type,
                )
                return codes

            except aiohttp.ClientError as e:
                if attempt == max_retries - 1:
                    logger.error("HTTP error fetching %s after %d retries: %s", source.name, max_retries, e)
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning("Fetch attempt %d/%d failed for %s: %s. Retrying in %.1fs",
                               attempt + 1, max_retries, source.name, e, delay)
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error("Error extracting from %s: %s", source.name, e)
                raise

    async def _fetch_with_browser(self, source: SourceConfig) -> list[str]:
        """Fetch using Playwright for JS-rendered content."""
        browser = await self._get_browser()
        page = await browser.new_page()

        try:
            await page.goto(source.url, wait_until="networkidle", timeout=source.timeout_seconds * 1000)

            if source.browser_wait_selector:
                await page.wait_for_selector(source.browser_wait_selector, timeout=source.browser_wait_seconds * 1000)
            else:
                await asyncio.sleep(source.browser_wait_seconds)

            content = await page.content()

            extractor = EXTRACTORS[source.selector_type]
            codes = extractor.extract(content, source.selector)

            logger.info(
                "Fetched %d codes from %s (browser, %s)",
                len(codes),
                source.name,
                source.selector_type,
            )
            return codes

        except Exception as e:
            logger.error("Browser error fetching %s: %s", source.name, e)
            raise
        finally:
            await page.close()

    async def fetch_all_enabled(self) -> dict[str, list[str]]:
        """Fetch codes from all enabled sources."""
        sources = self.storage.list_sources(enabled_only=True)
        results = {}

        for source_data in sources:
            source = SourceConfig(
                name=source_data["name"],
                url=source_data["url"],
                selector_type=source_data["selector_type"],
                selector=source_data["selector"],
                enabled=bool(source_data["enabled"]),
            )
            try:
                codes = await self.fetch_source(source)
                results[source.name] = codes
            except Exception as e:
                logger.error("Failed to fetch from %s: %s", source.name, e)
                results[source.name] = []

            # Rate limiting
            if source.rate_limit_seconds > 0:
                await asyncio.sleep(source.rate_limit_seconds)

        return results


def register_extractor(name: str, extractor: Extractor) -> None:
    """Register a custom extractor."""
    EXTRACTORS[name] = extractor


def get_extractor(name: str) -> Extractor | None:
    """Get extractor by name."""
    return EXTRACTORS.get(name)


def create_default_sources() -> list[SourceConfig]:
    """Create default source configurations."""
    return [
        SourceConfig(
            name="wiki",
            url="https://genshin-impact.fandom.com/wiki/Promotional_Code",
            selector_type="css",
            selector="table.wikitable.sortable tbody tr td:first-child code, table.wikitable.sortable tbody tr td:first-child b code",
            enabled=True,
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="wiki_api",
            url="https://genshin-impact.fandom.com/api.php",
            selector_type="json",
            selector="parse.text.*",
            enabled=True,
            headers={"User-Agent": "GenshinCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="genshin_codes_github",
            url="https://raw.githubusercontent.com/GenshinCodeArchive/codes/main/codes.json",
            selector_type="json",
            selector="[*].code",
            enabled=True,
            timeout_seconds=30,
            rate_limit_seconds=1.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="hoyolab",
            url="https://www.hoyolab.com/article/",
            selector_type="css",
            selector=".article-content code, .article-content .code-block",
            enabled=False,  # Requires auth
            requires_browser=True,
            browser_wait_selector=".article-content",
            timeout_seconds=60,
            rate_limit_seconds=5.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
    ]


# Source presets for common sites
SOURCE_PRESETS: dict[str, SourceConfig] = {
    "genshin_wiki": SourceConfig(
        name="genshin_wiki",
        url="https://genshin-impact.fandom.com/wiki/Promotional_Code",
        selector_type="css",
        selector="table.wikitable.sortable tbody tr td:first-child code, table.wikitable.sortable tbody tr td:first-child b code",
        enabled=True,
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "genshin_wiki_api": SourceConfig(
        name="genshin_wiki_api",
        url="https://genshin-impact.fandom.com/api.php",
        selector_type="json",
        selector="parse.text.*",
        enabled=True,
        headers={"User-Agent": "GenshinCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "hoyolab_articles": SourceConfig(
        name="hoyolab_articles",
        url="https://www.hoyolab.com/article/",
        selector_type="css",
        selector=".article-content code, .article-content .code-block",
        enabled=False,
        requires_browser=True,
        browser_wait_selector=".article-content",
        timeout_seconds=60,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "reddit_genshin": SourceConfig(
        name="reddit_genshin",
        url="https://www.reddit.com/r/Genshin_Impact/search.json?q=promo+code&restrict_sr=1&sort=new",
        selector_type="json",
        selector="data.children[*].data.selftext",
        enabled=False,  # Reddit blocks with 403
        headers={"User-Agent": "GenshinCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=3.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "genshin_codes_github": SourceConfig(
        name="genshin_codes_github",
        url="https://raw.githubusercontent.com/GenshinCodeArchive/codes/main/codes.json",
        selector_type="json",
        selector="[*].code",
        enabled=True,
        timeout_seconds=30,
        rate_limit_seconds=1.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "hoyoverse_news": SourceConfig(
        name="hoyoverse_news",
        url="https://genshin.hoyoverse.com/en/news",
        selector_type="css",
        selector="[class*=\"news\"]",
        enabled=False,  # Requires browser, no codes in listing
        requires_browser=True,
        browser_wait_selector="[class*=\"news\"]",
        timeout_seconds=60,
        rate_limit_seconds=10.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "twitter_nitter": SourceConfig(
        name="twitter_nitter",
        url="https://nitter.net/GenshinImpact/search?q=redemption%20code&f=tweets",
        selector_type="css",
        selector=".tweet-content, .tweet-text",
        enabled=False,  # Nitter instances blocked/empty
        headers={"User-Agent": "GenshinCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "youtube_channel": SourceConfig(
        name="youtube_channel",
        url="https://www.youtube.com/@GenshinImpact/videos",
        selector_type="css",
        selector="#video-title, #description-text",
        enabled=False,  # Requires browser/JS
        requires_browser=True,
        browser_wait_selector="#contents",
        timeout_seconds=60,
        rate_limit_seconds=10.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "discord_webhook": SourceConfig(
        name="discord_webhook",
        url="https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN",
        selector_type="json",
        selector="content",
        enabled=False,  # Requires webhook URL configuration
        headers={"Content-Type": "application/json"},
        timeout_seconds=10,
        rate_limit_seconds=1.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
}


def get_preset(name: str) -> SourceConfig | None:
    """Get a source preset by name."""
    return SOURCE_PRESETS.get(name)


def list_presets() -> list[str]:
    """List available source preset names."""
    return list(SOURCE_PRESETS.keys())


async def seed_default_sources(storage: Storage) -> int:
    """Seed database with default sources if not present."""
    count = 0
    for source in create_default_sources():
        try:
            storage.add_source(
                name=source.name,
                url=source.url,
                selector_type=source.selector_type,
                selector=source.selector,
            )
            count += 1
            logger.info("Seeded source: %s", source.name)
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                logger.debug("Source already exists: %s", source.name)
            else:
                logger.error("Failed to seed source %s: %s", source.name, e)
    return count


if __name__ == "__main__":
    import asyncio
    import os
    import tempfile

    async def test():
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            storage = Storage(db_path)
            await seed_default_sources(storage)

            async with SourceFetcher(storage) as fetcher:
                results = await fetcher.fetch_all_enabled()
                for name, codes in results.items():
                    print(f"{name}: {len(codes)} codes")
                    for code in codes[:3]:
                        print(f"  {code}")
        finally:
            os.unlink(db_path)

    asyncio.run(test())
