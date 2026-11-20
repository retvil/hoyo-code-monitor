"""Sources router: /sources/* routes + /api/sources/status."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.sources import SourceConfig, SourceFetcher
from src.storage import Storage
from src.templates import templates
from src.web_views import page_ctx, source_status
from src.web_views import safe_detail as _safe_detail

router = APIRouter()

# Rate limit for test_source
_TEST_RATE_LIMIT_TTL_SECONDS = 60.0
_test_rate_limit: dict[str, float] = {}
_RATE_LIMIT_SECONDS = 5.0


@router.get("/sources", response_class=HTMLResponse)
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
            },
        ),
    )


@router.post("/sources")
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
            game=game,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "message": f"Source '{name}' created"}


@router.post("/sources/{name}/enable")
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


@router.post("/sources/{name}/disable")
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


@router.delete("/sources/{name}")
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


@router.post("/sources/{name}/test")
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
    stale = [k for k, v in _test_rate_limit.items() if now - v >= _TEST_RATE_LIMIT_TTL_SECONDS]
    for k in stale:
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
        return {"success": False, "error": _safe_detail(e)}


@router.get("/api/sources/status")
async def api_sources_status() -> list[dict[str, Any]]:
    """Get status of all sources."""
    storage = Storage()
    sources = storage.list_sources()

    # Format for frontend consumption
    statuses = []
    for source in sources:
        statuses.append(
            {
                "name": source["name"],
                "enabled": bool(source["enabled"]),
                "game": source.get("game", "unknown"),
                "last_checked": source.get("last_checked"),
                "last_success": source.get("last_success"),
                "error_count": source.get("error_count", 0),
                "status": source_status(source),
            }
        )

    return statuses
