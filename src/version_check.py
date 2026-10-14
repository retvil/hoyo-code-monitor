"""Read-only GitHub Releases update check.

This app otherwise makes no outbound calls beyond the sources the user
configures. This module is the single, explicit, user-visible exception: one
GET to the public GitHub Releases API to learn whether a newer version exists.

Contract:
- **Read-only.** No token, no writes, no telemetry, no device identifiers.
- **Never raises.** Every failure path returns ``None``; the banner stays
  hidden and the rest of the app is unaffected.
- **Cached.** At most one request per ``UPDATE_CHECK_INTERVAL_SECONDS``,
  including failed attempts, so an unreachable network cannot turn into a
  request per page render.
- **Disableable.** ``update_check_enabled = false`` in config, or dismiss the
  banner in the UI.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from src.constants import (
    APP_VERSION,
    HTTP_OK,
    RELEASES_API_URL,
    RELEASES_PAGE_URL,
    UPDATE_CHECK_INTERVAL_SECONDS,
    UPDATE_CHECK_TIMEOUT_SECONDS,
)
from src.http_session import get_session

logger = logging.getLogger(__name__)

# Release notes are shown verbatim in a banner; keep them banner-sized.
MAX_NOTES_CHARS: int = 400

# Inline Markdown syntax stripped from release notes before display. The banner
# renders notes as plain text, so these only make the sentence readable.
# MULTILINE so headings/lists/quotes are stripped on every line, not just the
# first: notes are still multi-line at this point and are collapsed afterwards.
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*)(.+?)\1", re.DOTALL)
_MD_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_MD_INLINE_CODE = re.compile(r"`+([^`]*)`+")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)

_REQUEST_HEADERS: dict[str, str] = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"hoyo-code-monitor/{APP_VERSION}",
}


@dataclass(frozen=True)
class UpdateInfo:
    """Result of a successful check that found a newer release."""

    latest_version: str
    current_version: str
    url: str
    release_notes: str


def parse_version(raw: str) -> tuple[int, ...]:
    """Parse a version string into a comparable integer tuple.

    Tolerates a leading ``v``, a ``-beta.1`` pre-release suffix, and
    non-numeric components. Returns an empty tuple when nothing numeric is
    found, which sorts below every real version.
    """
    if not raw:
        return ()
    core = raw.strip().lstrip("vV").split("-", 1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if digits:
            parts.append(int(digits))
        else:
            # A component like "x" or "" carries no ordering information;
            # treat it as 0 so 1.x still compares against 1.0.
            parts.append(0)
    return tuple(parts)


def compare_versions(left: str, right: str) -> int:
    """Compare two version strings. Returns -1, 0 or 1."""
    a = parse_version(left)
    b = parse_version(right)
    # Pad to equal length so "1.2" == "1.2.0" and "1.2" < "1.2.1".
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is strictly newer than ``current``."""
    return compare_versions(latest, current) > 0


def _is_prerelease(version: str) -> bool:
    """True when the running build is itself a pre-release."""
    return "-" in version.strip().lstrip("vV")


