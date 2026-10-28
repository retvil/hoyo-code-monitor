"""Web UI for HoYo Code Monitor using FastAPI + HTMX."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiohttp
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from src.config import ConfigManager
from src.constants import (
    APP_VERSION,
    MASK_VISIBLE_CHARS,
    MAX_CHECKIN_JITTER_MINUTES,
)
from src.http_session import close_all as close_http_sessions
from src.http_session import get_session
from src.i18n import get_lang, make_t
from src.scheduler import create_scheduler_from_storage
from src.sources import SOURCE_PRESETS, SourceConfig, SourceFetcher, seed_default_sources
from src.storage import Storage
from src.templates import templates
from src.version_check import check_for_update
from src.web_views import (
    account_checkin_switch_html,
    account_redeem_switch_html,
    checkin_logs_with_names,
    is_source_stale,
    page_ctx,
    source_health,
)
from src.web_views import (
    safe_detail as _safe_detail,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

logger = logging.getLogger(__name__)

# Rate limit for test_source
_TEST_RATE_LIMIT_TTL_SECONDS = 60.0
_test_rate_limit: dict[str, float] = {}
_RATE_LIMIT_SECONDS = 5.0

# Global scheduler instance
scheduler = None

# CSRF protection: state-changing routes require a valid X-CSRF-Token header.
#
# The token rotates at every UTC day boundary. A token that never expires gives
# anyone who ever observes it — a log line, a screenshot, a shared screen, a
# stale browser tab — an unlimited window in which to replay it. Deriving the
# token from the current UTC date bounds that window to a single day while
# needing no server-side state: every render within the same day agrees, and a
# restarted frozen build keeps working without re-seeding anything.
#
# Delivery is double-submit. The token is written to the non-HttpOnly
# ``hcm_csrf`` cookie on ``/api/csrf-token`` *and* embedded in every rendered
# page; the client echoes it back in the X-CSRF-Token header. Validation
# compares the header against the server's own secret, never against the
# cookie, so the cookie is a convenience for the client rather than the thing
# being trusted. A self-consistent attacker-forged header+cookie pair still
# fails, because the secret is only ever handed to a same-origin page.
_CSRF_SEED = secrets.token_urlsafe(32)
_CSRF_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_COOKIE = "hcm_csrf"


def _csrf_day() -> str:
    """Return the current CSRF epoch as a UTC date string (YYYY-MM-DD)."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _csrf_token() -> str:
    """Return the CSRF token for the current UTC day.

    Deterministically derived from the process seed and the date, so the value
    is stable across renders and restarts within a day and changes on its own
    at the UTC boundary without a timer or a stored rotation timestamp.
    """
    material = f"{_CSRF_SEED}|{_csrf_day()}".encode()
    return hashlib.sha256(material).hexdigest()[:43]


# Expose the token to every template as a global so each rendered page can
# embed it for the client-side HTMX listener, without touching each of the
# 14 TemplateResponse call sites. Passed as the *function*, not its result:
# Jinja calls it at render time, so the embedded token tracks rotation.
templates.env.globals["csrf_token"] = _csrf_token


def _verify_csrf(request: Request) -> None:
    """Validate CSRF token for state-changing requests.

    The token is a single server-side secret exposed to the page at render
    time; the browser echoes it back in the X-CSRF-Token header. The header
    is compared against the server secret, not against a client-supplied
    cookie, so a self-consistent header+cookie pair proves nothing.

    Raises 403 on failure.
    """
    origin = request.headers.get("origin", "")
    # Only compare scheme://host[:port]; a prefix match would let
    # "http://127.0.0.1:8000.evil.com" pass as "127.0.0.1:8000".
    expected_origin = f"{request.base_url.scheme}://{request.base_url.netloc}"
    if origin and origin.rstrip("/") != expected_origin:
        logger.warning("Blocked cross-origin state change from %s to %s", origin, request.url.path)
        raise HTTPException(status_code=403, detail="Origin not allowed")
    token = request.headers.get("x-csrf-token")
    if not token or not hmac.compare_digest(token, _csrf_token()):
        logger.warning("Blocked state change with invalid CSRF token from %s", request.url.path)
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler
    # Startup

    # Seed sources first so the UI is never empty before the first cycle.
    try:
        await seed_default_sources(Storage())
    except Exception:
        logger.exception("Failed to seed default sources on startup")

    # Tray mode injects its own already-running scheduler; only create one
    # when standalone (otherwise the dashboard would show a dead scheduler).
    if scheduler is None:
        scheduler = create_scheduler_from_storage()

    # Prime the update cache in the background so the first page render reads
    # a warm cache instead of paying for a GitHub round-trip. Deliberately not
    # awaited: a slow or unreachable GitHub must never delay startup.
    _spawn_background(_prime_update_cache())

    yield
    # Shutdown
    if scheduler and scheduler.is_running():
        scheduler.stop()
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
async def request_id_middleware(request: Request, call_next: Callable[[Request], Coroutine[Any, Any, Response]]) -> Response:
    """Attach a unique request ID for traceability."""
    request_id = secrets.token_urlsafe(16)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def csrf_middleware(request: Request, call_next: Callable[[Request], Coroutine[Any, Any, Response]]) -> Response:
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
    response = await call_next(request)
    return response


