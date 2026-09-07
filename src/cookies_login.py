"""Automatic cookie capture via browser login.

Opens HoYoLAB login page in a visible browser window. The user logs in
manually once; the app watches the browser context, captures auth cookies
(ltuid/ltoken, incl. _v2 variants) and stores them encrypted.
Local-only: browser opens on the user's own PC.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.hoyolab.com/"
WANT_KEYS = ("ltuid", "ltuid_v2", "ltoken", "ltoken_v2", "cookie_token_v2", "ltmid_v2")
POLL_SECONDS = 2.0


def _normalize(cookies: list[dict]) -> dict[str, str]:
    """Pick auth cookies from Playwright cookie list.

    Returns both raw names and normalized ltuid/ltoken aliases
    so the redeemer works regardless of _v2 suffix.
    """
    out: dict[str, str] = {}
    for c in cookies:
        name = c.get("name", "")
        if name in WANT_KEYS and c.get("value"):
            out[name] = c["value"]
    if "ltuid" not in out and "ltuid_v2" in out:
        out["ltuid"] = out["ltuid_v2"]
    if "ltoken" not in out and "ltoken_v2" in out:
        out["ltoken"] = out["ltoken_v2"]
    return out


async def capture_cookies(timeout_seconds: int = 300) -> dict[str, str]:
    """Open login page and wait until auth cookies appear.

    Args:
        timeout_seconds: Max time to wait for user login.

    Returns:
        Dict with at least ltuid + ltoken.

    Raises:
        TimeoutError: If user did not log in within timeout.
        RuntimeError: If Playwright is unavailable.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("Playwright is not installed (pip install playwright)") from e

    deadline = time.time() + timeout_seconds
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            logger.info("Browser opened, waiting for HoYoLAB login (timeout %ds)", timeout_seconds)
            while time.time() < deadline:
                found = _normalize(await context.cookies())
                if found.get("ltuid") and found.get("ltoken"):
                    logger.info("Auth cookies captured")
                    return found
                await asyncio.sleep(POLL_SECONDS)
            raise TimeoutError(f"No login within {timeout_seconds}s")
        finally:
            await browser.close()


def capture_cookies_sync(timeout_seconds: int = 300) -> dict[str, str]:
    """Sync wrapper for capture_cookies."""
    return asyncio.run(capture_cookies(timeout_seconds))
