"""Telegram notifications for HoYo Code Monitor.

Sends messages via Bot API on new codes and successful redemptions.
Configure with bot token + chat id (stored in DB config, never in git).
Get token from @BotFather, chat id from @userinfobot.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    import aiohttp

    if not bot_token or not chat_id:
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as sess:
            async with sess.post(
                API_URL.format(token=bot_token),
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            ) as r:
                data = await r.json()
                ok = bool(data.get("ok"))
                if not ok:
                    logger.warning("Telegram send failed: %s", data)
                return ok
    except Exception as e:
        logger.warning("Telegram send error: %s", e)
        return False


def notify_configured(storage) -> tuple[str, str] | None:
    """Return (token, chat_id) if notifications configured, else None."""
    token = storage.get_config("telegram_bot_token", "") or ""
    chat_id = storage.get_config("telegram_chat_id", "") or ""
    if token and chat_id:
        return token, chat_id
    return None


async def notify_new_codes(storage, codes: list[str]) -> None:
    """Notify about newly found codes (call sparingly, batched per cycle)."""
    cfg = notify_configured(storage)
    if not cfg or not codes:
        return
    shown = ", ".join(f"<code>{c}</code>" for c in codes[:10])
    extra = f" (+{len(codes) - 10} more)" if len(codes) > 10 else ""
    await send_telegram(cfg[0], cfg[1], f"🎁 New Genshin codes ({len(codes)}): {shown}{extra}")


async def notify_redeemed(storage, code: str, account: str, reward: str) -> None:
    """Notify about successful redemption."""
    cfg = notify_configured(storage)
    if not cfg:
        return
    await send_telegram(cfg[0], cfg[1], f"✅ <code>{code}</code> redeemed for {account}: {reward}")