@app.get("/api/update", response_class=JSONResponse)
async def api_update() -> JSONResponse:
    """Return the latest release, checking GitHub only when the cache is stale.

    Non-forcing reads are free; a cold cache costs one GitHub round-trip, which
    the lifespan task has usually already paid by the time anyone asks.
    """
    update = await check_for_update()
    return JSONResponse(
        {
            "current": APP_VERSION,
            "latest": update.latest_version if update else APP_VERSION,
            "update_available": update is not None,
            "url": update.url if update else "",
            "release_notes": update.release_notes if update else "",
        }
    )


@app.get("/api/csrf-token")
async def csrf_token(request: Request) -> JSONResponse:
    """Return the current CSRF token and re-issue the double-submit cookie.

    The token is a server-side secret, embedded in each rendered page and
    echoed back by the client in the X-CSRF-Token header. It is also written
    to the non-HttpOnly ``hcm_csrf`` cookie so the client-side script can pick
    it up on an already-open tab after rotation, without needing a re-render.
    The header is still validated against the server secret, so the cookie is
    a delivery channel rather than the thing being trusted.

    The cookie is deliberately not HttpOnly: the page's own script must read
    it to echo the value back in the header.
    """
    token = _csrf_token()
    response = JSONResponse(content={"csrf_token": token})
    # Re-issued on every call so a client that has been open across the UTC
    # boundary refreshes its cookie from the same response that hands it the
    # matching token, keeping header and cookie in agreement.
    response.set_cookie(
        _CSRF_COOKIE,
        token,
        max_age=86400,
        samesite="strict",
        secure=request.base_url.scheme == "https",
    )
    return response


@app.post("/language")
async def set_language(language: str = Form(...)) -> dict[str, Any]:
    """Set UI language (en, ru, de, fr, ja, zh)."""
    from src.i18n import set_lang

    storage = Storage()
    try:
        set_lang(storage, language)
        return {"success": True, "language": language}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e


# Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, game: str = "") -> HTMLResponse:
    """Main dashboard (variant C: game summary cards + filter)."""
    from src.constants import GAME_CONF, GAMES

    storage = Storage()
    config_manager = ConfigManager()
    config = config_manager.get_all()
    current_game = game if game in GAMES else ""

    # Get stats (global or per game)
    stats = storage.get_stats(game=current_game or None)

    # Per-game summary cards (always show all games)
    game_cards = []
    for gid in GAMES:
        gs = storage.get_stats(game=gid)
        game_cards.append(
            {
                "id": gid,
                "name": GAME_CONF[gid]["name"],
                "accent": GAME_CONF[gid]["accent"],
                "total": gs["total_codes"],
                "redeemed": gs["successful"],
                "active": gid == current_game,
            }
        )

    # Get recent codes
    codes = storage.list_codes(limit=20, only_unredeemed=False, game=current_game or None)

    # Get redeemed codes (filtered by game, newest first by redemption time)
    redeemed_codes = [
        c for c in storage.list_codes(limit=200, game=current_game or None) if c.get("redeemed")
    ]
    redeemed_codes.sort(key=lambda c: c.get("redeemed_at") or "", reverse=True)

    # Get sources
    sources = storage.list_sources()

    # Get accounts
    accounts = storage.list_accounts()

    # Get redemption logs
    logs = storage.get_redemption_logs(limit=20)

    # Scheduler status
    sched_status = scheduler.status if scheduler else None

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        page_ctx(
            storage,
            {
                "request": request,
                "stats": stats,
                "game_cards": game_cards,
                "current_game": current_game,
                "codes": codes,
                "redeemed_codes": redeemed_codes,
                "sources": sources,
                "accounts": accounts,
                "logs": logs,
                "config": config,
                "scheduler": sched_status,
                "source_presets": {k: v.__dict__ for k, v in SOURCE_PRESETS.items()},
            },
        ),
    )


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request) -> HTMLResponse:
    """Sources management page."""
    storage = Storage()
    sources = storage.list_sources()
    return templates.TemplateResponse(
        request,
        "sources.html",
        page_ctx(
            storage,
            {
                "request": request,
                "sources": sources,
                "source_presets": {k: v.__dict__ for k, v in SOURCE_PRESETS.items()},
            },
        ),
    )


