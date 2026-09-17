"""Automatic cookie capture via browser login.

Opens HoYoLAB login page in a visible browser window. The user logs in
manually once; the app watches the browser context, captures auth cookies
(ltuid/ltoken, incl. _v2 variants) and stores them encrypted.
Local-only: browser opens on the user's own PC.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.hoyolab.com/"
# Skip junk/consent cookies, keep everything else (auth needs full set:
# ltuid_v2, ltoken_v2, cookie_token_v2, account_id_v2, account_mid_v2, ...)
SKIP_PREFIXES = ("_ga", "_gid", "_gat", "_hj", "intercom-", "cf_", "__cf")
SKIP_EXACT = {"mi18nLang", "DEVICEFP", "_MHYUUID", "Hm_lvt_", "Hm_lpvt_"}
POLL_SECONDS = 2.0


def profile_dir() -> str:
    """Persistent browser profile dir (login survives restarts)."""
    from src.paths import app_data_dir

    d = app_data_dir() / "browser-profile"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def browsers_dir() -> Path:
    """Directory Playwright downloads browsers to.

    Frozen exe: persistent app-data dir (the bundle temp dir is wiped on exit,
    so the default driver-relative lookup fails). Source: respect
    PLAYWRIGHT_BROWSERS_PATH or the standard user cache.
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        from src.paths import app_data_dir

        d = app_data_dir() / "ms-playwright"
        d.mkdir(parents=True, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(d)
        return d
    return Path.home() / ".cache" / "ms-playwright"


def chromium_executable() -> Path | None:
    """Find a downloaded full Chromium executable, if any."""
    for exe in sorted(browsers_dir().glob("chromium-*/chrome-*/chrome.exe")):
        if exe.is_file():
            return exe
    return None


def ensure_chromium() -> None:
    """Download Chromium via the bundled Playwright driver if missing.

    Raises:
        RuntimeError: If Playwright is unavailable or the download fails.
    """
    if chromium_executable():
        return
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except ImportError as e:
        raise RuntimeError("Playwright is not installed (pip install playwright)") from e  # noqa: TRY003 -- actionable install hint
    target = browsers_dir()
    logger.info("Chromium not found, downloading to %s (~170MB, one-time)", target)
    env = dict(get_driver_env())
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(target)
    try:
        driver_executable, driver_cli = compute_driver_executable()
        proc = subprocess.run(
            [driver_executable, driver_cli, "install", "chromium"],
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except Exception as e:
        raise RuntimeError(f"Chromium download failed to start: {e}") from e  # noqa: TRY003 -- startup detail needed
    if proc.returncode != 0 or not chromium_executable():
        tail = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"Chromium download failed: {tail}") from None  # noqa: TRY003, EM101 -- download detail needed
    logger.info("Chromium downloaded")


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
        raise RuntimeError("Playwright is not installed (pip install playwright)") from e  # noqa: TRY003 -- actionable install hint

    deadline = time.time() + timeout_seconds
    # Blocking download (~170MB first run) must not stall the event loop
    await asyncio.to_thread(ensure_chromium)
    async with async_playwright() as p:
        # Persistent profile: login survives restarts, user logs in once
        context = await p.chromium.launch_persistent_context(
            profile_dir(),
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
            raise TimeoutError(f"No login within {timeout_seconds}s")  # noqa: TRY003 -- timeout detail needed
        finally:
            await context.close()


def capture_cookies_sync(timeout_seconds: int = 300) -> dict[str, str]:
    """Sync wrapper for capture_cookies."""
    return asyncio.run(capture_cookies(timeout_seconds))
