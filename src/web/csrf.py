"""CSRF protection for state-changing routes.

The token rotates at every UTC day boundary. A token that never expires gives
anyone who ever observes it — a log line, a screenshot, a shared screen, a
stale browser tab — an unlimited window in which to replay it. Deriving the
token from the current UTC date bounds that window to a single day while
needing no server-side state: every render within the same day agrees.

The seed is persisted to disk so that restarts within the same UTC day do
not invalidate tokens already issued to open browser tabs. It rotates
automatically at the UTC midnight boundary (the token itself changes even
if the seed is the same), and the stored seed is replaced on the next
startup after midnight so stale tabs eventually get a clean rejection.

Delivery is double-submit. The token is written to the non-HttpOnly
``hcm_csrf`` cookie on ``/api/csrf-token`` *and* embedded in every rendered
page; the client echoes it back in the X-CSRF-Token header. Validation
compares the header against the server's own secret, never against the
cookie, so the cookie is a convenience for the client rather than the thing
being trusted. A self-consistent attacker-forged header+cookie pair still
fails, because the secret is only ever handed to a same-origin page.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from contextlib import suppress
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from src.paths import app_data_dir

logger = logging.getLogger(__name__)

_CSRF_SEED_FILE = "_csrf_seed"
_CSRF_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_COOKIE = "hcm_csrf"


def _load_or_create_csrf_seed() -> str:
    """Load the persisted CSRF seed, or create and persist a new one.

    The seed survives process restarts so that tokens issued earlier in the
    same UTC day remain valid for open tabs. It is replaced on the next
    startup after the UTC day has changed (checked via the stored date).
    """
    seed_path = app_data_dir() / _CSRF_SEED_FILE
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        if seed_path.exists():
            raw = seed_path.read_text(encoding="utf-8").strip()
            # Format: "<date>|<seed>" — validate the date so a stale seed
            # from a previous day is replaced on next startup.
            if "|" in raw:
                stored_date, stored_seed = raw.split("|", 1)
                if stored_date == today and len(stored_seed) >= 32:
                    return stored_seed
    except Exception:
        logger.debug("Could not read CSRF seed file", exc_info=True)

    seed = secrets.token_urlsafe(32)
    try:
        seed_path.write_text(f"{today}|{seed}", encoding="utf-8")
        with suppress(OSError):
            seed_path.chmod(0o600)
    except Exception:
        logger.debug("Could not persist CSRF seed", exc_info=True)
    return seed


_CSRF_SEED: str = _load_or_create_csrf_seed()


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
