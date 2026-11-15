"""Telegram notifications for HoYo Code Monitor.

Sends messages via Bot API on new codes and successful redemptions.
Configure with bot token + chat id (stored in DB config, never in git).
Get token from @BotFather, chat id from @userinfobot.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any
from urllib.parse import quote

from src.http_session import get_session

logger = logging.getLogger(__name__)

API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"

# Telegram is chatty but small; a tighter bound than the pool default.
SEND_TIMEOUT = 15.0


def _build_api_url(bot_token: str) -> str:
    """Build the Telegram API URL, quoting the token to protect against
    special characters and to prevent accidental URL structure injection."""
    return API_URL_TEMPLATE.format(token=quote(bot_token, safe=""))


async def send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message with retry + backoff. Returns True on success."""
    import aiohttp

    if not bot_token or not chat_id:
        return False
    max_retries = 3
    base_delay = 1.0
    timeout = aiohttp.ClientTimeout(total=SEND_TIMEOUT)
    session = get_session()
    api_url = _build_api_url(bot_token)
    for attempt in range(max_retries):
        try:
            async with session.post(
                api_url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=timeout,
            ) as r:
                if r.status != 200:
                    logger.warning(
                        "Telegram API HTTP %s (attempt %d/%d)",
                        r.status,
                        attempt + 1,
                        max_retries,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2**attempt))
                        continue
                    return False
                data = await r.json()
                ok = bool(data.get("ok"))
                if not ok:
                    logger.warning("Telegram send failed: %s", data)
                return ok
        except Exception as e:
            logger.warning("Telegram send error (attempt %d/%d): %s", attempt + 1, max_retries, e)
            if attempt == max_retries - 1:
                return False
            await asyncio.sleep(base_delay * (2**attempt))
    return False


def notify_configured(storage: Any) -> tuple[str, str] | None:
    """Return (token, chat_id) if notifications configured, else None."""
    token = storage.get_config("telegram_bot_token", "") or ""
    chat_id = storage.get_config("telegram_chat_id", "") or ""
    if token and chat_id:
        return token, chat_id
    return None


async def notify_new_codes(storage: Any, codes: list[str]) -> None:
    """Notify about newly found codes (call sparingly, batched per cycle)."""
    cfg = notify_configured(storage)
    if not cfg or not codes:
        return
    # Codes are alphanumeric, safe to wrap in <code> tags. Account names and
    # rewards are user-supplied and must be escaped to prevent HTML injection
    # via Telegram's HTML parser.
    shown = ", ".join(f"<code>{html.escape(c)}</code>" for c in codes[:10])
    extra = f" (+{len(codes) - 10} more)" if len(codes) > 10 else ""
    await send_telegram(cfg[0], cfg[1], f"🎁 New Genshin codes ({len(codes)}): {shown}{extra}")


async def notify_redeemed(storage: Any, code: str, account: str, reward: str) -> None:
    """Notify about successful redemption."""
    cfg = notify_configured(storage)
    if not cfg:
        return
    # Account names and rewards are user-supplied; escape to prevent HTML
    # injection via Telegram's HTML parser (e.g., <img src=x onerror=...>).
    safe_account = html.escape(account)
    safe_reward = html.escape(reward) if reward else ""
    await send_telegram(
        cfg[0], cfg[1], f"✅ <code>{html.escape(code)}</code> redeemed for {safe_account}: {safe_reward}"
    )
