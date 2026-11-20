"""Accounts router: /accounts/* routes + per-account state fragments."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.constants import MASK_VISIBLE_CHARS
from src.storage import Storage
from src.templates import templates
from src.web.app import _get_scheduler
from src.web_views import (
    account_checkin_switch_html,
    account_redeem_switch_html,
    page_ctx,
)
from src.web_views import (
    safe_detail as _safe_detail,
)

router = APIRouter()


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request) -> HTMLResponse:
    """Accounts management page."""
    storage = Storage()
    accounts = storage.list_accounts()
    for acc in accounts:
        cookies = storage.load_account_cookies(acc["name"]) or {}
        acc["has_cookies"] = bool(cookies.get("ltuid") and cookies.get("ltoken"))
        acc["cookie_expired"] = storage.get_account_cookie_state(acc["name"]) == "expired"
    sched = _get_scheduler()
    sched_status = sched.status if sched else None
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


@router.post("/accounts")
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
    from src.constants import (
        GAMES,
    )

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
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    else:
        return {"success": True, "message": f"Account '{name}' created"}


@router.post("/accounts/{name}/cookies")
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
    storage.set_account_cookie_state(name, "ok")
    return {"success": True, "message": f"Cookies set for account '{name}'"}


@router.post("/accounts/{name}/login")
async def login_account(name: str, timeout: int = 300) -> dict[str, Any]:
    """Auto-capture cookies via browser login (opens browser on this PC)."""
    from src.cookies_login import (
        capture_cookies,
    )

    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        cookies = await capture_cookies(timeout_seconds=timeout, account_slug=name)
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=_safe_detail(e)) from e
    except RuntimeError as e:
        # Playwright / Chromium launch failure. Show the raw detail (not
        # mask_secret-mangled) so the user can act on it — e.g. "Executable
        # doesn't exist at ...", "Playwright is not installed", "download failed".
        raise HTTPException(status_code=502, detail=f"Browser login failed: {e}") from e
    except Exception as e:
        # e.g. playwright._impl._errors.Error (browser launch failure):
        # report the detail instead of a bare 500 page
        raise HTTPException(status_code=502, detail=f"Browser login failed: {e}") from e
    storage.store_account_cookies(name, cookies)
    # A fresh browser login means the session is live again: clear any
    # "expired" marker so the UI badge drops.
    storage.set_account_cookie_state(name, "ok")
    return {"success": True, "message": f"Cookies saved for '{name}'", "keys": sorted(cookies)}


@router.get("/accounts/{name}/cookies")
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
        # User-supplied values (cookie names/values) must be escaped to prevent
        # reflected XSS via crafted cookie names like "<script>alert(1)</script>".
        key_escaped = __import__("html").escape(str(key))
        shown_escaped = __import__("html").escape(str(shown)) if shown is not None else ""
        parts.append(
            f"<span class='badge badge-info'>{key_escaped}</span> <span class='mono'>{shown_escaped}</span>"
        )
    return HTMLResponse("<br>".join(parts))


@router.delete("/accounts/{name}")
async def delete_account(name: str) -> dict[str, Any]:
    """Delete an account."""
    storage = Storage()
    try:
        storage.delete_account(name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_detail(e)) from e
    else:
        return {"success": True}


@router.get("/accounts/{name}/redeem-state", response_class=HTMLResponse)
async def account_redeem_state(name: str) -> str:
    """Current per-account auto-redeem switch HTML (for initial load)."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    return account_redeem_switch_html(name, storage.is_account_redeem_enabled(name))


@router.post("/accounts/{name}/redeem/toggle", response_class=HTMLResponse)
async def toggle_account_redeem(name: str) -> str:
    """Toggle per-account auto-redeem on/off, returns switch HTML."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    new_value = not storage.is_account_redeem_enabled(name)
    storage.set_account_redeem(name, new_value)
    return account_redeem_switch_html(name, new_value)


@router.get("/accounts/{name}/checkin-state", response_class=HTMLResponse)
async def account_checkin_state(name: str) -> str:
    """Current per-account auto-check-in switch HTML (for initial load)."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    return account_checkin_switch_html(name, storage.is_account_checkin_enabled(name))


@router.post("/accounts/{name}/checkin/toggle", response_class=HTMLResponse)
async def toggle_account_checkin(name: str) -> str:
    """Toggle per-account auto-check-in on/off, returns switch HTML."""
    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    new_value = not storage.is_account_checkin_enabled(name)
    storage.set_account_checkin(name, new_value)
    return account_checkin_switch_html(name, new_value)


@router.get("/accounts/{name}/games", response_class=HTMLResponse)
async def account_games_state(name: str) -> str:
    """Current per-account enabled-games checkboxes HTML (for initial load)."""
    from src.constants import (
        GAMES,
    )

    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_games_checkboxes_html(name, storage.get_account_games(name), GAMES)


@router.post("/accounts/{name}/games", response_class=HTMLResponse)
async def account_games_update(name: str, request: Request) -> str:
    """Update per-account enabled-games filter from the checkbox group."""
    from src.constants import (
        GAMES,
    )

    storage = Storage()
    if not storage.get_account(name):
        raise HTTPException(status_code=404, detail="Account not found")
    form = await request.form()
    picked = form.getlist("games")
    # Keep only ids we know, so a hand-edited form can't write arbitrary values.
    enabled = [g for g in picked if g in GAMES]
    # Empty selection means "no games" -> store None so the scheduler runs all
    # (NULL = "all games" default), matching the add-account form behaviour.
    updated = storage.update_account_games(name, enabled if enabled else None)
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return _account_games_checkboxes_html(name, storage.get_account_games(name), GAMES)


def _account_games_checkboxes_html(
    name: str, enabled: list[str] | None, games: tuple[str, ...]
) -> str:
    """Render the per-account "enabled games" checkbox group fragment.

    The form is wired for HTMX so the page-wide CSRF listener attaches the
    X-CSRF-Token header on submit.
    """
    boxes = []
    for g in games:
        checked = "" if enabled is None else ("checked" if g in enabled else "")
        boxes.append(
            f"<label style='display: flex; align-items: center; gap: 4px; margin-right: 8px;'>"
            f"<input type='checkbox' name='games' value='{g}' {checked} "
            f"style='width: 15px; height: 15px;'> {g}</label>"
        )
    # Account names are user-supplied; escape to prevent reflected XSS via
    # a crafted name like "<script>alert(1)</script>".
    name_escaped = __import__("html").escape(name)
    return (
        f"<div id='games-{name_escaped}'>"
        f"<form hx-post='/accounts/{name_escaped}/games' hx-target='#games-{name_escaped}' hx-swap='outerHTML'>"
        f"<button type='button' class='btn' style='padding: 2px 8px; font-size: 0.75rem;'>Games:</button> "
        + "".join(boxes)
        + "<button type='submit' class='btn btn-primary' "
        "style='padding: 2px 8px; font-size: 0.75rem;'>Save</button>"
        "</form></div>"
    )
