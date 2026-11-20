"""System router: dashboard, config, author, scheduler control, health, api, partials."""

from __future__ import annotations

import io
import logging
from typing import Any

import aiohttp
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from src.config import ConfigManager
from src.constants import APP_VERSION
from src.http_session import get_session
from src.i18n import get_lang, make_t
from src.scheduler import create_scheduler_from_storage
from src.storage import Storage
from src.templates import templates
from src.version_check import check_for_update
from src.web.app import (
    _get_scheduler,
    _safe_scheduler_status,
    _set_scheduler,
)
from src.web.csrf import _CSRF_COOKIE, _csrf_token
from src.web_views import page_ctx, source_health
from src.web_views import safe_detail as _safe_detail

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/update", response_class=JSONResponse)
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


@router.get("/api/csrf-token")
async def csrf_token(request: Request) -> JSONResponse:
    """Return the current CSRF token and re-issue the double-submit cookie.

    The token is a server-side secret, embedded in each rendered page and
    echoed back by the client in the X-CSRF-Token header. It is also written
    to the non-HttpOnly ``hcm_csrf`` cookie so the client-side script can pick
    it up on an already-open tab after rotation, without needing a re-render.
    The header is still validated against the server secret, so the cookie is
    a delivery channel rather than the thing being trusted.

    The cookie is deliberately **not** HttpOnly (httponly=False): the page's
    own script must read it to echo the value back in the header. The template
    also embeds the token in a <meta name="csrf-token"> tag as a fallback for
    tabs that were open before the most recent rotation.
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
        httponly=False,  # intentional: JS reads it to echo X-CSRF-Token
        samesite="strict",
        secure=request.base_url.scheme == "https",
    )
    return response


@router.post("/language")
async def set_language(language: str = Form(...)) -> dict[str, Any]:
    """Set UI language (en, ru, de, fr, ja, zh)."""
    from src.i18n import (
        set_lang,
    )

    storage = Storage()
    try:
        set_lang(storage, language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "language": language}


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, game: str = "") -> HTMLResponse:
    """Main dashboard (variant C: game summary cards + filter)."""
    from src.constants import (
        GAME_CONF,
        GAMES,
    )

    storage = Storage()
    config_manager = ConfigManager()
    config = config_manager.get_all()
    current_game = game if game in GAMES else ""

    # Get stats (global or per game)
    stats = storage.get_stats(game=current_game or None)

    # Per-game summary cards (always show all games) — one query instead of 5
    all_stats = storage.get_all_stats_single_query()
    game_cards = []
    for gid in GAMES:
        gs = all_stats.get(gid, {"total_codes": 0, "successful": 0, "failed": 0})
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
    redeemed_codes = storage.list_codes(
        limit=200, game=current_game or None, order_by_redeemed=True
    )
    redeemed_codes = [c for c in redeemed_codes if c.get("redeemed")]

    # Get sources
    sources = storage.list_sources()

    # Get accounts
    accounts = storage.list_accounts()

    # Get redemption logs
    logs = storage.get_redemption_logs(limit=20)

    # Scheduler status
    sched = _get_scheduler()
    sched_status = sched.status if sched else None

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
            },
        ),
    )


@router.get("/config", response_class=HTMLResponse)
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


@router.post("/config")
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

    # Validate paths before touching config: path-traversal / out-of-dir values
    # are rejected up front, so a bad input never reaches config_manager.set.
    from pathlib import Path

    from src.paths import app_data_dir

    app_data_dir_path = app_data_dir()

    def _validate_safe_path(value: str, setting: str) -> None:
        """Reject path-traversal and absolute paths outside the app data dir."""
        if ".." in value:
            raise HTTPException(
                status_code=400,
                detail=f"{setting} must not contain '..' (path traversal not allowed)",
            )
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve()
                app_data_dir_path.resolve()
                candidate.relative_to(app_data_dir_path)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"{setting} must be within the app data directory ({app_data_dir_path})",
                ) from None

    _validate_safe_path(db_path, "db_path")
    _validate_safe_path(log_file, "log_file")

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
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "message": "Settings saved"}


@router.get("/author", response_class=HTMLResponse)
async def author_page(request: Request) -> HTMLResponse:
    """Author page with contacts and support options."""
    from src import (
        author as author_module,
    )

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


@router.get("/author/qr")
async def author_qr(kind: str = "bitcoin") -> Response:
    """QR code PNG for a crypto address (generated locally, no external calls)."""
    from src import (
        author as author_module,
    )

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

    img = qrcode.make(address)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.post("/scheduler/start")
async def start_scheduler() -> dict[str, Any]:
    """Start the scheduler."""
    if not _get_scheduler():
        _set_scheduler(create_scheduler_from_storage())
    sched = _get_scheduler()
    try:
        if sched.start():
            result = {"success": True, "message": "Scheduler started"}
        else:
            result = {"success": False, "message": "Scheduler already running"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e)) from e
    else:
        return result


@router.post("/scheduler/stop")
async def stop_scheduler() -> dict[str, Any]:
    """Stop the scheduler."""
    sched = _get_scheduler()
    if not sched:
        return {"success": False, "message": "Scheduler not initialized"}
    try:
        if sched.stop():
            result = {"success": True, "message": "Scheduler stopped"}
        else:
            result = {"success": False, "message": "Scheduler not running or timeout"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e)) from e
    else:
        return result


@router.post("/scheduler/run-once")
async def run_once() -> dict[str, Any]:
    """Run a single check cycle."""
    if not _get_scheduler():
        _set_scheduler(create_scheduler_from_storage())
    sched = _get_scheduler()
    try:
        result = sched.run_once()
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "result": result}


@router.get("/api/status")
async def api_status() -> dict[str, Any]:
    """Get scheduler status as JSON."""
    sched = _get_scheduler()
    if not sched:
        return {"running": False}
    status = sched.status
    return {
        "running": status.running,
        "next_run": status.next_run,
        "last_run": status.last_run,
        "last_run_success": status.last_run_success,
        "last_run_codes_found": status.last_run_codes_found,
        "last_run_codes_redeemed": status.last_run_codes_redeemed,
        "error_message": status.error_message,
    }


@router.get("/api/stats")
async def api_stats() -> dict[str, Any]:
    """Get statistics as JSON."""
    storage = Storage()
    return storage.get_stats()


@router.get("/health")
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
            async with get_session().head("https://api.telegram.org", timeout=timeout) as resp:
                payload["connectivity"] = "ok" if resp.status < 500 else "degraded"
        except Exception as exc:
            payload["connectivity"] = "error"
            logger.debug("External connectivity check failed: %s", exc)

    sources_payload = payload["sources"]
    if sources_payload.get("error") or any(
        source.get("state") == "error" for source in sources_payload.get("sources", [])
    ):
        payload["status"] = "degraded"
    if payload["connectivity"] == "error":
        payload["status"] = "degraded"
    return payload


@router.get("/partials/health", response_class=HTMLResponse)
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


@router.get("/partials/scheduler-status")
async def partial_scheduler_status(request: Request) -> HTMLResponse:
    """HTMX partial for scheduler status."""
    sched = _get_scheduler()
    storage = Storage()
    lang = get_lang(storage)
    t_func = make_t(lang)
    if not sched:
        return templates.TemplateResponse(
            request,
            "partials/scheduler_status.html",
            {
                "request": request,
                "scheduler": None,
                "t": t_func,
            },
        )
    status = sched.status
    return templates.TemplateResponse(
        request,
        "partials/scheduler_status.html",
        {
            "request": request,
            "scheduler": status,
            "t": t_func,
        },
    )


@router.get("/partials/sparkline", response_class=HTMLResponse)
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
    _html = __import__("html")
    bars = "".join(
        f"<circle cx='{x}' cy='{y}' r='2.5' fill='var(--accent)'><title>{_html.escape(str(d['day']))}: {d['count']}</title></circle>"
        for (x, y), d in zip((p.split(",") for p in pts), data, strict=True)
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


@router.get("/partials/stats")
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
