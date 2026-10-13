"""Tests for the shared aiohttp session pool (src/http_session.py).

The pool is keyed by ``id(loop)``, so these tests care about three things:
that a loop reuses one session, that different loops never share a session,
and that a closed/dead loop's session is never handed to a live one.
"""

from __future__ import annotations

import asyncio
import threading

import aiohttp
import pytest

import src.http_session as hs
from src.http_session import close_all, close_current, get_session


@pytest.fixture(autouse=True)
def _clean_pool():
    """Empty the registry around every test.

    The registry is module-level state shared by all tests; without this a
    session created in one test leaks sockets into the next.
    """
    hs._registry.clear()
    yield
    hs._registry.clear()


class TestGetSession:
    async def test_reuses_session_within_one_loop(self) -> None:
        first = get_session()
        second = get_session()
        assert first is second

    async def test_session_is_open_and_usable(self) -> None:
        session = get_session()
        assert not session.closed
        assert isinstance(session, aiohttp.ClientSession)

    async def test_custom_timeout_and_user_agent_are_applied(self) -> None:
        expected_timeout_seconds = 5
        timeout = aiohttp.ClientTimeout(total=expected_timeout_seconds)
        session = get_session(timeout=timeout, user_agent="test-agent/1.0")
        assert session.timeout.total == expected_timeout_seconds
        assert session.headers["User-Agent"] == "test-agent/1.0"

    async def test_replaces_closed_session(self) -> None:
        first = get_session()
        await first.close()
        second = get_session()
        assert second is not first
        assert not second.closed

    async def test_no_stale_entry_left_after_closed_session_replaced(self) -> None:
        first = get_session()
        await first.close()
        second = get_session()
        assert len(hs._registry) == 1
        assert hs._registry[id(asyncio.get_running_loop())][1] is second

    async def test_registry_tracks_only_live_loop_entries(self) -> None:
        get_session()
        assert len(hs._registry) == 1
        key = id(asyncio.get_running_loop())
        cached_loop, _session = hs._registry[key]
        assert cached_loop is asyncio.get_running_loop()


class TestPerLoopIsolation:
    async def test_different_loops_get_different_sessions(self) -> None:
        """A ClientSession cannot cross loops — each loop must get its own."""
        captured: dict[str, int] = {}

        def run_other_loop() -> None:
            async def worker() -> None:
                session = get_session()
                captured["other"] = id(session)
                captured["other_closed"] = session.closed

            asyncio.run(worker())

        thread = threading.Thread(target=run_other_loop)
        thread.start()
        thread.join()

        mine = id(get_session())
        assert captured["other"] != mine
        assert captured["other_closed"] is False

    async def test_reuses_session_across_calls_in_same_loop_after_other_loop(self) -> None:
        def run_other_loop() -> None:
            async def worker() -> None:
                get_session()

            asyncio.run(worker())

        thread = threading.Thread(target=run_other_loop)
        thread.start()
        thread.join()

        assert get_session() is get_session()


class TestCloseCurrent:
    async def test_closes_and_forgets_current_session(self) -> None:
        session = get_session()
        await close_current()
        assert session.closed
        assert len(hs._registry) == 0

    async def test_is_noop_when_nothing_cached(self) -> None:
        await close_current()  # must not raise
        assert len(hs._registry) == 0

    async def test_new_session_created_after_close(self) -> None:
        first = get_session()
        await close_current()
        second = get_session()
        assert second is not first
        assert not second.closed


class TestCloseAll:
    async def test_closes_every_session_and_clears_registry(self) -> None:
        session = get_session()
        await close_all()
        assert session.closed
        assert len(hs._registry) == 0

    async def test_is_noop_when_registry_empty(self) -> None:
        await close_all()  # must not raise
        assert len(hs._registry) == 0

    async def test_closes_session_owned_by_a_running_foreign_loop(self) -> None:
        """Cross-loop close must be scheduled on the owner loop, not awaited.

        Awaiting a session bound to a *different running* loop raises
        "attached to a different loop", so ``close_all()`` must hand the close
        back to the owning loop via ``call_soon_threadsafe``.
        """
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:

            async def _make_session() -> aiohttp.ClientSession:
                # Must run *on the foreign loop*: get_session() binds to
                # whatever loop is running at call time.
                return get_session()

            session = asyncio.run_coroutine_threadsafe(_make_session(), loop).result(timeout=5)
            assert not session.closed
            assert len(hs._registry) == 1
            assert hs._registry[id(loop)][0] is loop

            await close_all()

            # Registry is emptied eagerly, before the foreign loop has run
            # the scheduled close — the session is still open at this point.
            assert len(hs._registry) == 0
            assert not session.closed

            # Drive the foreign loop until its scheduled close lands.
            async def _wait_closed() -> bool:
                for _ in range(200):
                    if session.closed:
                        return True
                    await asyncio.sleep(0.01)
                return session.closed

            closed = asyncio.run_coroutine_threadsafe(_wait_closed(), loop).result(timeout=5)
            assert closed is True
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()

    async def test_already_closed_sessions_are_skipped(self) -> None:
        session = get_session()
        await session.close()
        await close_all()  # must not raise on an already-closed session
        assert len(hs._registry) == 0


class TestRegistryKeyCollision:
    async def test_dead_loop_entry_is_not_reused_by_live_loop(self) -> None:
        """Guard against id() reuse: a dead loop's session must never leak.

        Simulates the address-reuse hazard directly by planting a bogus entry
        under the *current* loop's id but with a different loop object.
        """
        dead_loop = asyncio.new_event_loop()
        try:
            stale_session = aiohttp.ClientSession()
        finally:
            pass

        live_loop = asyncio.get_running_loop()
        hs._registry[id(live_loop)] = (dead_loop, stale_session)

        session = get_session()
        try:
            assert session is not stale_session
            assert not session.closed
            assert hs._registry[id(live_loop)][1] is session
        finally:
            await session.close()
            await stale_session.close()
            dead_loop.close()
