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
# Skip junk/consent cookies, keep everything else (auth needs full set:
# ltuid_v2, ltoken_v2, cookie_token_v2, account_id_v2, account_mid_v2, ...)
SKIP_PREFIXES = ("_ga", "_gid", "_gat", "_hj", "intercom-", "cf_", "__cf")
SKIP_EXACT = {"mi18nLang", "DEVICEFP", "_MHYUUID", "Hm_lvt_", "Hm_lpvt_"}
POLL_SECONDS = 2.0
PROFILE_DIR = "data/browser-profile"


def _normalize(cookies: list[dict]) -> dict[str, str]:
    """Pick auth cookies from Playwright cookie list.

    Keeps the full auth set plus normalized ltuid/ltoken aliases
    so the redeemer works regardless of _v2 suffix.
    """
    out: dict[str, str] = {}
    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        if not name or not value:
            continue
        if name in SKIP_EXACT or name.startswith(SKIP_PREFIXES):
            continue
        out[name] = value
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
        # Persistent profile: login survives restarts, user logs in once
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
        )
        try:
            # Already logged in from previous run?
            found = _normalize(await context.cookies())
            if found.get("ltuid") and found.get("ltoken"):
                logger.info("Already logged in via saved profile")
                return found
            page = await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            logger.info("Browser opened, waiting for HoYoLAB login (timeout %ds)", timeout_seconds)
            while time.time() < deadline:
                found = _normalize(await context.cookies())
                if found.get("ltuid") and found.get("ltoken"):
                    logger.info("Auth cookies captured (%d keys)", len(found))
                    return found
                await asyncio.sleep(POLL_SECONDS)
            raise TimeoutError(f"No login within {timeout_seconds}s")
        finally:
            await context.close()


def capture_cookies_sync(timeout_seconds: int = 300) -> dict[str, str]:
    """Sync wrapper for capture_cookies."""
    return asyncio.run(capture_cookies(timeout_seconds))
