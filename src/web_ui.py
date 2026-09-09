"""Web UI for HoYo Code Monitor using FastAPI + HTMX."""

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
from src.constants import APP_AUTHOR, APP_VERSION, MASK_VISIBLE_CHARS
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
    title="HoYo Code Monitor",
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


def page_ctx(storage: Storage, extra: dict | None = None) -> dict:
    """Build template context with i18n + hardcoded author info (release build)."""
    from src import author as author_module

    lang = get_lang(storage)
    ctx: dict = {
        "t": make_t(lang),
        "lang": lang,
        "langs": SUPPORTED,
        "app_version": APP_VERSION,
        "app_author": APP_AUTHOR,
    }
    ctx.update(author_module.as_dict())
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
async def dashboard(request: Request, game: str = ""):
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


@app.get("/author", response_class=HTMLResponse)
async def author_page(request: Request):
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
        "bitcoin": raw.get("support_bitcoin", ""),
        "ton": raw.get("support_ton", ""),
        "usdt": raw.get("support_usdt_trc20", ""),
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
async def author_qr(kind: str = "bitcoin"):
    """QR code PNG for a crypto address (generated locally, no external calls)."""
    from src import author as author_module

    data = author_module.as_dict()
    key = {"bitcoin": "support_bitcoin", "ton": "support_ton", "usdt": "support_usdt_trc20"}.get(
        kind, "support_bitcoin"
    )
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


@app.post("/codes/{code}/redeem")
async def redeem_single_code(code: str):
    """Redeem one code for all accounts with auto-redeem ON."""
    import asyncio

    from src.redeemer import Redeemer

    storage = Storage()
    row = storage.get_code(code.upper().strip())
    if not row:
        raise HTTPException(status_code=404, detail="Code not found")
    accounts = [a for a in storage.list_accounts() if storage.is_account_redeem_enabled(a["name"])]
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts with auto-redeem enabled")
    gap = int(storage.get_config("redemption_min_gap_seconds", "8") or 8)
    results = []
    redeemer = Redeemer()
    async with redeemer:
        for acc in accounts:
            cookies = storage.load_account_cookies(acc["name"])
            try:
                res = await redeemer.redeem_code(
                    code=row["code"], cookies=cookies, uid=acc["uid"], region=acc["region"],
                    game_biz=acc.get("game_biz", "hk4e_global"),
                    lang=acc.get("lang", "en-us"), s_lang_key=acc.get("s_lang_key", "en-us"),
                )
                claimed = res.success or res.raw_response.get("retcode") in (-2017, -2018)
                storage.update_code_redemption(row["code"], claimed, res.reward if res.success else None)
                storage.add_redemption_log(
                    code=row["code"], account_id=acc["id"],
                    status="success" if claimed else "failed",
                    reward=res.reward if res.success else None,
                    error_message=None if claimed else f"{res.message} (retcode {res.raw_response.get('retcode')})",
                )
                results.append(f"{acc['name']}: {'OK' if claimed else res.message}")
            except Exception as e:
                results.append(f"{acc['name']}: error {e}")
            await asyncio.sleep(gap)
    return {"success": True, "result": "; ".join(results)}


@app.delete("/codes/{code}")
async def delete_single_code(code: str):
    """Delete a code (logs are kept for history)."""
    storage = Storage()
    if not storage.delete_code(code.upper().strip()):
        raise HTTPException(status_code=404, detail="Code not found")
    return {"success": True}


@app.post("/codes/cleanup")
async def cleanup_dead():
    """Delete unredeemed codes proven dead by API (expired/invalid)."""
    storage = Storage()
    count = storage.cleanup_dead_codes()
    return {"success": True, "result": f"Removed {count} dead codes"}


@app.post("/redeem/all")
async def redeem_all_codes():
    """Redeem all unredeemed, non-expired codes for accounts with auto-redeem ON."""
    import asyncio

    from src.redeemer import Redeemer

    storage = Storage()
    accounts = [a for a in storage.list_accounts() if storage.is_account_redeem_enabled(a["name"])]
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts with auto-redeem enabled")
    codes = [c for c in storage.list_codes(limit=500, only_unredeemed=True) if c.get("display_status") in ("pending", "failed")]
    if not codes:
        return {"success": True, "result": "Nothing to redeem"}
    gap = int(storage.get_config("redemption_min_gap_seconds", "8") or 8)
    done, failed = 0, 0
    redeemer = Redeemer()
    async with redeemer:
        for row in codes:
            for acc in accounts:
                cookies = storage.load_account_cookies(acc["name"])
                try:
                    res = await redeemer.redeem_code(
                        code=row["code"], cookies=cookies, uid=acc["uid"], region=acc["region"],
                        game_biz=acc.get("game_biz", "hk4e_global"),
                        lang=acc.get("lang", "en-us"), s_lang_key=acc.get("s_lang_key", "en-us"),
                    )
                    claimed = res.success or res.raw_response.get("retcode") in (-2017, -2018)
                    storage.update_code_redemption(row["code"], claimed, res.reward if res.success else None)
                    storage.add_redemption_log(
                        code=row["code"], account_id=acc["id"],
                        status="success" if claimed else "failed",
                        reward=res.reward if res.success else None,
                        error_message=None if claimed else f"{res.message} (retcode {res.raw_response.get('retcode')})",
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
async def export_data():
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
            }
            for c in codes
        ],
    }


@app.post("/import")
async def import_data(payload: str = Form(...)):
    """Import codes JSON (merges, never overwrites redemption state)."""
    storage = Storage()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
    items = data.get("codes", []) if isinstance(data, dict) else []
    added, skipped = 0, 0
    for item in items:
        code = str(item.get("code", "")).strip().upper()
        if not code:
            continue
        existing = storage.get_code(code)
        if existing:
            skipped += 1
            continue
        try:
            for src in item.get("sources", ["import"]) or ["import"]:
                try:
                    storage.add_code(code, str(src))
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


@app.get("/partials/sparkline", response_class=HTMLResponse)
async def partial_sparkline(request: Request):
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


PAGE_SIZE = 20


@app.get("/partials/recent-codes")
async def partial_recent_codes(
    request: Request,
    page: int = 1,
    source: str = "",
    status: str = "all",
    q: str = "",
    game: str = "",
):
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
