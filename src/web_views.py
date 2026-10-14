"""View helpers and request/response models for the FastAPI web UI.

This module intentionally contains no FastAPI app instance and no mutable
scheduler state. Route handlers stay in :mod:`src.web_ui`, preserving the
existing ``src.web_ui.Storage`` and ``src.web_ui.scheduler`` monkeypatch
surface used by the tray entry point and tests.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from src import author as author_module
from src.constants import APP_AUTHOR, APP_VERSION, GAME_CONF
from src.i18n import SUPPORTED, get_lang, make_t
from src.version_check import UpdateInfo, cached_update

if TYPE_CHECKING:
    from src.storage import Storage

logger = logging.getLogger(__name__)

SOURCE_STALE_SECONDS: int = 3600


class SourceCreate(BaseModel):
    """JSON request model for source creation clients."""

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
    """JSON request model for account creation clients."""

    name: str
    uid: str
    region: str
    game_biz: str = "hk4e_global"
    lang: str = "en-us"
    s_lang_key: str = "en-us"


class ConfigUpdate(BaseModel):
    """JSON request model for a single configuration update."""

    key: str
    value: Any


def mask_secret(value: str, visible: int = 4) -> str:
    """Mask a secret string, showing only its tail."""
    if not value or len(value) <= visible * 2:
        return "*" * max(len(value), 4)
    return f"{'*' * visible}{value[-visible:]}"


def safe_detail(exc: BaseException) -> str:
    """Return an exception detail safe to send to a browser client."""
    return mask_secret(str(exc))


def page_ctx(storage: Storage, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build template context with i18n, author details, and game metadata."""
    lang = get_lang(storage)
    accounts = storage.list_accounts()
    games_with_account = {account.get("game") or "genshin" for account in accounts}
    context: dict[str, Any] = {
        "t": make_t(lang),
        "lang": lang,
        "langs": SUPPORTED,
        "app_version": APP_VERSION,
        "app_author": APP_AUTHOR,
        "current_game": "",
        "game_accents": {
            game_id: {
                "accent": config["accent"],
                "accent_soft": config.get("accent_soft", "#ede9fe"),
                "short": config.get("short", game_id.upper()),
                "name": config.get("name", game_id),
            }
            for game_id, config in GAME_CONF.items()
        },
        "games_with_account": games_with_account,
        "gift_urls": {game_id: config["gift_url"] for game_id, config in GAME_CONF.items()},
    }
    context.update(author_module.as_dict())
    # Update checks are primed in the FastAPI lifespan background task. This
    # only reads the cache, so rendering a page never waits on GitHub.
    context.update(update_ctx(cached_update(), lang))
    if extra:
        context.update(extra)
    return context


def is_source_stale(last_checked: str | None) -> bool:
    """Check if a source is stale (not checked for over an hour).

    Returns False on missing or malformed timestamps instead of raising.
    """
    if not last_checked:
        return False
    try:
        checked_at = datetime.fromisoformat(last_checked)
        if checked_at.tzinfo is not None:
            # Normalize aware timestamps to local naive time so the
            # subtraction below cannot raise on mixed naive/aware operands.
            checked_at = checked_at.astimezone().replace(tzinfo=None)
        age_seconds = (datetime.now() - checked_at).total_seconds()
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed last_checked %r", last_checked)
        return False
    return age_seconds > SOURCE_STALE_SECONDS


def update_ctx(update: UpdateInfo | None, lang: str) -> dict[str, Any]:
    """Return localized update banner data, or an empty context.

    Args:
        update: A newer GitHub release, if one was found.
        lang: Already-resolved UI language from the active storage config.
    """
    if update is None:
        return {
            "update_available": False,
            "update_message": "",
            "update_latest": "",
            "update_current": APP_VERSION,
            "update_url": "",
            "update_notes_text": "",
        }
    return {
        "update_available": True,
        "update_message": make_t(lang)("update_available")
        .replace("{{latest}}", update.latest_version)
        .replace("{{current}}", update.current_version),
        "update_latest": update.latest_version,
        "update_current": update.current_version,
        "update_url": update.url,
        "update_notes_text": update.release_notes,
    }


def source_health(storage: Storage) -> dict[str, Any]:
    """Return enabled sources health summary without raising."""
    try:
        sources = storage.list_sources(enabled_only=True)
        health: list[dict[str, Any]] = []
        for source in sources:
            checked_at = source.get("last_checked")
            stale = is_source_stale(checked_at)
            health.append(
                {
                    "name": source.get("name", "unknown"),
                    "last_checked": checked_at,
                    "last_success": source.get("last_success"),
                    "error_count": source.get("error_count", 0),
                    "state": (
                        "active"
                        if source.get("last_success") and not stale
                        else "warning" if stale else "idle"
                    ),
                }
            )
        return {
            "count": len(sources),
            "sources": health,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"count": 0, "sources": [], "error": str(exc)}


def account_redeem_switch_html(name: str, enabled: bool) -> str:
    """Render the per-account auto-redeem HTMX switch fragment."""
    checked = "checked" if enabled else ""
    label = "ON" if enabled else "OFF"
    css_class = "badge-ok" if enabled else "badge-bad"
    return (
        f"<span id='redeem-{name}'>"
        f"<label style='display: flex; align-items: center; gap: 8px; cursor: pointer;'>"
        f"<input type='checkbox' {checked} style='width: 18px; height: 18px;' "
        f"hx-post='/accounts/{name}/redeem/toggle' hx-target='#redeem-{name}' hx-swap='outerHTML'>"
        f"<span class='badge {css_class}'>{label}</span></label></span>"
    )


def account_checkin_switch_html(name: str, enabled: bool) -> str:
    """Render the per-account auto-checkin HTMX switch fragment."""
    checked = "checked" if enabled else ""
    label = "ON" if enabled else "OFF"
    css_class = "badge-ok" if enabled else "badge-bad"
    return (
        f"<span id='checkin-{name}'>"
        f"<label style='display: flex; align-items: center; gap: 8px; cursor: pointer;'>"
        f"<input type='checkbox' {checked} style='width: 18px; height: 18px;' "
        f"hx-post='/accounts/{name}/checkin/toggle' hx-target='#checkin-{name}' hx-swap='outerHTML'>"
        f"<span class='badge {css_class}'>{label}</span></label></span>"
    )


def checkin_logs_with_names(storage: Storage, **filters: Any) -> list[dict[str, Any]]:
    """Return checkin logs with account names attached for templates."""
    logs = storage.get_checkin_logs(**filters)
    names = {account["id"]: account["name"] for account in storage.list_accounts()}
    for row in logs:
        row["account_name"] = names.get(row["account_id"], f"id:{row['account_id']}")
    return logs