@app.post("/sources")
async def create_source(
    name: str = Form(...),
    url: str = Form(...),
    selector_type: str = Form("css"),
    selector: str = Form(...),
    enabled: bool = Form(True),
    headers: str = Form("{}"),
    timeout_seconds: int = Form(30),
    rate_limit_seconds: float = Form(1.0),
    requires_browser: bool = Form(False),
    browser_wait_selector: str | None = Form(None),
    browser_wait_seconds: int = Form(5),
    max_retries: int = Form(3),
    retry_base_delay: float = Form(1.0),
    game: str = Form("genshin"),
) -> dict[str, Any]:
    """Create a new source (accepts form-data from HTMX modal)."""
    storage = Storage()
    try:
        try:
            headers_dict = json.loads(headers) if headers else {}
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid headers JSON: {e}") from e
        storage.add_source(
            name=name,
            url=url,
            selector_type=selector_type,
            selector=selector,
            enabled=enabled,
            headers=headers_dict,
            timeout_seconds=timeout_seconds,
            rate_limit_seconds=rate_limit_seconds,
            requires_browser=requires_browser,
            browser_wait_selector=browser_wait_selector or None,
            browser_wait_seconds=browser_wait_seconds,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
        )
        return {"success": True, "message": f"Source '{name}' created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e


@app.post("/sources/{name}/enable")
async def enable_source(name: str) -> dict[str, Any]:
    """Enable a source."""
    storage = Storage()
    try:
        updated = storage.update_source(name, enabled=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    return {"success": True}


@app.post("/sources/{name}/disable")
async def disable_source(name: str) -> dict[str, Any]:
    """Disable a source."""
    storage = Storage()
    try:
        updated = storage.update_source(name, enabled=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    return {"success": True}


@app.delete("/sources/{name}")
async def delete_source(name: str) -> dict[str, Any]:
    """Delete a source."""
    storage = Storage()
    try:
        deleted = storage.delete_source(name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    return {"success": True}


@app.post("/sources/{name}/test")
async def test_source(name: str, request: Request) -> dict[str, Any]:
    """Test fetch from a source."""
    # Simple per-IP rate limit (local only)
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}:{name}"
    now = time.time()
    last = _test_rate_limit.get(key, 0)
    if now - last < _RATE_LIMIT_SECONDS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited, try in {_RATE_LIMIT_SECONDS - (now - last):.1f}s",
        )
    # Prune stale entries in place (TTL cleanup to prevent memory leak on long runs)
    for k in [key for key in _test_rate_limit if now - _test_rate_limit[key] >= _TEST_RATE_LIMIT_TTL_SECONDS]:
        del _test_rate_limit[k]
    _test_rate_limit[key] = now

    storage = Storage()
    source_data = storage.get_source(name)
    if not source_data:
        raise HTTPException(status_code=404, detail="Source not found")

    source = SourceConfig.from_row(source_data)

    try:
        async with SourceFetcher(storage) as fetcher:
            codes = await fetcher.fetch_source(source)
        return {"success": True, "codes": codes, "count": len(codes)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request) -> HTMLResponse:
    """Accounts management page."""
    storage = Storage()
    accounts = storage.list_accounts()
    for acc in accounts:
        cookies = storage.load_account_cookies(acc["name"]) or {}
        acc["has_cookies"] = bool(cookies.get("ltuid") and cookies.get("ltoken"))
    sched_status = scheduler.status if scheduler else None
    return templates.TemplateResponse(
        request,
        "accounts.html",
        page_ctx(
            storage,
            {
                "request": request,
                "accounts": accounts,
                "scheduler": sched_status,
            },
        ),
    )


@app.post("/accounts")
async def create_account(
    name: str = Form(...),
    uid: str = Form(...),
    region: str = Form(...),
    game_biz: str = Form("hk4e_global"),
    lang: str = Form("en-us"),
    s_lang_key: str = Form("en-us"),
    game: str = Form("genshin"),
) -> dict[str, Any]:
    """Create a new account (accepts form-data from HTMX modal)."""
    from src.constants import GAMES

    storage = Storage()
    if game not in GAMES:
        raise HTTPException(status_code=400, detail=f"Unknown game: {game}")
    try:
        storage.add_account(
            name=name,
            uid=uid,
            region=region,
            game_biz=game_biz,
            lang=lang,
            s_lang_key=s_lang_key,
            game=game,
        )
        return {"success": True, "message": f"Account '{name}' created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e


@app.post("/accounts/{name}/cookies")
async def set_account_cookies(name: str, cookies: str = Form(...)) -> dict[str, Any]:
    """Set cookies for an account (cookies as JSON string)."""
    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        cookies_dict = json.loads(cookies) if isinstance(cookies, str) else dict(cookies)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid cookies JSON: {e}") from e
    storage.store_account_cookies(name, cookies_dict)
    return {"success": True, "message": f"Cookies set for account '{name}'"}


@app.post("/accounts/{name}/login")
async def login_account(name: str, timeout: int = 300) -> dict[str, Any]:
    """Auto-capture cookies via browser login (opens browser on this PC)."""
    from src.cookies_login import capture_cookies

    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        cookies = await capture_cookies(timeout_seconds=timeout)
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=_safe_detail(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e)) from e
    except Exception as e:
        # e.g. playwright._impl._errors.Error (browser launch failure):
        # report the detail instead of a bare 500 page
        raise HTTPException(status_code=502, detail=f"Browser login failed: {e}") from e
    storage.store_account_cookies(name, cookies)
    return {"success": True, "message": f"Cookies saved for '{name}'", "keys": sorted(cookies)}


@app.get("/accounts/{name}/cookies")
async def get_account_cookies(name: str) -> HTMLResponse:
    """Get cookies for an account (masked)."""
    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    cookies = storage.load_account_cookies(name)
    if not cookies:
        return HTMLResponse("<span class='muted'>No cookies saved.</span>")

    parts = []
    for key, value in sorted(cookies.items()):
        if isinstance(value, str) and value:
            shown = (
                "*" * len(value)
                if len(value) <= MASK_VISIBLE_CHARS
                else value[:MASK_VISIBLE_CHARS] + "*" * (len(value) - MASK_VISIBLE_CHARS)
            )
        else:
            shown = value
        parts.append(
            f"<span class='badge badge-info'>{key}</span> <span class='mono'>{shown}</span>"
        )
    return HTMLResponse("<br>".join(parts))


@app.delete("/accounts/{name}")
async def delete_account(name: str) -> dict[str, Any]:
    """Delete an account."""
    storage = Storage()
    try:
        storage.delete_account(name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e))


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    """Configuration page."""
    storage = Storage()
    config_manager = ConfigManager()
    config = config_manager.get_all()
    return templates.TemplateResponse(
        request,
        "config.html",
        page_ctx(
            storage,
            {
                "request": request,
                "config": config,
            },
        ),
    )


@app.post("/config")
async def update_config(
    poll_interval_seconds: int = Form(900),
    source_timeout_seconds: int = Form(30),
    redemption_min_gap_seconds: int = Form(8),
    max_retry_attempts: int = Form(3),
    redemption_enabled: bool = Form(False),
    db_path: str = Form("data/monitor.db"),
    log_level: str = Form("INFO"),
    log_file: str = Form("logs/app.log"),
) -> dict[str, Any]:
    """Update configuration from settings form (form-data)."""
    config_manager = ConfigManager()
    try:
        values = {
            "poll_interval_seconds": poll_interval_seconds,
            "source_timeout_seconds": source_timeout_seconds,
            "redemption_min_gap_seconds": redemption_min_gap_seconds,
            "max_retry_attempts": max_retry_attempts,
            "redemption_enabled": redemption_enabled,
            "db_path": db_path,
            "log_level": log_level,
            "log_file": log_file,
        }
        for key, value in values.items():
            config_manager.set(key, value)
        return {"success": True, "message": "Settings saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e


@app.get("/author", response_class=HTMLResponse)
async def author_page(request: Request) -> HTMLResponse:
    """Author page with contacts and support options."""
    from src import author as author_module

    storage = Storage()
    raw = author_module.as_dict()
    author = {
        "name": raw.get("author_name", ""),
        "url": raw.get("author_url", ""),
        "telegram": raw.get("author_telegram", ""),
        "email": raw.get("author_email", ""),
        "github": raw.get("author_github", ""),
        "url_generic": raw.get("support_url", ""),
        "patreon": raw.get("support_patreon", ""),
        "boosty": raw.get("support_boosty", ""),
        "kofi": raw.get("support_kofi", ""),
        "donationalerts": raw.get("support_donationalerts", ""),
        "cloudtips": raw.get("support_cloudtips", ""),
        "donatepay": raw.get("support_donatepay", ""),
        "donate_stream": raw.get("support_donate_stream", ""),
        "donatty": raw.get("support_donatty", ""),
        "bitcoin": raw.get("support_bitcoin", ""),
        "ton": raw.get("support_ton", ""),
        "usdt": raw.get("support_usdt_trc20", ""),
        "usdt_erc20": raw.get("support_usdt_erc20", ""),
        "usdt_sol": raw.get("support_usdt_sol", ""),
    }
    return templates.TemplateResponse(
        request,
        "author.html",
        page_ctx(
            storage,
            {
                "request": request,
                "author": author,
                "has_any": author_module.has_any(),
            },
        ),
    )


@app.get("/author/qr")
async def author_qr(kind: str = "bitcoin") -> Response:
    """QR code PNG for a crypto address (generated locally, no external calls)."""
    from src import author as author_module

    data = author_module.as_dict()
    key = {
        "bitcoin": "support_bitcoin",
        "ton": "support_ton",
        "usdt": "support_usdt_trc20",
        "usdt_trc20": "support_usdt_trc20",
        "usdt_erc20": "support_usdt_erc20",
        "usdt_sol": "support_usdt_sol",
    }.get(kind, "support_bitcoin")
    address = data.get(key, "") or ""
    if not address:
        raise HTTPException(status_code=404, detail="Address not set")
    try:
        import qrcode
    except ImportError as e:
        raise HTTPException(status_code=503, detail="qrcode lib not installed") from e
    import io

    img = qrcode.make(address)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.post("/scheduler/start")
async def start_scheduler() -> dict[str, Any]:
    """Start the scheduler."""
    global scheduler
    if not scheduler:
        scheduler = create_scheduler_from_storage()
    try:
        if scheduler.start():
            return {"success": True, "message": "Scheduler started"}
        return {"success": False, "message": "Scheduler already running"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e))


@app.post("/scheduler/stop")
async def stop_scheduler() -> dict[str, Any]:
    """Stop the scheduler."""
    global scheduler
    if not scheduler:
        return {"success": False, "message": "Scheduler not initialized"}
    try:
        if scheduler.stop():
            return {"success": True, "message": "Scheduler stopped"}
        return {"success": False, "message": "Scheduler not running or timeout"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e))


