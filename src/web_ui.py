"""Web UI for Genshin Code Monitor using FastAPI + HTMX."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.config import ConfigManager
from src.scheduler import create_scheduler_from_storage
from src.sources import SourceConfig, SourceFetcher, list_presets
from src.storage import Storage

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    # Startup
    storage = Storage()
    config = ConfigManager().load()
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
# app.mount("/static", StaticFiles(directory="static"), name="static")


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

    # Get sources
    sources = storage.list_sources()

    # Get accounts
    accounts = storage.list_accounts()

    # Get redemption logs
    logs = storage.get_redemption_logs(limit=20)

    # Scheduler status
    sched_status = scheduler.status if scheduler else None

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "codes": codes,
        "sources": sources,
        "accounts": accounts,
        "logs": logs,
        "config": config,
        "scheduler": sched_status,
        "source_presets": list_presets(),
    })


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    """Sources management page."""
    storage = Storage()
    sources = storage.list_sources()
    return templates.TemplateResponse("sources.html", {
        "request": request,
        "sources": sources,
        "source_presets": list_presets(),
    })


@app.post("/sources")
async def create_source(source: SourceCreate):
    """Create a new source."""
    storage = Storage()
    try:
        storage.add_source(
            name=source.name,
            url=source.url,
            selector_type=source.selector_type,
            selector=source.selector,
        )
        # Update additional fields via config
        if source.headers:
            storage.set_config(f"source_headers_{source.name}", json.dumps(source.headers))
        if source.timeout_seconds != 30:
            storage.set_config(f"source_timeout_{source.name}", str(source.timeout_seconds))
        if source.rate_limit_seconds != 1.0:
            storage.set_config(f"source_rate_limit_{source.name}", str(source.rate_limit_seconds))
        if source.requires_browser:
            storage.set_config(f"source_requires_browser_{source.name}", "true")
        if source.browser_wait_selector:
            storage.set_config(f"source_browser_wait_selector_{source.name}", source.browser_wait_selector)
        if source.browser_wait_seconds != 5:
            storage.set_config(f"source_browser_wait_seconds_{source.name}", str(source.browser_wait_seconds))
        if source.max_retries != 3:
            storage.set_config(f"source_max_retries_{source.name}", str(source.max_retries))
        if source.retry_base_delay != 1.0:
            storage.set_config(f"source_retry_base_delay_{source.name}", str(source.retry_base_delay))
        if not source.enabled:
            storage.disable_source(source.name)
        return {"success": True, "message": f"Source '{source.name}' created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sources/{name}/enable")
async def enable_source(name: str):
    """Enable a source."""
    storage = Storage()
    try:
        storage.enable_source(name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sources/{name}/disable")
async def disable_source(name: str):
    """Disable a source."""
    storage = Storage()
    try:
        storage.disable_source(name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/sources/{name}")
async def delete_source(name: str):
    """Delete a source."""
    storage = Storage()
    try:
        storage.remove_source(name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sources/{name}/test")
async def test_source(name: str):
    """Test fetch from a source."""
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
        headers=json.loads(storage.get_config(f"source_headers_{name}", "{}")),
        timeout_seconds=int(storage.get_config(f"source_timeout_{name}", "30")),
        rate_limit_seconds=float(storage.get_config(f"source_rate_limit_{name}", "1.0")),
        requires_browser=storage.get_config(f"source_requires_browser_{name}", "false").lower() == "true",
        browser_wait_selector=storage.get_config(f"source_browser_wait_selector_{name}"),
        browser_wait_seconds=int(storage.get_config(f"source_browser_wait_seconds_{name}", "5")),
        max_retries=int(storage.get_config(f"source_max_retries_{name}", "3")),
        retry_base_delay=float(storage.get_config(f"source_retry_base_delay_{name}", "1.0")),
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
    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "accounts": accounts,
    })


@app.post("/accounts")
async def create_account(account: AccountCreate):
    """Create a new account."""
    storage = Storage()
    try:
        storage.add_account(
            name=account.name,
            uid=account.uid,
            region=account.region,
            game_biz=account.game_biz,
            lang=account.lang,
            s_lang_key=account.s_lang_key,
        )
        return {"success": True, "message": f"Account '{account.name}' created"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/accounts/{name}/cookies")
async def set_account_cookies(name: str, cookies: dict = Form(...)):
    """Set cookies for an account."""
    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    storage.set_config(f"account_cookies_{name}", json.dumps(cookies))
    return {"success": True, "message": f"Cookies set for account '{name}'"}


@app.get("/accounts/{name}/cookies")
async def get_account_cookies(name: str):
    """Get cookies for an account (masked)."""
    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    cookies_json = storage.get_config(f"account_cookies_{name}")
    if not cookies_json:
        return {"cookies": {}}

    cookies = json.loads(cookies_json)
    masked = {}
    for key, value in cookies.items():
        if isinstance(value, str) and value:
            masked[key] = '*' * len(value) if len(value) <= 4 else value[:4] + '*' * (len(value) - 4)
        else:
            masked[key] = value
    return {"cookies": masked}


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
    config_manager = ConfigManager()
    config = config_manager.get_all()
    return templates.TemplateResponse("config.html", {
        "request": request,
        "config": config,
    })


@app.post("/config")
async def update_config(update: ConfigUpdate):
    """Update a configuration value."""
    config_manager = ConfigManager()
    try:
        config_manager.set(update.key, update.value)
        return {"success": True, "message": f"Set {update.key} = {update.value}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
