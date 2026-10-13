"""Source registry and HTTP fetchers for Genshin code monitor.

Provides pluggable source configuration and extraction strategies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Self
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
from lxml import html as lxml_html

from src.constants import DEFAULT_SOURCE_HOST_CONCURRENCY
from src.exceptions import SourceValidationError
from src.http_session import get_session
from src.storage import Storage

logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"\b[A-Za-z0-9]{8,24}\b")


def is_plausible_code(text: str) -> bool:
    """Heuristic: real promo codes have digits, are ALL-CAPS, or long MixedCase.

    Rejects plain lowercase English words picked up from article text.
    """
    if not (8 <= len(text) <= 24):
        return False
    if any(ch.isdigit() for ch in text):
        return True
    if text == text.upper():
        return True
    return len(text) >= 10 and any(ch.isupper() for ch in text)


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


class Extractor(Protocol):
    """Protocol for code extractors."""

    def extract(self, content: str, selector: str) -> list[str]:
        """Extract codes from content using selector."""
        ...


class CSSExtractor:
    """Extract codes using CSS selectors."""

    def extract(self, content: str, selector: str) -> list[str]:
        soup = BeautifulSoup(content, "lxml")
        elements = soup.select(selector)
        codes: list[str] = []
        for el in elements:
            for m in _CODE_RE.findall(el.get_text(strip=True)):
                if is_plausible_code(m):
                    codes.append(m)
        return _dedup(codes)


class XPathExtractor:
    """Extract codes using XPath selectors (via lxml)."""

    def extract(self, content: str, selector: str) -> list[str]:
        tree = lxml_html.fromstring(content)
        elements = tree.xpath(selector)
        codes: list[str] = []
        for el in elements:
            if isinstance(el, str):
                text = el
            else:
                text = el.text_content() if hasattr(el, "text_content") else str(el)
            for m in _CODE_RE.findall(text):
                if is_plausible_code(m):
                    codes.append(m)
        return _dedup(codes)


CODE_KEYS = ("code", "cdkey", "promo_code", "promocode", "redemption_code", "gift_code")


class JSONExtractor:
    """Extract codes from JSON using dot-path selectors.

    Selector examples: "" (whole document), "active", "data.list".
    Falls back to whole-document scan if path is missing.
    Values of exact `code`-like keys are taken verbatim (case preserved).
    """

    def extract(self, content: str, selector: str) -> list[str]:
        import json

        data = json.loads(content)
        target: Any = data
        if selector:
            node: Any = data
            missing = False
            for part in selector.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    missing = True
                    break
            if missing:
                logger.warning("JSON selector %r not found, scanning whole document", selector)
            else:
                target = node
        codes: list[str] = []

        def find_codes(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if (
                        isinstance(k, str)
                        and k.lower() in CODE_KEYS
                        and isinstance(v, str)
                        and v.strip()
                    ):
                        codes.append(v.strip())
                    else:
                        find_codes(v)
            elif isinstance(obj, list):
                for v in obj:
                    find_codes(v)
            elif isinstance(obj, str):
                for m in _CODE_RE.findall(obj):
                    if is_plausible_code(m):
                        codes.append(m)

        find_codes(target)
        return list(dict.fromkeys(codes))


class RegexExtractor:
    """Extract codes using regex pattern."""

    def __init__(self) -> None:
        self._cache: dict[str, re.Pattern[str]] = {}

    def extract(self, content: str, selector: str) -> list[str]:
        pat = self._cache.get(selector)
        if pat is None:
            pat = re.compile(selector)
            self._cache[selector] = pat
        return pat.findall(content)


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
    game: str = "genshin"

    def validate(self) -> None:
        """Validate source configuration."""
        from src.constants import GAMES

        if self.game not in GAMES:
            raise SourceValidationError(f"Unknown game: {self.game}")  # noqa: TRY003 -- validation message needs interpolation
        if self.selector_type not in EXTRACTORS:
            raise SourceValidationError(f"Unknown selector_type: {self.selector_type}")  # noqa: TRY003 -- validation message needs interpolation
        if not self.url:
            raise SourceValidationError("url is required")  # noqa: TRY003 -- validation message needs interpolation
        if not self.selector and self.selector_type != "json":
            raise SourceValidationError("selector is required")  # noqa: TRY003 -- validation message needs interpolation
        if self.timeout_seconds <= 0:
            raise SourceValidationError("timeout_seconds must be positive")  # noqa: TRY003 -- validation message needs interpolation
        if self.rate_limit_seconds < 0:
            raise SourceValidationError("rate_limit_seconds must be non-negative")  # noqa: TRY003 -- validation message needs interpolation
        if self.max_retries < 0:
            raise SourceValidationError("max_retries must be non-negative")  # noqa: TRY003 -- validation message needs interpolation
        if self.retry_base_delay <= 0:
            raise SourceValidationError("retry_base_delay must be positive")  # noqa: TRY003 -- validation message needs interpolation

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Self:
        """Build a SourceConfig from a database row dict.

        Normalizes legacy fields (JSON-stringified headers) and applies safe defaults
        so callers don't repeat the same coercion logic in three places.
        """
        headers = row.get("headers") or {}
        if isinstance(headers, str):
            try:
                headers = json.loads(headers)
            except Exception:
                headers = {}
        return cls(
            name=row["name"],
            url=row["url"],
            selector_type=row["selector_type"],
            selector=row["selector"],
            enabled=bool(row["enabled"]),
            headers=headers,
            timeout_seconds=int(row.get("timeout_seconds") or 30),
            rate_limit_seconds=float(row.get("rate_limit_seconds") or 1.0),
            requires_browser=bool(row.get("requires_browser")),
            browser_wait_selector=row.get("browser_wait_selector"),
            browser_wait_seconds=int(row.get("browser_wait_seconds") or 5),
            max_retries=int(row.get("max_retries") or 3),
            retry_base_delay=float(row.get("retry_base_delay") or 1.0),
            game=row.get("game") or "genshin",
        )


class _HostGate:
    """Bounds in-flight requests to a single host and spaces out their starts.

    Two knobs, because they solve different problems:

    * ``concurrency`` (an ``asyncio.Semaphore``) caps how many requests to this
      host are in flight at once, so a burst of sources sharing a host cannot
      open every connection simultaneously.
    * ``min_interval`` spaces the *start* of each request by at least that many
      seconds, which is what ``SourceConfig.rate_limit_seconds`` asked for.

    The next slot is reserved while holding a lock and then slept out, so
    concurrent waiters receive distinct, ordered start times instead of racing
    to the same timestamp.
    """

    __slots__ = ("_lock", "_next_slot", "_semaphore", "host", "min_interval")

    def __init__(self, host: str, concurrency: int, min_interval: float) -> None:
        self.host = host
        self.min_interval = min_interval
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._lock = asyncio.Lock()
        # ``None`` means "nothing queued yet", so the first request starts
        # immediately. Without this, the leading request would wait out a full
        # min_interval for no reason — the old sequential loop slept *between*
        # requests, never before the first one.
        self._next_slot: float | None = None

    async def __aenter__(self) -> _HostGate:
        await self._semaphore.acquire()
        if self.min_interval > 0:
            loop = asyncio.get_running_loop()
            async with self._lock:
                now = loop.time()
                start = now if self._next_slot is None else max(now, self._next_slot)
                self._next_slot = start + self.min_interval
            delay = start - now
            if delay > 0:
                await asyncio.sleep(delay)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        self._semaphore.release()


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
        # Serializes lazy browser creation. ``_get_browser`` awaits inside its
        # init branch, so without this lock parallel browser fetches would each
        # start their own Playwright instance and Chromium process.
        self._browser_lock = asyncio.Lock()
        # hostname -> _HostGate, built once per fetch_all_enabled() cycle. A
        # per-cycle (not per-instance) registry keeps the spacing state from
        # leaking between cycles, where a long-dead timestamp would stall the
        # first request of every subsequent run.
        self._host_gates: dict[str, _HostGate] = {}

    async def __aenter__(self) -> Self:
        if self._session is None:
            # Borrow from the process-wide pool instead of building a private
            # pool: every scheduler cycle would otherwise open and tear down a
            # fresh connection pool. See src/http_session.py.
            self._session = get_session()
            self._own_session = False
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # A borrowed session is left open for the rest of the process; it is
        # torn down at shutdown by http_session.close_all().
        if self._own_session and self._session:
            await self._session.close()
        self._session = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if getattr(self, "_playwright", None):
            await self._playwright.stop()
            self._playwright = None

    async def _get_browser(self):
        """Lazy-initialize Playwright browser (single-flight)."""
        if self._browser is not None:
            return self._browser
        async with self._browser_lock:
            # Re-check under the lock: the first caller's await can suspend long
            # enough for others to queue up behind it.
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
            raise RuntimeError("Session not initialized. Use async context manager.")  # noqa: TRY003 -- validation message needs interpolation

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

            except aiohttp.ClientResponseError as e:
                # 4xx (except 429) will not recover — fail fast without retries
                if e.status != 429 and 400 <= e.status < 500:
                    logger.error("HTTP %s fetching %s (no retry): %s", e.status, source.name, e)
                    raise
                if attempt == max_retries - 1:
                    logger.error(
                        "HTTP error fetching %s after %d retries: %s", source.name, max_retries, e
                    )
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s. Retrying in %.1fs",
                    attempt + 1,
                    max_retries,
                    source.name,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            except aiohttp.ClientError as e:
                if attempt == max_retries - 1:
                    logger.error(
                        "HTTP error fetching %s after %d retries: %s", source.name, max_retries, e
                    )
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s. Retrying in %.1fs",
                    attempt + 1,
                    max_retries,
                    source.name,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error("Error extracting from %s: %s", source.name, e)
                raise

    async def _fetch_with_browser(self, source: SourceConfig) -> list[str]:
        """Fetch using Playwright for JS-rendered content."""
        browser = await self._get_browser()
        page = await browser.new_page()

        try:
            await page.goto(
                source.url, wait_until="networkidle", timeout=source.timeout_seconds * 1000
            )

            if source.browser_wait_selector:
                await page.wait_for_selector(
                    source.browser_wait_selector, timeout=source.browser_wait_seconds * 1000
                )
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

    def _host_of(self, url: str) -> str:
        """Hostname used to group sources for per-host rate limiting."""
        return urlparse(url).hostname or url

    def _build_host_gates(self, sources: list[SourceConfig]) -> dict[str, _HostGate]:
        """Build one :class:`_HostGate` per hostname.

        Sources sharing a host can carry different ``rate_limit_seconds``; the
        most conservative one wins, so a 5s source is not crowded out by a 1s
        neighbour on the same host. Building gates up front (rather than lazily
        during the run) keeps the spacing independent of scheduling order, so
        two runs over the same rows behave identically.
        """
        intervals: dict[str, float] = {}
        for source in sources:
            host = self._host_of(source.url)
            interval = max(0.0, source.rate_limit_seconds)
            intervals[host] = max(intervals.get(host, 0.0), interval)
        return {
            host: _HostGate(host, DEFAULT_SOURCE_HOST_CONCURRENCY, interval)
            for host, interval in intervals.items()
        }

    async def fetch_all_enabled(self) -> dict[str, list[str]]:
        """Fetch codes from every enabled source, overlapping unrelated hosts.

        Requests to *different* hosts run concurrently. Requests sharing a host
        are gated by a per-host :class:`_HostGate`, which caps in-flight
        connections and spaces each start by that host's ``rate_limit_seconds``.
        That preserves the politeness of the previous sequential loop — which
        slept after every single source — without serialising hosts that never
        talk to each other. A 46-source cycle is therefore no longer the sum of
        every source's rate limit; it is roughly the heaviest single host.

        Every enabled source appears in the result exactly once, in row order.
        A source that fails yields an empty list and has its error counter
        incremented, exactly as before.
        """
        rows = self.storage.list_sources(enabled_only=True)
        if not rows:
            return {}

        # Parse first so a malformed row costs one error log instead of aborting
        # the whole cycle.
        parsed: list[tuple[str, SourceConfig | None]] = []
        for row in rows:
            name = str(row.get("name") or "?")
            try:
                parsed.append((name, SourceConfig.from_row(row)))
            except Exception as e:
                logger.error("Skipping malformed source %r: %s", name, e)
                parsed.append((name, None))

        self._host_gates = self._build_host_gates([s for _, s in parsed if s is not None])

        async def run_one(name: str, source: SourceConfig | None) -> tuple[str, list[str]]:
            if source is None:
                return name, []
            gate = self._host_gates[self._host_of(source.url)]
            try:
                async with gate:
                    return name, await self.fetch_source(source)
            except Exception as e:
                logger.error("Failed to fetch from %s: %s", source.name, e)
                try:
                    self.storage.increment_source_error(source.name)
                except Exception:
                    logger.debug("Could not increment error count for %s", source.name)
                return name, []

        # run_one swallows every exception, so gather never leaves a sibling
        # coroutine with an unretrieved exception.
        pairs = await asyncio.gather(*(run_one(n, s) for n, s in parsed))
        return dict(pairs)


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
            selector="",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="genshin_codes_github",
            url="https://raw.githubusercontent.com/GenshinCodeArchive/codes/main/codes.json",
            selector_type="json",
            selector="",
            enabled=False,  # Repo removed (404 as of 2026-09) - kept for manual URL fix
            timeout_seconds=30,
            rate_limit_seconds=1.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="ennead_mihoyo_api",
            url="https://api.ennead.cc/mihoyo/genshin/codes",
            selector_type="json",
            selector="active",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="pockettactics_guides",
            url="https://www.pockettactics.com/genshin-impact/codes",
            selector_type="css",
            selector="li strong",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=5.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="theclick_guides",
            url="https://www.theclick.gg/genshin-impact-codes-2/",
            selector_type="css",
            selector=".entry-content code",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=5.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="eurogamer_guides",
            url="https://www.eurogamer.net/genshin-impact-codes-livestream-active-working-how-to-redeem-9026",
            selector_type="css",
            selector="article ul li",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=5.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="mmoculture_guides",
            url="https://mmoculture.com/2026/08/genshin-impact-redeem-codes/",
            selector_type="css",
            selector="article li",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=5.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="playnforge_guides",
            url="https://www.playnforge.com/genshin-codes",
            selector_type="css",
            selector="table td",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=5.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="hoyo_codes_api",
            url="https://hoyo-codes.seria.moe/codes?game=genshin",
            selector_type="json",
            selector="",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
        ),
        SourceConfig(
            name="ennead_codes_api",
            url="https://api.ennead.cc/codes/genshin",
            selector_type="json",
            selector="",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="genshin",
        ),
        SourceConfig(
            name="hoyo_codes_hsr",
            url="https://hoyo-codes.seria.moe/codes?game=hkrpg",
            selector_type="json",
            selector="",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="hsr",
        ),
        SourceConfig(
            name="ennead_hsr_api",
            url="https://api.ennead.cc/mihoyo/starrail/codes",
            selector_type="json",
            selector="active",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="hsr",
        ),
        SourceConfig(
            name="ennead_hi3_api",
            url="https://api.ennead.cc/mihoyo/honkai/codes",
            selector_type="json",
            selector="active",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="hi3",
        ),
        SourceConfig(
            name="hoyo_codes_tot",
            url="https://hoyo-codes.seria.moe/codes?game=tot",
            selector_type="json",
            selector="",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="tot",
        ),
        SourceConfig(
            name="ennead_tot_api",
            url="https://api.ennead.cc/mihoyo/themis/codes",
            selector_type="json",
            selector="active",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="tot",
        ),
        SourceConfig(
            name="hoyo_codes_zzz",
            url="https://hoyo-codes.seria.moe/codes?game=nap",
            selector_type="json",
            selector="",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="zzz",
        ),
        SourceConfig(
            name="ennead_zzz_api",
            url="https://api.ennead.cc/mihoyo/zenless/codes",
            selector_type="json",
            selector="active",
            enabled=True,
            headers={"User-Agent": "HoYoCodeMonitor/1.0"},
            timeout_seconds=30,
            rate_limit_seconds=2.0,
            max_retries=3,
            retry_base_delay=1.0,
            game="zzz",
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
        selector="",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
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
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=3.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "genshin_codes_github": SourceConfig(
        name="genshin_codes_github",
        url="https://raw.githubusercontent.com/GenshinCodeArchive/codes/main/codes.json",
        selector_type="json",
        selector="",
        enabled=False,  # Repo removed (404 as of 2026-09)
        timeout_seconds=30,
        rate_limit_seconds=1.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "hoyo_codes_hsr": SourceConfig(
        name="hoyo_codes_hsr",
        url="https://hoyo-codes.seria.moe/codes?game=hkrpg",
        selector_type="json",
        selector="",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="hsr",
    ),
    "ennead_hsr_api": SourceConfig(
        name="ennead_hsr_api",
        url="https://api.ennead.cc/mihoyo/starrail/codes",
        selector_type="json",
        selector="active",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="hsr",
    ),
    "ennead_hi3_api": SourceConfig(
        name="ennead_hi3_api",
        url="https://api.ennead.cc/mihoyo/honkai/codes",
        selector_type="json",
        selector="active",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="hi3",
    ),
    "hoyo_codes_tot": SourceConfig(
        name="hoyo_codes_tot",
        url="https://hoyo-codes.seria.moe/codes?game=tot",
        selector_type="json",
        selector="",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="tot",
    ),
    "ennead_tot_api": SourceConfig(
        name="ennead_tot_api",
        url="https://api.ennead.cc/mihoyo/themis/codes",
        selector_type="json",
        selector="active",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="tot",
    ),
    "hoyo_codes_zzz": SourceConfig(
        name="hoyo_codes_zzz",
        url="https://hoyo-codes.seria.moe/codes?game=nap",
        selector_type="json",
        selector="",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="zzz",
    ),
    "ennead_zzz_api": SourceConfig(
        name="ennead_zzz_api",
        url="https://api.ennead.cc/mihoyo/zenless/codes",
        selector_type="json",
        selector="active",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="zzz",
    ),
    "ennead_mihoyo_api": SourceConfig(
        name="ennead_mihoyo_api",
        url="https://api.ennead.cc/mihoyo/genshin/codes",
        selector_type="json",
        selector="active",  # skip inactive/expired codes
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "pockettactics_guides": SourceConfig(
        name="pockettactics_guides",
        url="https://www.pockettactics.com/genshin-impact/codes",
        selector_type="css",
        selector="li strong",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "theclick_guides": SourceConfig(
        name="theclick_guides",
        url="https://www.theclick.gg/genshin-impact-codes-2/",
        selector_type="css",
        selector=".entry-content code",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "eurogamer_guides": SourceConfig(
        name="eurogamer_guides",
        url="https://www.eurogamer.net/genshin-impact-codes-livestream-active-working-how-to-redeem-9026",
        selector_type="css",
        selector="article ul li",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "playnforge_guides": SourceConfig(
        name="playnforge_guides",
        url="https://www.playnforge.com/genshin-codes",
        selector_type="css",
        selector="table td",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "mmoculture_guides": SourceConfig(
        name="mmoculture_guides",
        url="https://mmoculture.com/2026/08/genshin-impact-redeem-codes/",
        selector_type="css",
        selector="article li",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "hoyo_codes_api": SourceConfig(
        name="hoyo_codes_api",
        url="https://hoyo-codes.seria.moe/codes?game=genshin",
        selector_type="json",
        selector="",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "ennead_codes_api": SourceConfig(
        name="ennead_codes_api",
        url="https://api.ennead.cc/codes/genshin",
        selector_type="json",
        selector="",
        enabled=True,
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
        timeout_seconds=30,
        rate_limit_seconds=2.0,
        max_retries=3,
        retry_base_delay=1.0,
    ),
    "hoyolab_news_official": SourceConfig(
        name="hoyolab_news_official",
        url="https://bbs-api-os.hoyolab.com/community/post/wapi/getNewsList?gids=2&page_size=20&type=1",
        selector_type="json",
        selector="",
        enabled=False,  # Very noisy: ~400 word-like candidates per fetch, mostly article text
        headers={"User-Agent": "HoYoCodeMonitor/1.0", "x-rpc-language": "en-us"},
        timeout_seconds=30,
        rate_limit_seconds=5.0,
        max_retries=3,
        retry_base_delay=1.0,
        game="genshin",
    ),
    "hoyoverse_news": SourceConfig(
        name="hoyoverse_news",
        url="https://genshin.hoyoverse.com/en/news",
        selector_type="css",
        selector='[class*="news"]',
        enabled=False,  # Requires browser, no codes in listing
        requires_browser=True,
        browser_wait_selector='[class*="news"]',
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
        headers={"User-Agent": "HoYoCodeMonitor/1.0"},
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
    """Seed database with all known presets if not present (idempotent).

    Seeds from SOURCE_PRESETS (the full researched list). Presets whose name
    or URL already exists (e.g. legacy names from older versions) are skipped,
    so upgrades never create duplicates.
    """
    count = 0
    existing = storage.list_sources()
    existing_names = {s["name"] for s in existing}
    existing_urls = {s["url"] for s in existing}
    for source in SOURCE_PRESETS.values():
        if source.name in existing_names or source.url in existing_urls:
            logger.debug("Source already exists: %s", source.name)
            continue
        try:
            storage.add_source(
                name=source.name,
                url=source.url,
                selector_type=source.selector_type,
                selector=source.selector,
                enabled=source.enabled,
                headers=source.headers,
                timeout_seconds=source.timeout_seconds,
                rate_limit_seconds=source.rate_limit_seconds,
                requires_browser=source.requires_browser,
                browser_wait_selector=source.browser_wait_selector,
                browser_wait_seconds=source.browser_wait_seconds,
                max_retries=source.max_retries,
                retry_base_delay=source.retry_base_delay,
                game=source.game,
            )
            existing_names.add(source.name)
            existing_urls.add(source.url)
            count += 1
            logger.info("Seeded source: %s", source.name)
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                logger.debug("Source already exists: %s", source.name)
            else:
                logger.exception("Failed to seed source %s", source.name)
    return count


if __name__ == "__main__":
    import asyncio
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
            Path(db_path).unlink(missing_ok=True)

    asyncio.run(test())