@app.post("/scheduler/run-once")
async def run_once() -> dict[str, Any]:
    """Run a single check cycle."""
    global scheduler
    if not scheduler:
        scheduler = create_scheduler_from_storage()
    try:
        result = scheduler.run_once()
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e))


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    """Get scheduler status as JSON."""
    global scheduler
    if not scheduler:
        return {"running": False}
    status = scheduler.status
    return {
        "running": status.running,
        "next_run": status.next_run,
        "last_run": status.last_run,
        "last_run_success": status.last_run_success,
        "last_run_codes_found": status.last_run_codes_found,
        "last_run_codes_redeemed": status.last_run_codes_redeemed,
        "error_message": status.error_message,
    }


@app.get("/api/stats")
async def api_stats() -> dict[str, Any]:
    """Get statistics as JSON."""
    storage = Storage()
    return storage.get_stats()


@app.get("/api/sources/status")
async def api_sources_status() -> list[dict[str, Any]]:
    """Get status of all sources."""
    storage = Storage()
    sources = storage.list_sources()

    # Format for frontend consumption
    source_status = []
    for source in sources:
        source_status.append({
            "name": source["name"],
            "enabled": bool(source["enabled"]),
            "game": source.get("game", "unknown"),
            "last_checked": source.get("last_checked"),
            "last_success": source.get("last_success"),
            "error_count": source.get("error_count", 0),
            "status": "active" if source["enabled"] and source.get("last_success") else
                     "error" if source.get("error_count", 0) > 3 else
                     "warning" if is_source_stale(source.get("last_checked"))
                     else "unknown"
    })

    return source_status


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    storage = Storage()
    payload: dict[str, Any] = {
        "status": "healthy",
        "database": "ok",
        "scheduler": _safe_scheduler_status(),
        "sources": source_health(storage),
        "connectivity": "unknown",
    }
    db_error = False
    try:
        with storage._connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        payload["database"] = "error"
        payload["status"] = "unhealthy"
        payload["error"] = _safe_detail(exc)
        db_error = True

    if not db_error:
        try:
            # Borrow the pooled session instead of building one per probe: the
            # 5s budget is applied per request, so the shared session (and its
            # connection pool) survives the probe. See src/http_session.py.
            timeout = aiohttp.ClientTimeout(total=5)
            async with get_session().head(
                "https://api.telegram.org", timeout=timeout
            ) as resp:
                payload["connectivity"] = "ok" if resp.status < 500 else "degraded"
        except Exception as exc:
            payload["connectivity"] = "error"
            logger.debug("External connectivity check failed: %s", exc)

    if payload["sources"].get("state") == "missing" or any(
        source.get("state") == "error" for source in payload["sources"].get("sources", [])
    ):
        payload["status"] = "degraded"
    if payload["connectivity"] == "error":
        payload["status"] = "degraded"
    return payload


