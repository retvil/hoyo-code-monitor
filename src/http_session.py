"""Shared aiohttp session pool, keyed by event loop.

The app runs more than one event loop: the scheduler runs its own loop in a
background thread, and uvicorn runs another for the web API. A
``ClientSession`` is bound to the loop that created it, so a single global
session would fail with "attached to a different loop" / "Event loop is
closed". Sessions are therefore cached per running loop.

Every HTTP component (notify, redeemer, check-in transport, source fetcher,
health check) should call :func:`get_session` instead of constructing its own
``ClientSession``. That collapses the process down to one connection pool per
loop instead of one per component, and eliminates the per-call session churn
that previously burned a fresh socket for every Telegram message or health
probe.

Per-request ``timeout=`` and ``headers=`` still override the session defaults,
so callers keep their own timeouts and User-Agent without owning a session.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import aiohttp

logger = logging.getLogger(__name__)

# Generous default; callers that need a tighter bound (e.g. the 5s health
# probe) pass an explicit per-request timeout instead of a separate session.
DEFAULT_TIMEOUT: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=30)
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# id(loop) -> (loop, session). Guarded by _registry_lock because the scheduler
# thread and the web thread can both touch the registry.
_registry: dict[int, tuple[asyncio.AbstractEventLoop, aiohttp.ClientSession]] = {}
_registry_lock = threading.Lock()


def get_session(
    *,
    timeout: aiohttp.ClientTimeout | None = None,
    user_agent: str | None = None,
) -> aiohttp.ClientSession:
    """Return the shared ``ClientSession`` for the running event loop.

    A session is created on first use for a given loop and reused afterwards.
    If the cached session was closed, it is transparently replaced.

    Args:
        timeout: Session-level default timeout. Callers can still override per
            request. Defaults to a 30s total budget.
        user_agent: Session-level default User-Agent. Overridable per request.

    Returns:
        A live ``ClientSession`` bound to the current running loop.
    """
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _registry_lock:
        entry = _registry.get(key)
        if entry is not None:
            cached_loop, session = entry
            # ``id()`` is only unique among *live* objects: a loop that was
            # closed and garbage-collected can have its address reused by a new
            # loop. Comparing identity as well as liveness keeps a session
            # bound to a dead loop from being handed to a live one.
            if cached_loop is loop and not session.closed:
                return session
            # Stale or closed entry — drop it and build a fresh session.
            del _registry[key]
        session = aiohttp.ClientSession(
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            headers={"User-Agent": user_agent or DEFAULT_USER_AGENT},
        )
        _registry[key] = (loop, session)
        return session


async def _safe_close(session: aiohttp.ClientSession) -> None:
    """Close a session, swallowing shutdown-time errors."""
    if not session.closed:
        try:
            await session.close()
        except Exception:
            logger.debug("Error closing shared session", exc_info=True)


async def close_current() -> None:
    """Close the shared session for the running loop. Safe to call from it."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _registry_lock:
        entry = _registry.pop(key, None)
    if entry is None:
        return
    _cached_loop, session = entry
    await _safe_close(session)


async def close_all() -> None:
    """Best-effort close of every cached session. Call once at shutdown.

    Sessions belonging to a *different* still-running loop are closed on their
    own loop via ``call_soon_threadsafe`` to avoid cross-loop errors; sessions
    on the current loop (or on loops that are no longer running) are closed
    directly.
    """
    with _registry_lock:
        entries = list(_registry.items())
        _registry.clear()
    if not entries:
        return
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    for _key, (owner_loop, session) in entries:
        if session.closed:
            continue
        if current is None or owner_loop is current or not owner_loop.is_running():
            await _safe_close(session)
        else:

            def _close_on_owner(
                s: aiohttp.ClientSession = session,
                lp: asyncio.AbstractEventLoop = owner_loop,
            ) -> None:
                # Bound as default args (not a closure) so each callback keeps
                # its own session/loop pairing instead of reading them late.
                # The task reference is deliberately not stored: nothing awaits
                # it and the loop owns its lifetime.
                asyncio.ensure_future(_safe_close(s), loop=lp)  # noqa: RUF006

            try:
                owner_loop.call_soon_threadsafe(_close_on_owner)
            except RuntimeError:
                # Loop went away between the check and the call; nothing to do.
                logger.debug("Owner loop unavailable; skipping session close")