def _clean_notes(raw: Any) -> str:
    """Trim release notes to a banner-friendly single paragraph.

    Release notes are Markdown authored upstream, and the banner renders them
    as plain text. Stripping the common inline syntax keeps the sentence
    readable instead of showing literal ``###`` and ``**``. Rendering them as
    text (never as HTML) also means no markdown-injection surface.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    text = _MD_HEADING.sub("", text)  # leading ### / ## / #
    text = _MD_EMPHASIS.sub(r"\2", text)  # **bold** / *italic* / __bold__
    text = _MD_STRIKE.sub(r"\1", text)  # ~~strike~~
    text = _MD_INLINE_CODE.sub(r"\1", text)  # `code`
    text = _MD_IMAGE.sub("", text)  # ![alt](url) - alt is redundant here
    text = _MD_LINK.sub(r"\1", text)  # [text](url) -> text
    text = _MD_LIST_MARKER.sub("", text)  # leading "- " / "* " / "1. "
    text = _MD_BLOCKQUOTE.sub("", text)  # leading "> "
    text = " ".join(text.split())  # collapse newlines and runs of spaces
    if len(text) <= MAX_NOTES_CHARS:
        return text
    return text[: MAX_NOTES_CHARS - 1].rstrip() + "…"


# id(loop) -> (checked_at, result). Guarded because the scheduler thread and
# the web thread can both trigger a check.
_cache: dict[int, tuple[float, UpdateInfo | None]] = {}
_cache_lock = threading.Lock()

# Per-loop in-flight guard, so concurrent page renders issue at most one
# request instead of stampeding the API. Mirrors the session-pool keying.
_inflight: set[int] = set()


def _cache_key() -> int:
    """Key the cache per event loop, mirroring the HTTP session pool."""
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        # Called outside a loop (sync context): use a stable sentinel.
        return -1


def cached_update() -> UpdateInfo | None:
    """Return the cached update info if it is still fresh, else ``None``.

    A fresh entry holding ``None`` means "checked recently and there was
    nothing to report" — that is a real answer, not a cache miss.
    """
    key = _cache_key()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        checked_at, result = entry
        if (time.monotonic() - checked_at) >= UPDATE_CHECK_INTERVAL_SECONDS:
            del _cache[key]
            return None
        return result


def _has_fresh_entry() -> bool:
    """True when a fresh (non-expired) cache entry exists for this loop.

    Distinguishes "checked recently, nothing to report" — a real answer stored
    as ``None`` — from "never checked", which the plain ``cached_update()``
    cannot express because ``None`` is its miss signal too.
    """
    key = _cache_key()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return False
        checked_at, _result = entry
        return (time.monotonic() - checked_at) < UPDATE_CHECK_INTERVAL_SECONDS


def reset_cache() -> None:
    """Drop every cached result. Intended for tests."""
    with _cache_lock:
        _cache.clear()
        _inflight.clear()


def _store(result: UpdateInfo | None) -> None:
    with _cache_lock:
        _cache[_cache_key()] = (time.monotonic(), result)


async def _fetch_release() -> dict[str, Any] | None:
    """GET the latest-release payload. Returns ``None`` on any failure."""
    try:
        session = get_session()
        async with session.get(
            RELEASES_API_URL,
            headers=_REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=UPDATE_CHECK_TIMEOUT_SECONDS),
        ) as response:
            if response.status != HTTP_OK:
                logger.debug("Update check returned HTTP %s", response.status)
                return None
            payload: Any = await response.json()
            return payload if isinstance(payload, dict) else None
    except Exception:
        # Offline, DNS failure, rate limit, malformed JSON, closed loop:
        # all equally unimportant to the user's actual task.
        logger.debug("Update check request failed", exc_info=True)
        return None


async def _build_update_info() -> UpdateInfo | None:
    """Turn a release payload into an ``UpdateInfo``, or ``None``."""
    payload = await _fetch_release()
    if payload is None:
        return None
    # Do not push pre-releases at users running stable builds.
    if payload.get("prerelease") and not _is_prerelease(APP_VERSION):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return None
    latest = tag.lstrip("vV")
    if not is_newer(latest, APP_VERSION):
        return None
    return UpdateInfo(
        latest_version=latest,
        current_version=APP_VERSION,
        url=str(payload.get("html_url") or RELEASES_PAGE_URL),
        release_notes=_clean_notes(payload.get("body")),
    )


async def check_for_update(force: bool = False) -> UpdateInfo | None:
    """Return an available update, or ``None``.

    Serves from cache unless ``force`` is set. Never raises.

    Concurrent callers on the same event loop share a single in-flight request
    rather than stampeding the API; the first caller's result is what everyone
    observes once the cache is populated.
    """
    if not force:
        cached = cached_update()
        if cached is not None:
            return cached
        if _has_fresh_entry():
            return None
        with _cache_lock:
            key = _cache_key()
            if key in _inflight:
                return None
            _inflight.add(key)
    try:
        result = await _build_update_info()
    finally:
        if not force:
            with _cache_lock:
                _inflight.discard(_cache_key())
    _store(result)
    return result
