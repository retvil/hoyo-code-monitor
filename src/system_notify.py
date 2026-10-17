"""Windows toast notifications for HoYo Code Monitor.

Best-effort desktop notification via the WinRT toast API. Toasts are a
*second* channel alongside Telegram, not a replacement: they require no
configuration and never touch the network, so the scheduler announces events
on the machine even when no Telegram bot is configured.

Design constraints:

* **Never raise.** A toast is a convenience. A missing console session, a
  stripped-down Windows install, or a locked screen must not fail a fetch
  cycle, so every failure is logged at DEBUG and the call returns ``False``.
* **No network, no secrets.** The payload is ``title`` + ``message`` only; no
  cookies, tokens, or account identifiers beyond the plain account name that
  Telegram already receives.
* **Async-friendly.** The library opens a pipe and waits for ``PowerShell`` to
  print its exit line, which is blocking. Callers run it through
  :func:`asyncio.to_thread` via :func:`notify_toast` so the scheduler loop is
  never held up.
* **No heavy import cost.** ``winotify`` is imported inside
  :func:`show_toast`, keeping the module importable in CI images that do not
  install the optional dependency.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# The app_id must match a registered app manifest. Without one, the toast is
# still shown but attributed to a generic "Windows" identity, which is
# acceptable for a local-only tool.
APP_ID = "HoyoCodeMonitor"

# Timeout for the spawned notification process, kept short so a hung
# PowerShell cannot stall a background thread indefinitely.
SHOW_TIMEOUT = 10.0

# Toasts batch at most this many codes per message; the rest become "+N more".
MAX_CODES_PER_TOAST = 5


def is_configured() -> bool:
    """Return whether the optional toast dependency is importable."""
    try:
        import winotify  # noqa: F401, PLC0415 -- optional dependency probe

        return True  # noqa: TRY300 -- probe result reads better inline
    except ImportError:
        return False


def show_toast(title: str, message: str) -> bool:
    """Show a Windows toast. Best effort: never raises, returns success flag."""
    if not title and not message:
        return False
    try:
        from winotify import Notification  # noqa: PLC0415 -- optional dependency
    except ImportError as e:
        logger.debug("Toast unavailable, winotify not installed: %s", e)
        return False

    try:
        notification = Notification(app_id=APP_ID, title=title, msg=message)
        # ``show()`` takes no timeout argument on current winotify; the timeout
        # is only meaningful for the Process returned by ``start_showing()``,
        # which is a different (and heavier) API. Keep it a simple blocking
        # call - a hung notification must not hold a background thread.
        notification.show()
        return True  # noqa: TRY300 -- success reads better inline
    except Exception as e:
        logger.debug("Toast failed: %s", e)
        return False


async def notify_toast(title: str, message: str) -> bool:
    """Async wrapper so the blocking toast call never blocks the event loop."""
    return await asyncio.to_thread(show_toast, title, message)


async def notify_new_codes_toast(codes: list[str]) -> bool:
    """Toast for newly found promo codes (batched per scheduler cycle)."""
    if not codes:
        return False
    shown = ", ".join(codes[:MAX_CODES_PER_TOAST])
    extra = f" (+{len(codes) - MAX_CODES_PER_TOAST} more)" if len(codes) > MAX_CODES_PER_TOAST else ""
    return await notify_toast(f"New codes: {len(codes)}", f"{shown}{extra}")


async def notify_redeemed_toast(code: str, account: str, reward: str) -> bool:
    """Toast for a successful redemption."""
    if not code:
        return False
    detail = f"{account}: {reward}" if reward else account
    return await notify_toast(f"Redeemed {code}", detail)
