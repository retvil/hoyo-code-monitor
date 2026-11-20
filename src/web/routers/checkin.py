"""Check-in router: /checkins/* and /api/checkins/* routes."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.constants import MAX_CHECKIN_JITTER_MINUTES
from src.scheduler import create_scheduler_from_storage
from src.storage import Storage
from src.templates import templates
from src.web.app import _get_scheduler, _set_scheduler
from src.web_views import checkin_logs_with_names, page_ctx
from src.web_views import safe_detail as _safe_detail

router = APIRouter()


@router.get("/checkins", response_class=HTMLResponse)
async def checkins_page(request: Request) -> HTMLResponse:
    """Daily check-ins page: schedule settings, manual run, history."""
    storage = Storage()
    logs = checkin_logs_with_names(storage, limit=50)
    _scheduler = _get_scheduler()
    sched = _scheduler.status if _scheduler else None
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


@router.post("/checkins/run-now")
async def run_checkins_now() -> dict[str, Any]:
    """Run a daily check-in pass immediately (blocking work runs in a thread)."""
    if not _get_scheduler():
        _set_scheduler(create_scheduler_from_storage())
    sched = _get_scheduler()
    try:
        result = await asyncio.to_thread(sched.run_checkins_now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "result": result}


@router.post("/checkins/settings")
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


@router.get("/partials/checkin-logs")
async def partial_checkin_logs(request: Request, game: str = "", status: str = "") -> HTMLResponse:
    """HTMX partial for check-in history with filters."""
    storage = Storage()
    logs = checkin_logs_with_names(storage, limit=50, game=game or None, status=status or None)
    return templates.TemplateResponse(
        request,
        "partials/checkin_logs.html",
        page_ctx(storage, {"request": request, "logs": logs}),
    )


@router.get("/api/checkins/status")
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
    _scheduler = _get_scheduler()
    sched = _scheduler.status if _scheduler else None
    return {
        "date": today,
        "by_game": by_game,
        "last_checkin_run": sched.last_checkin_run if sched else None,
        "next_checkin_run": sched.next_checkin_run if sched else None,
    }


@router.get("/api/checkins/progress")
async def api_checkins_progress() -> dict[str, Any]:
    """Current check-in pass progress (empty dict when idle)."""
    sched = _get_scheduler()
    if sched is None:
        return {}
    progress: dict[str, Any] = sched.get_checkin_progress()
    return progress


@router.get("/partials/checkin-progress")
async def partial_checkin_progress(request: Request) -> HTMLResponse:
    """HTMX partial for live check-in progress (empty when idle)."""
    storage = Storage()
    progress: dict[str, Any] = {}
    sched = _get_scheduler()
    if sched is not None:
        progress = sched.get_checkin_progress()
    return templates.TemplateResponse(
        request,
        "partials/checkin_progress.html",
        page_ctx(storage, {"request": request, "progress": progress}),
    )
