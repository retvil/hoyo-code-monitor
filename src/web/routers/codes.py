"""Codes router: /codes/*, /redeem/all, /import, /export, recent partials."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.constants import GAMES
from src.storage import Storage
from src.templates import templates
from src.web_views import page_ctx

router = APIRouter()

PAGE_SIZE = 20


@router.post("/codes/{code}/redeem", response_model=None)
async def redeem_single_code(code: str, request: Request) -> dict[str, Any] | HTMLResponse:
    """Redeem one code for all accounts with auto-redeem ON."""
    from src.redeemer import (
        Redeemer,
    )

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
    results: list[dict[str, Any]] = []
    from src.web.services.redemption import RedemptionService

    redeemer = Redeemer()
    svc = RedemptionService(storage=storage, redeemer=redeemer)
    async with redeemer:
        for acc in accounts:
            try:
                claimed, msg = await svc.redeem_code_for_account(row["code"], acc)
                results.append(
                    {
                        "account": acc["name"],
                        "ok": claimed,
                        "msg": "OK" if claimed else msg,
                    }
                )
            except Exception as e:
                results.append({"account": acc["name"], "ok": False, "msg": str(e)})
            await asyncio.sleep(gap)
    any_success = any(r["ok"] for r in results)

    # When called via HTMX, return a styled HTML fragment instead of raw JSON
    # so the swap renders a readable result next to the button.
    if request.headers.get("HX-Request") == "true":
        from src.web.fragments import render_result_fragment

        return HTMLResponse(content=render_result_fragment(results, any_success))

    return {
        "success": any_success,
        "result": "; ".join(f"{r['account']}: {'OK' if r['ok'] else r['msg']}" for r in results),
    }


@router.delete("/codes/{code}")
async def delete_single_code(code: str) -> dict[str, Any]:
    """Delete a code (logs are kept for history)."""
    storage = Storage()
    if not storage.delete_code(code.strip()):
        raise HTTPException(status_code=404, detail="Code not found")
    return {"success": True}


@router.post("/codes/cleanup")
async def cleanup_dead() -> dict[str, Any]:
    """Delete unredeemed codes proven dead by API (expired/invalid)."""
    storage = Storage()
    count = storage.cleanup_dead_codes()
    return {"success": True, "result": f"Removed {count} dead codes"}


@router.post("/redeem/all", response_model=None)
async def redeem_all_codes(request: Request) -> dict[str, Any] | HTMLResponse:
    """Redeem all unredeemed, non-expired codes for accounts with auto-redeem ON."""
    from src.redeemer import (
        Redeemer,
    )

    storage = Storage()
    accounts = [a for a in storage.list_accounts() if storage.is_account_redeem_enabled(a["name"])]
    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts with auto-redeem enabled")
    codes = [
        c
        for c in storage.list_codes(limit=500, only_unredeemed=True)
        if c.get("display_status") == "pending"
    ]
    if not codes:
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(content='<span class="redeem-result-ok">Nothing to redeem</span>')
        return {"success": True, "result": "Nothing to redeem"}
    gap = int(storage.get_config("redemption_min_gap_seconds", "8") or 8)
    done, failed = 0, 0
    from src.web.services.redemption import RedemptionService

    redeemer = Redeemer()
    svc = RedemptionService(storage=storage, redeemer=redeemer)
    async with redeemer:
        for row in codes:
            row_game = row.get("game") or "genshin"
            matched = [a for a in accounts if (a.get("game") or "genshin") == row_game] or accounts
            for acc in matched:
                try:
                    claimed, _ = await svc.redeem_code_for_account(row["code"], acc)
                    if claimed:
                        done += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(gap)
    result_text = f"Redeemed: {done}, failed: {failed}"
    ok = failed == 0

    if request.headers.get("HX-Request") == "true":
        from src.web.fragments import render_summary_fragment

        return HTMLResponse(content=render_summary_fragment(result_text, ok))

    return {"success": True, "result": result_text}


@router.get("/export")
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


@router.post("/import")
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
        game_raw = item.get("game", "genshin") or "genshin"
        if game_raw not in GAMES:
            # An item referencing an unknown game is unimportable; skip it.
            skipped += 1
            continue
        try:
            for src in item.get("sources", ["import"]) or ["import"]:
                try:
                    storage.add_code(code, str(src), game=game_raw)
                    break
                except Exception:
                    continue
            if item.get("redeemed"):
                storage.update_code_redemption(code, True, item.get("reward"))
            added += 1
        except Exception:
            skipped += 1
    return {"success": True, "result": f"Imported {added}, skipped {skipped}"}


@router.get("/partials/recent-codes")
async def partial_recent_codes(
    request: Request,
    page: int = 1,
    source: str = "",
    status: str = "all",
    q: str = "",
    game: str = "",
) -> HTMLResponse:
    """HTMX partial for codes table with filters + pagination."""
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


@router.get("/partials/recent-logs")
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
