"""FastAPI application factory: app object, lifespan, middlewares, routers.

The mutable scheduler state and shared helpers live here so every router can
pull a single source of truth for the live scheduler and for the
``Storage`` / seeding / scheduler-factory names that tests patch.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from src.constants import APP_VERSION
from src.http_session import close_all as close_http_sessions
from src.scheduler import Scheduler, create_scheduler_from_storage
from src.sources import seed_default_sources
from src.storage import Storage
from src.templates import templates
from src.version_check import check_for_update
from src.web.csrf import _CSRF_METHODS, _csrf_token, _verify_csrf

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

logger = logging.getLogger(__name__)

# Global scheduler instance, held in a mutable container instead of a module
# global: rebinding `scheduler` directly would trip ruff PLW0602/PLW0603, so
# the *internal* rebinds in the routes below go through `_set_scheduler`,
# which mirrors the value onto the module attribute in the same call. The
# module attribute remains the source of truth for *external* writers
# (cli.py's tray mode and tests' direct `web_ui.scheduler = ...` assignment),
# and `_get_scheduler` reads that same live attribute so those external sets
# are honored — without reintroducing a bare `global` statement.
_scheduler_box: list[Any] = [None]

scheduler: Scheduler | None = None


def _get_scheduler() -> Any:
    """Read the live scheduler (the module attribute, kept in sync by external sets)."""
    return scheduler


def _set_scheduler(value: Any) -> None:
    """Replace the live scheduler, keeping the container and module attribute in sync."""
    _scheduler_box[0] = value
    globals()["scheduler"] = value


#: Strong refs for fire-and-forget tasks. asyncio only keeps weak references
#: to running tasks, so an unreferenced one can be garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine to completion in the background, keeping a strong ref."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _prime_update_cache() -> None:
    """Warm the GitHub Releases cache without ever blocking startup."""
    try:
        await check_for_update()
    except Exception:  # pragma: no cover - check_for_update already swallows
        logger.warning("Update check failed", exc_info=True)


def _safe_scheduler_status() -> dict[str, Any]:
    """Return scheduler status without raising."""
    sched = _get_scheduler()
    if sched is None:
        return {"state": "missing"}
    try:
        status = sched.status
        result = {
            "state": "running" if status.running else "stopped",
            "last_run": status.last_run,
            "next_run": status.next_run,
            "last_run_success": status.last_run_success,
            "error": status.error_message,
            "checkin": {
                "last_run": status.last_checkin_run,
                "last_success": status.last_checkin_success,
                "next_run": status.next_checkin_run,
            },
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"state": "error", "error": str(exc)}
    else:
        return result


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Startup

    # Seed sources first so the UI is never empty before the first cycle.
    try:
        await seed_default_sources(Storage())
    except Exception:
        logger.exception("Failed to seed default sources on startup")

    # Tray mode injects its own already-running scheduler; only create one
    # when standalone (otherwise the dashboard would show a dead scheduler).
    if _get_scheduler() is None:
        _set_scheduler(create_scheduler_from_storage())

    if os.environ.get("HCM_TESTING") == "1":
        logger.warning(
            "HCM_TESTING=1 is set — CSRF protection is DISABLED. "
            "Remove this environment variable before deploying to production."
        )

    # Prime the update cache in the background so the first page render reads
    # a warm cache instead of paying for a GitHub round-trip. Deliberately not
    # awaited: a slow or unreachable GitHub must never delay startup.
    _spawn_background(_prime_update_cache())

    yield
    # Shutdown
    sched = _get_scheduler()
    if sched and sched.is_running():
        sched.stop()
    # Release every pooled aiohttp session. Components borrow rather than own
    # their sessions, so nothing else closes them; skipping this leaks a
    # connection pool (and its sockets) per event loop at shutdown.
    try:
        await close_http_sessions()
    except Exception:
        logger.debug("Error closing shared HTTP sessions", exc_info=True)


app = FastAPI(
    title="HoYo Code Monitor",
    description="Monitor and redeem Genshin Impact promotional codes",
    version=APP_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[Any, Any, Response]]
) -> Response:
    """Attach a unique request ID for traceability."""
    request_id = secrets.token_urlsafe(16)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def csrf_middleware(
    request: Request, call_next: Callable[[Request], Coroutine[Any, Any, Response]]
) -> Response:
    """Enforce CSRF protection on state-changing requests.

    HTTPException raised inside user middleware escapes Starlette's inner
    ExceptionMiddleware, so it would surface as a 500 via ServerErrorMiddleware.
    Return the rejection response directly instead of raising.
    """
    if request.method in _CSRF_METHODS and os.environ.get("HCM_TESTING") != "1":
        try:
            _verify_csrf(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


# Expose the CSRF token to every template as a global so each rendered page can
# embed it for the client-side HTMX listener, without touching each of the
# TemplateResponse call sites. Passed as the *function*, not its result:
# Jinja calls it at render time, so the embedded token tracks rotation.
templates.env.globals["csrf_token"] = _csrf_token


# Mount routers last, after all shared state and helpers above are defined,
# so the router modules' `from src.web.app import ...` lines resolve cleanly.
from src.web.routers.accounts import router as accounts_router  # noqa: E402
from src.web.routers.checkin import router as checkin_router  # noqa: E402
from src.web.routers.codes import router as codes_router  # noqa: E402
from src.web.routers.sources import router as sources_router  # noqa: E402
from src.web.routers.system import router as system_router  # noqa: E402

app.include_router(system_router)
app.include_router(sources_router)
app.include_router(accounts_router)
app.include_router(codes_router)
app.include_router(checkin_router)


def main() -> None:
    """Console entry point: run the web UI via uvicorn."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)


if __name__ == "__main__":
    main()
