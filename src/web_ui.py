"""Web UI for Genshin Code Monitor using FastAPI + HTMX."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.config import ConfigManager
from src.constants import MASK_VISIBLE_CHARS
from src.exceptions import StorageError
from src.i18n import SUPPORTED, get_lang, make_t
from src.scheduler import create_scheduler_from_storage
from src.sources import SOURCE_PRESETS, SourceConfig, SourceFetcher, list_presets
from src.storage import Storage

logger = logging.getLogger(__name__)

# Rate limit for test_source
_test_rate_limit: dict[str, float] = {}
_RATE_LIMIT_SECONDS = 5.0

# Global scheduler instance
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    # Startup

    scheduler = create_scheduler_from_storage()
    yield
    # Shutdown
    if scheduler and scheduler.is_running():
        scheduler.stop()


app = FastAPI(
    title="Genshin Code Monitor",
    description="Monitor and redeem Genshin Impact promotional codes",
    version="0.1.0",
    lifespan=lifespan,
)

# Templates
templates = Jinja2Templates(directory="templates")

# Static files (if any)


# Pydantic models for API
class SourceCreate(BaseModel):
    name: str
    url: str
    selector_type: str
    selector: str
    enabled: bool = True
    headers: dict[str, str] = {}
    timeout_seconds: int = 30
    rate_limit_seconds: float = 1.0
    requires_browser: bool = False
    browser_wait_selector: str | None = None
    browser_wait_seconds: int = 5
    max_retries: int = 3
    retry_base_delay: float = 1.0


class AccountCreate(BaseModel):
    name: str
    uid: str
    region: str
    game_biz: str = "hk4e_global"
    lang: str = "en-us"
    s_lang_key: str = "en-us"


class ConfigUpdate(BaseModel):
    key: str
    value: Any


AUTHOR_KEYS = (
    "author_name",
    "author_url",
    "author_telegram",
    "author_email",
    "author_github",
    "support_url",
    "support_patreon",
    "support_boosty",
    "support_kofi",
    "support_donationalerts",
    "support_cloudtips",
    "support_donatepay",
    "support_bitcoin",
    "support_ton",
    "support_usdt_trc20",
)


def page_ctx(storage: Storage, extra: dict | None = None) -> dict:
    """Build template context with i18n + author info (local single-user UI)."""
    lang = get_lang(storage)
    ctx: dict = {
        "t": make_t(lang),
        "lang": lang,
        "langs": SUPPORTED,
    }
    for key in AUTHOR_KEYS:
        ctx[key] = storage.get_config(key, "") or ""
    if extra:
        ctx.update(extra)
    return ctx


@app.post("/language")
async def set_language(language: str = Form(...)):
    """Set UI language (en, ru, de, fr, ja, zh)."""
    from src.i18n import set_lang

    storage = Storage()
    try:
        set_lang(storage, language)
        return {"success": True, "language": language}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard."""
    storage = Storage()
    config_manager = ConfigManager()
    config = config_manager.get_all()

    # Get stats
    stats = storage.get_stats()

    # Get recent codes
    codes = storage.list_codes(limit=20, only_unredeemed=False)

    # Get redeemed codes (all, newest first by redemption time)
    redeemed_codes = [c for c in storage.list_codes(limit=200) if c.get("redeemed")]
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
async def sources_page(request: Request):
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
):
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
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/sources/{name}/enable")
async def enable_source(name: str):
    """Enable a source."""
    storage = Storage()
    try:
        updated = storage.update_source(name, enabled=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    return {"success": True}


@app.post("/sources/{name}/disable")
async def disable_source(name: str):
    """Disable a source."""
    storage = Storage()
    try:
        updated = storage.update_source(name, enabled=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    return {"success": True}


@app.delete("/sources/{name}")
async def delete_source(name: str):
    """Delete a source."""
    storage = Storage()
    try:
        deleted = storage.delete_source(name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Source '{name}' not found")
    return {"success": True}


@app.post("/sources/{name}/test")
async def test_source(name: str, request: Request):
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
    _test_rate_limit[key] = now

    storage = Storage()
    source_data = storage.get_source(name)
    if not source_data:
        raise HTTPException(status_code=404, detail="Source not found")

    source = SourceConfig(
        name=source_data["name"],
        url=source_data["url"],
        selector_type=source_data["selector_type"],
        selector=source_data["selector"],
        enabled=bool(source_data["enabled"]),
        headers=source_data.get("headers") or {},
        timeout_seconds=int(source_data.get("timeout_seconds") or 30),
        rate_limit_seconds=float(source_data.get("rate_limit_seconds") or 1.0),
        requires_browser=bool(source_data.get("requires_browser")),
        browser_wait_selector=source_data.get("browser_wait_selector"),
        browser_wait_seconds=int(source_data.get("browser_wait_seconds") or 5),
        max_retries=int(source_data.get("max_retries") or 3),
        retry_base_delay=float(source_data.get("retry_base_delay") or 1.0),
    )

    try:
        async with SourceFetcher(storage) as fetcher:
            codes = await fetcher.fetch_source(source)
        return {"success": True, "codes": codes, "count": len(codes)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request):
    """Accounts management page."""
    storage = Storage()
    accounts = storage.list_accounts()
    return templates.TemplateResponse(
        request,
        "accounts.html",
        page_ctx(
            storage,
            {
                "request": request,
                "accounts": accounts,
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
):
    """Create a new account (accepts form-data from HTMX modal)."""
    storage = Storage()
    try:
        storage.add_account(
            name=name,
            uid=uid,
            region=region,
            game_biz=game_biz,
            lang=lang,
            s_lang_key=s_lang_key,
        )
        return {"success": True, "message": f"Account '{name}' created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/accounts/{name}/cookies")
async def set_account_cookies(name: str, cookies: str = Form(...)):
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
async def login_account(name: str, timeout: int = 300):
    """Auto-capture cookies via browser login (opens browser on this PC)."""
    from src.cookies_login import capture_cookies

    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        cookies = await capture_cookies(timeout_seconds=timeout)
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    storage.store_account_cookies(name, cookies)
    return {"success": True, "message": f"Cookies saved for '{name}'", "keys": sorted(cookies)}


@app.get("/accounts/{name}/cookies")
async def get_account_cookies(name: str):
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
        parts.append(f"<span class='badge badge-info'>{key}</span> <span class='mono'>{shown}</span>")
    return HTMLResponse("<br>".join(parts))


@app.delete("/accounts/{name}")
async def delete_account(name: str):
    """Delete an account."""
    storage = Storage()
    try:
        storage.delete_account(name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
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
):
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
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/author")
async def update_author(
    author_name: str = Form(""),
    author_url: str = Form(""),
    support_url: str = Form(""),
    author_telegram: str = Form(""),
    author_email: str = Form(""),
    author_github: str = Form(""),
    support_patreon: str = Form(""),
    support_boosty: str = Form(""),
    support_bitcoin: str = Form(""),
    support_kofi: str = Form(""),
    support_donationalerts: str = Form(""),
    support_cloudtips: str = Form(""),
    support_donatepay: str = Form(""),
    support_ton: str = Form(""),
    support_usdt_trc20: str = Form(""),
):
    """Update author info (stored in local DB)."""
    storage = Storage()
    for key, value in {
        "author_name": author_name,
        "author_url": author_url,
        "support_url": support_url,
        "author_telegram": author_telegram,
        "author_email": author_email,
        "author_github": author_github,
        "support_patreon": support_patreon,
        "support_boosty": support_boosty,
        "support_kofi": support_kofi,
        "support_donationalerts": support_donationalerts,
        "support_cloudtips": support_cloudtips,
        "support_donatepay": support_donatepay,
        "support_bitcoin": support_bitcoin,
        "support_ton": support_ton,
        "support_usdt_trc20": support_usdt_trc20,
    }.items():
        storage.set_config(key, value.strip())
    return {"success": True, "message": "Author info saved"}


@app.get("/author/qr")
async def author_qr(kind: str = "bitcoin"):
    """QR code PNG for a crypto address (generated locally, no external calls)."""
    import io

    storage = Storage()
    key = {"bitcoin": "support_bitcoin", "ton": "support_ton", "usdt": "support_usdt_trc20"}.get(kind, "support_bitcoin")
    address = storage.get_config(key, "") or ""
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


@app.post("/scheduler/start")
async def start_scheduler():
    """Start the scheduler."""
    global scheduler
    if not scheduler:
        scheduler = create_scheduler_from_storage()
    try:
        if scheduler.start():
            return {"success": True, "message": "Scheduler started"}
        return {"success": False, "message": "Scheduler already running"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scheduler/stop")
async def stop_scheduler():
    """Stop the scheduler."""
    global scheduler
    if not scheduler:
        return {"success": False, "message": "Scheduler not initialized"}
    try:
        if scheduler.stop():
            return {"success": True, "message": "Scheduler stopped"}
        return {"success": False, "message": "Scheduler not running or timeout"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scheduler/run-once")
async def run_once():
    """Run a single check cycle."""
    global scheduler
    if not scheduler:
        scheduler = create_scheduler_from_storage()
    try:
        result = scheduler.run_once()
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status")
async def api_status():
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
async def api_stats():
    """Get statistics as JSON."""
    storage = Storage()
    return storage.get_stats()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    storage = Storage()
    try:
        # Check database
        with storage._connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "healthy", "database": "ok"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@app.get("/partials/health", response_class=HTMLResponse)
async def partial_health():
    """HTMX partial: pretty health badge (machine JSON stays at /health)."""
    storage = Storage()
    try:
        with storage._connection() as conn:
            conn.execute("SELECT 1").fetchone()
        sources = storage.list_sources(enabled_only=True)
        return (
            '<span class="badge badge-ok">Healthy</span> '
            f'<span class="muted">DB ok · {len(sources)} active sources</span>'
        )
    except Exception as e:
        return f'<span class="badge badge-bad">Unhealthy</span> <span class="muted">{e}</span>'


@app.get("/accounts/{name}/redeem-state", response_class=HTMLResponse)
async def account_redeem_state(name: str):
    """Current per-account auto-redeem switch HTML (for initial load)."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_redeem_switch_html(name, storage.is_account_redeem_enabled(name))


@app.post("/accounts/{name}/redeem/toggle", response_class=HTMLResponse)
async def toggle_account_redeem(name: str):
    """Toggle per-account auto-redeem on/off, returns switch HTML."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    new_value = not storage.is_account_redeem_enabled(name)
    storage.set_account_redeem(name, new_value)
    return _account_redeem_switch_html(name, new_value)


def _account_redeem_switch_html(name: str, enabled: bool) -> str:
    """Render per-account auto-redeem toggle switch (full span for outerHTML swap)."""
    checked = "checked" if enabled else ""
    label = "ON" if enabled else "OFF"
    cls = "badge-ok" if enabled else "badge-bad"
    return (
        f"<span id='redeem-{name}'>"
        f"<label style='display: flex; align-items: center; gap: 8px; cursor: pointer;'>"
        f"<input type='checkbox' {checked} style='width: 18px; height: 18px;' "
        f"hx-post='/accounts/{name}/redeem/toggle' hx-target='#redeem-{name}' hx-swap='outerHTML'>"
        f"<span class='badge {cls}'>{label}</span></label></span>"
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    from src.logging_setup import get_prometheus_metrics

    metrics_data = get_prometheus_metrics()
    if metrics_data is None:
        raise HTTPException(status_code=503, detail="Prometheus client not available")
    from fastapi.responses import Response

    return Response(content=metrics_data, media_type="text/plain")


@app.get("/partials/scheduler-status")
async def partial_scheduler_status(request: Request):
    """HTMX partial for scheduler status."""
    global scheduler
    if not scheduler:
        return templates.TemplateResponse(
            request,
            "partials/scheduler_status.html",
            {
                "request": request,
                "scheduler": None,
            },
        )
    status = scheduler.status
    return templates.TemplateResponse(
        request,
        "partials/scheduler_status.html",
        {
            "request": request,
            "scheduler": status,
        },
    )


@app.get("/partials/stats")
async def partial_stats(request: Request):
    """HTMX partial for statistics."""
    storage = Storage()
    stats = storage.get_stats()
    return templates.TemplateResponse(
        request,
        "partials/stats.html",
        {
            "request": request,
            "stats": stats,
        },
    )


@app.get("/partials/recent-codes")
async def partial_recent_codes(request: Request):
    """HTMX partial for recent codes."""
    storage = Storage()
    codes = storage.list_codes(limit=20, only_unredeemed=False)
    return templates.TemplateResponse(
        request,
        "partials/recent_codes.html",
        {
            "request": request,
            "codes": codes,
        },
    )


@app.get("/partials/recent-logs")
async def partial_recent_logs(request: Request):
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

    uvicorn.run(app, host="127.0.0.1", port=8000)