def _safe_scheduler_status() -> dict[str, Any]:
    """Return scheduler status without raising."""
    if scheduler is None:
        return {"state": "missing"}
    try:
        status = scheduler.status
        return {
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


@app.get("/partials/health", response_class=HTMLResponse)
async def partial_health() -> str:
    """HTMX partial: pretty health badge (machine JSON stays at /health)."""
    storage = Storage()
    try:
        with storage._connection() as conn:
            conn.execute("SELECT 1").fetchone()
        sources = storage.list_sources(enabled_only=True)
        scheduler_state = _safe_scheduler_status()
        if scheduler_state.get("state") == "missing":
            return (
                '<span class="badge badge-bad">Scheduler missing</span> '
                '<span class="muted">DB ok · Start the app to enable scheduling</span>'
            )
        return (
            '<span class="badge badge-ok">Healthy</span> '
            f'<span class="muted">DB ok · {len(sources)} active sources · scheduler {scheduler_state.get("state", "unknown")}</span>'
        )
    except Exception as e:
        return f'<span class="badge badge-bad">Unhealthy</span> <span class="muted">{e}</span>'


@app.get("/accounts/{name}/redeem-state", response_class=HTMLResponse)
async def account_redeem_state(name: str) -> str:
    """Current per-account auto-redeem switch HTML (for initial load)."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    return account_redeem_switch_html(name, storage.is_account_redeem_enabled(name))


@app.post("/accounts/{name}/redeem/toggle", response_class=HTMLResponse)
async def toggle_account_redeem(name: str) -> str:
    """Toggle per-account auto-redeem on/off, returns switch HTML."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    new_value = not storage.is_account_redeem_enabled(name)
    storage.set_account_redeem(name, new_value)
    return account_redeem_switch_html(name, new_value)


@app.get("/accounts/{name}/checkin-state", response_class=HTMLResponse)
async def account_checkin_state(name: str) -> str:
    """Current per-account auto-check-in switch HTML (for initial load)."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    return account_checkin_switch_html(name, storage.is_account_checkin_enabled(name))


@app.post("/accounts/{name}/checkin/toggle", response_class=HTMLResponse)
async def toggle_account_checkin(name: str) -> str:
    """Toggle per-account auto-check-in on/off, returns switch HTML."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    new_value = not storage.is_account_checkin_enabled(name)
    storage.set_account_checkin(name, new_value)
    return account_checkin_switch_html(name, new_value)


@app.get("/checkins", response_class=HTMLResponse)
async def checkins_page(request: Request) -> HTMLResponse:
    """Daily check-ins page: schedule settings, manual run, history."""
    storage = Storage()
    logs = checkin_logs_with_names(storage, limit=50)
    sched = scheduler.status if scheduler else None
    settings = {
        "enabled": storage.get_config("checkin_enabled", "true") == "true",
        "time": storage.get_config("checkin_time", "04:00") or "04:00",
        "jitter": storage.get_config("checkin_jitter_minutes", "15") or "15",
        "auto_refresh": storage.get_config("cookie_auto_refresh", "false") == "true",
    }
    checkin_status = {
        "last_checkin_run": sched.last_checkin_run if sched else None,
        "next_checkin_run": sched.next_checkin_run if sched else None,
    }
    return templates.TemplateResponse(
        request,
        "checkins.html",
        page_ctx(
            storage,
            {
                "request": request,
                "logs": logs,
                "checkin_settings": settings,
                "checkin_status": checkin_status,
            },
        ),
    )


@app.post("/checkins/run-now")
async def run_checkins_now() -> dict[str, Any]:
    """Run a daily check-in pass immediately (blocking work runs in a thread)."""
    global scheduler  # noqa: PLW0603 -- mirrors scheduler start/stop/run-once routes
    if not scheduler:
        scheduler = create_scheduler_from_storage()
    try:
        result = await asyncio.to_thread(scheduler.run_checkins_now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "result": result}


@app.post("/checkins/settings")
async def update_checkin_settings(
    checkin_enabled: bool = Form(False),
    checkin_time: str = Form("04:00"),
    checkin_jitter_minutes: int = Form(15),
    cookie_auto_refresh: bool = Form(False),
) -> dict[str, Any]:
    """Update daily check-in schedule settings (form-data)."""
    storage = Storage()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", (checkin_time or "").strip()):
        raise HTTPException(status_code=400, detail="checkin_time must be HH:MM")
    if not 0 <= checkin_jitter_minutes <= MAX_CHECKIN_JITTER_MINUTES:
        raise HTTPException(status_code=400, detail="jitter must be 0..120")
    storage.set_config("checkin_enabled", "true" if checkin_enabled else "false")
    storage.set_config("checkin_time", checkin_time.strip())
    storage.set_config("checkin_jitter_minutes", str(checkin_jitter_minutes))
    storage.set_config("cookie_auto_refresh", "true" if cookie_auto_refresh else "false")
    return {"success": True, "message": "Check-in settings saved"}


@app.get("/partials/checkin-logs")
async def partial_checkin_logs(
    request: Request, game: str = "", status: str = ""
) -> HTMLResponse:
    """HTMX partial for check-in history with filters."""
    storage = Storage()
    logs = checkin_logs_with_names(
        storage, limit=50, game=game or None, status=status or None
    )
    return templates.TemplateResponse(
        request,
        "partials/checkin_logs.html",
        page_ctx(storage, {"request": request, "logs": logs}),
    )


@app.get("/api/checkins/status")
async def api_checkins_status() -> dict[str, Any]:
    """Today's check-in summary per game as JSON."""
    storage = Storage()
    today = datetime.now().date().isoformat()
    logs = storage.get_checkin_logs(limit=500)
    by_game: dict[str, dict[str, int]] = {}
    for row in logs:
        if row.get("claimed_date") != today:
            continue
        entry = by_game.setdefault(row.get("game", "?"), {})
        entry[row.get("status", "?")] = entry.get(row.get("status", "?"), 0) + 1
    sched = scheduler.status if scheduler else None
    return {
        "date": today,
        "by_game": by_game,
        "last_checkin_run": sched.last_checkin_run if sched else None,
        "next_checkin_run": sched.next_checkin_run if sched else None,
    }


@app.get("/api/checkins/progress")
async def api_checkins_progress() -> dict[str, Any]:
    """Current check-in pass progress (empty dict when idle)."""
    if scheduler is None:
        return {}
    return scheduler.get_checkin_progress()


@app.get("/partials/checkin-progress")
async def partial_checkin_progress(request: Request) -> HTMLResponse:
    """HTMX partial for live check-in progress (empty when idle)."""
    storage = Storage()
    progress: dict[str, Any] = {}
    if scheduler is not None:
        progress = scheduler.get_checkin_progress()
    return templates.TemplateResponse(
        request,
        "partials/checkin_progress.html",
        page_ctx(storage, {"request": request, "progress": progress}),
    )


@app.post("/codes/{code}/redeem")
async def redeem_single_code(code: str) -> dict[str, Any]:
    """Redeem one code for all accounts with auto-redeem ON."""
    import asyncio

    from src.redeemer import Redeemer

    storage = Storage()
    row = storage.get_code(code.strip()) or storage.get_code(code.strip().upper())
    if not row:
        raise HTTPException(status_code=404, detail="Code not found")
    row_game = row.get("game") or "genshin"
    enabled = [a for a in storage.list_accounts() if storage.is_account_redeem_enabled(a["name"])]
    accounts = [a for a in enabled if (a.get("game") or "genshin") == row_game] or enabled
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts with auto-redeem enabled")
    gap = int(storage.get_config("redemption_min_gap_seconds", "8") or 8)
    results = []
    redeemer = Redeemer()
    async with redeemer:
        for acc in accounts:
            cookies = storage.load_account_cookies(acc["name"])
            try:
                from src.constants import GAME_CONF as _GC

                _ag = acc.get("game") or "genshin"
                res = await redeemer.redeem_code(
                    code=row["code"], cookies=cookies, uid=acc["uid"], region=acc["region"],
                    game_biz=acc.get("game_biz") or _GC.get(_ag, _GC["genshin"])["game_biz"],
                    lang=acc.get("lang", "en-us"), s_lang_key=acc.get("s_lang_key", "en-us"),
                    game=_ag,
                )
                claimed = res.success or res.raw_response.get("retcode") in (-2017, -2018)
                storage.update_code_redemption(
                    row["code"], claimed, res.reward if res.success else None, game=row_game
                )
                storage.add_redemption_log(
                    code=row["code"],
                    account_id=acc["id"],
                    status="success" if claimed else "failed",
                    reward=res.reward if res.success else None,
                    error_message=None
                    if claimed
                    else f"{res.message} (retcode {res.raw_response.get('retcode')})",
                )
                results.append(f"{acc['name']}: {'OK' if claimed else res.message}")
            except Exception as e:
                results.append(f"{acc['name']}: error {e}")
            await asyncio.sleep(gap)
    return {"success": True, "result": "; ".join(results)}


@app.delete("/codes/{code}")
async def delete_single_code(code: str) -> dict[str, Any]:
    """Delete a code (logs are kept for history)."""
    storage = Storage()
    if not storage.delete_code(code.strip()):
        raise HTTPException(status_code=404, detail="Code not found")
    return {"success": True}


@app.post("/codes/cleanup")
async def cleanup_dead() -> dict[str, Any]:
    """Delete unredeemed codes proven dead by API (expired/invalid)."""
    storage = Storage()
    count = storage.cleanup_dead_codes()
    return {"success": True, "result": f"Removed {count} dead codes"}


@app.post("/redeem/all")
async def redeem_all_codes() -> dict[str, Any]:
    """Redeem all unredeemed, non-expired codes for accounts with auto-redeem ON."""
    import asyncio

    from src.redeemer import Redeemer

    storage = Storage()
    accounts = [a for a in storage.list_accounts() if storage.is_account_redeem_enabled(a["name"])]
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts with auto-redeem enabled")
    codes = [
        c
        for c in storage.list_codes(limit=500, only_unredeemed=True)
        if c.get("display_status") in ("pending", "failed")
    ]
    if not codes:
        return {"success": True, "result": "Nothing to redeem"}
    gap = int(storage.get_config("redemption_min_gap_seconds", "8") or 8)
    done, failed = 0, 0
    redeemer = Redeemer()
    async with redeemer:
        for row in codes:
            row_game = row.get("game") or "genshin"
            matched = [a for a in accounts if (a.get("game") or "genshin") == row_game] or accounts
            for acc in matched:
                cookies = storage.load_account_cookies(acc["name"])
                try:
                    from src.constants import GAME_CONF as _GC2

                    _ag2 = acc.get("game") or "genshin"
                    res = await redeemer.redeem_code(
                        code=row["code"],
                        cookies=cookies,
                        uid=acc["uid"],
                        region=acc["region"],
                        game_biz=acc.get("game_biz") or _GC2.get(_ag2, _GC2["genshin"])["game_biz"],
                        lang=acc.get("lang", "en-us"),
                        s_lang_key=acc.get("s_lang_key", "en-us"),
                        game=_ag2,
                    )
                    claimed = res.success or res.raw_response.get("retcode") in (-2017, -2018)
                    storage.update_code_redemption(
                        row["code"], claimed, res.reward if res.success else None, game=row_game
                    )
                    storage.add_redemption_log(
                        code=row["code"],
                        account_id=acc["id"],
                        status="success" if claimed else "failed",
                        reward=res.reward if res.success else None,
                        error_message=None
                        if claimed
                        else f"{res.message} (retcode {res.raw_response.get('retcode')})",
                    )
                    if claimed:
                        done += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(gap)
    return {"success": True, "result": f"Redeemed: {done}, failed: {failed}"}


@app.get("/export")
async def export_data() -> dict[str, Any]:
    """Export codes + redemption state as JSON (backup / transfer)."""
    storage = Storage()
    codes = storage.list_codes(limit=10000)
    return {
        "app": "genshin-code-monitor",
        "version": 1,
        "codes": [
            {
                "code": c["code"],
                "sources": c.get("sources", []),
                "redeemed": bool(c.get("redeemed")),
                "reward": c.get("reward"),
                "attempted_at": c.get("attempted_at"),
                "redeemed_at": c.get("redeemed_at"),
                "game": c.get("game", "genshin"),
            }
            for c in codes
        ],
    }


@app.post("/import")
async def import_data(payload: str = Form(...)) -> dict[str, Any]:
    """Import codes JSON (merges, never overwrites redemption state)."""
    storage = Storage()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
    items = data.get("codes", []) if isinstance(data, dict) else []
    added, skipped = 0, 0
    for item in items:
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        existing = storage.get_code(code)
        if existing:
            skipped += 1
            continue
        try:
            for src in item.get("sources", ["import"]) or ["import"]:
                try:
                    storage.add_code(code, str(src), game=str(item.get("game", "genshin")))
                    break
                except Exception:
                    continue
            if item.get("redeemed"):
                storage.update_code_redemption(code, True, item.get("reward"))
            added += 1
        except Exception:
            skipped += 1
    return {"success": True, "result": f"Imported {added}, skipped {skipped}"}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    from src.logging_setup import get_prometheus_metrics

    metrics_data = get_prometheus_metrics()
    if metrics_data is None:
        raise HTTPException(status_code=503, detail="Prometheus client not available")
    from fastapi.responses import Response

    return Response(content=metrics_data, media_type="text/plain")


@app.get("/partials/scheduler-status")
async def partial_scheduler_status(request: Request) -> HTMLResponse:
    """HTMX partial for scheduler status."""
    global scheduler
    storage = Storage()
    lang = get_lang(storage)
    t_func = make_t(lang)
    if not scheduler:
        return templates.TemplateResponse(
            request,
            "partials/scheduler_status.html",
            {
                "request": request,
                "scheduler": None,
                "t": t_func,
            },
        )
    status = scheduler.status
    return templates.TemplateResponse(
        request,
        "partials/scheduler_status.html",
        {
            "request": request,
            "scheduler": status,
            "t": t_func,
        },
    )


@app.get("/partials/sparkline", response_class=HTMLResponse)
async def partial_sparkline(request: Request) -> HTMLResponse:
    """HTMX partial: SVG sparkline of codes found per day (last 14 days)."""
    storage = Storage()
    data = storage.codes_per_day(14)
    maximum = max([d["count"] for d in data] + [1])
    w, h, pad = 280, 64, 6
    n = max(len(data), 1)
    pts = []
    for i, d in enumerate(data):
        x = pad + (i * (w - 2 * pad) / max(n - 1, 1))
        y = h - pad - (d["count"] / maximum) * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    area = f"{pad},{h - pad} " + polyline + f" {w - pad},{h - pad}"
    bars = "".join(
        f"<circle cx='{x}' cy='{y}' r='2.5' fill='var(--accent)'><title>{d['day']}: {d['count']}</title></circle>"
        for (x, y), d in zip((p.split(",") for p in pts), data)
    )
    svg = (
        f"<svg viewBox='0 0 {w} {h}' style='width: 100%; height: auto;' role='img' "
        f"aria-label='Codes per day'>"
        f"<polygon points='{area}' fill='var(--accent-soft)'/>"
        f"<polyline points='{polyline}' fill='none' stroke='var(--accent)' stroke-width='2' "
        f"stroke-linejoin='round' stroke-linecap='round'/>{bars}</svg>"
    )
    total = sum(d["count"] for d in data)
    return templates.TemplateResponse(
        request,
        "partials/sparkline.html",
        page_ctx(storage, {"request": request, "svg": svg, "total": total}),
    )


@app.get("/partials/stats")
async def partial_stats(request: Request) -> HTMLResponse:
    """HTMX partial for statistics."""
    storage = Storage()
    stats = storage.get_stats()
    lang = get_lang(storage)
    t_func = make_t(lang)
    return templates.TemplateResponse(
        request,
        "partials/stats.html",
        {
            "request": request,
            "stats": stats,
            "t": t_func,
        },
    )


PAGE_SIZE = 20


@app.get("/partials/recent-codes")
async def partial_recent_codes(
    request: Request,
    page: int = 1,
    source: str = "",
    status: str = "all",
    q: str = "",
    game: str = "",
) -> HTMLResponse:
    """HTMX partial for codes table with filters + pagination."""
    from src.constants import GAMES

    storage = Storage()
    page = max(1, page)
    src = source or None
    st = status or "all"
    query = q.strip() or None
    gm = game if game in GAMES else None
    total = storage.count_codes(source=src, search=query, status=st, game=gm)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    codes = storage.list_codes(
        limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE, source=src, search=query, status=st, game=gm
    )
    sources = [s["name"] for s in storage.list_sources()]
    return templates.TemplateResponse(
        request,
        "partials/recent_codes.html",
        page_ctx(
            storage,
            {
                "request": request,
                "codes": codes,
                "page": page,
                "pages": pages,
                "total": total,
                "page_size": PAGE_SIZE,
                "f_source": source,
                "f_status": st,
                "f_q": q,
                "f_game": game,
                "all_sources": sources,
            },
        ),
    )


@app.get("/partials/recent-logs")
async def partial_recent_logs(request: Request) -> HTMLResponse:
    """HTMX partial for recent redemption logs."""
    storage = Storage()
    logs = storage.get_redemption_logs(limit=20)
    return templates.TemplateResponse(
        request,
        "partials/recent_logs.html",
        {
            "request": request,
            "logs": logs,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)
