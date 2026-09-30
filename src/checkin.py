"""HoYoLAB daily check-in module.

Provides async daily sign-in (check-in) for HoYoverse games via HoYoLAB event API.
Flow per account x game: GET info -> POST sign -> GET home (reward lookup).

Reference: seriaati/genshin.py (MIT) routes + DS algorithm,
Womsxd/MihoyoBBSTools (MIT) info -> sign -> home pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import string
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, Self

import aiohttp

from src.exceptions import CheckinError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from types import TracebackType

logger = logging.getLogger(__name__)

# --- Per-game check-in configuration (MVP: genshin + hsr, overseas) ---
# act_id / base_url values mirror genshin.py REWARD_URL (MIT, seriaati/genshin.py).
GAME_CHECKIN_CONF: dict[str, dict[str, str]] = {
    "genshin": {
        "name": "Genshin Impact",
        "base_url": "https://sg-hk4e-api.hoyolab.com/event/sol",
        "act_id": "e202102251931481",
        "sign_game": "hk4e",
    },
    "hsr": {
        "name": "Honkai: Star Rail",
        "base_url": "https://sg-public-api.hoyolab.com/event/luna/os",
        "act_id": "e202303301540311",
        "sign_game": "hkrpg",
    },
}

# --- HoYoLAB retcodes ---
RETCODE_SUCCESS: int = 0
RETCODE_ALREADY_CLAIMED: int = -5003
RETCODE_COOKIE_EXPIRED: tuple[int, ...] = (10001, -100)

# --- Check-in statuses (persisted in checkin_log.status) ---
STATUS_SUCCESS: str = "success"
STATUS_ALREADY_CLAIMED: str = "already_claimed"
STATUS_FAILED: str = "failed"
STATUS_SKIPPED: str = "skipped"

# DS salt for overseas HoYoLAB (public constant, cf. genshin.py utility/ds.py, MIT).
OS_DS_SALT: str = "6s25p5ox5y14umn1a8aafuwvlvogknd"

# Length of the random part in the DS signature.
DS_RANDOM_LENGTH: int = 6


class CheckinTransport(Protocol):
    """HTTP transport protocol (injectable for tests)."""

    async def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET JSON payload."""
        ...  # pragma: no cover

    async def post_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST JSON payload."""
        ...  # pragma: no cover


class AiohttpCheckinTransport:
    """Default aiohttp-based CheckinTransport (mirrors Redeemer session handling)."""

    def __init__(self, timeout: float = 30.0) -> None:
        """Initialize the transport.

        Args:
            timeout: Request timeout in seconds.
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the underlying session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET and parse JSON, raising on HTTP errors (retried by the runner)."""
        session = await self._get_session()
        async with session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            data: dict[str, Any] = await response.json()
            return data

    async def post_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST and parse JSON, raising on HTTP errors (retried by the runner)."""
        session = await self._get_session()
        async with session.post(url, headers=headers, params=params, json=body or {}) as resp:
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()
            return data


@dataclass
class CheckinContext:
    """Per-request check-in context (game + identity).

    Attributes:
        game: Game id from GAME_CHECKIN_CONF.
        device_id: Stable per-account device id for HoYoLAB.
        lang: Language code.
    """

    game: str
    device_id: str
    lang: str = "en-us"


@dataclass
class CheckinResult:
    """Result of one daily check-in attempt (one account x one game x one date).

    Attributes:
        game: Game id (e.g. "genshin").
        claimed_date: Local date string YYYY-MM-DD the attempt belongs to.
        status: One of success / already_claimed / failed / skipped.
        reward_name: Reward item name (empty if unknown/failed).
        reward_amount: Reward item count (0 if unknown/failed).
        total_sign_day: Cumulative signed days reported by /info.
        message: Human-readable outcome / error text.
    """

    game: str
    claimed_date: str
    status: str
    reward_name: str = ""
    reward_amount: int = 0
    total_sign_day: int = 0
    message: str = ""


class CheckinRunner:
    """Async runner for HoYoLAB daily check-ins.

    Attributes:
        transport: HTTP transport (defaults to aiohttp; inject fakes in tests).
        max_retries: Network-error retries per API call (API errors are not retried).
        retry_base_delay: Base backoff delay in seconds (exponential).
    """

    DEFAULT_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    DEFAULT_REFERER: str = "https://act.hoyolab.com/"

    def __init__(
        self,
        transport: CheckinTransport | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        """Initialize the runner.

        Args:
            transport: HTTP transport. Defaults to aiohttp transport.
            timeout: Request timeout for the default transport.
            max_retries: Network-error retries per API call.
            retry_base_delay: Base backoff delay in seconds.
        """
        self.transport: CheckinTransport = transport or AiohttpCheckinTransport(
            timeout=timeout
        )
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

    async def close(self) -> None:
        """Close the underlying transport if it holds resources."""
        close = getattr(self.transport, "close", None)
        if callable(close):
            await close()

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - closes transport."""
        await self.close()

    def _conf(self, game: str) -> dict[str, str]:
        """Look up per-game check-in config or raise."""
        conf = GAME_CHECKIN_CONF.get(game)
        if conf is None:
            raise CheckinError(f"Unsupported game: {game}")  # noqa: TRY003
        return conf

    @staticmethod
    def _require_cookies(cookies: dict[str, str]) -> None:
        """Validate auth cookies before any HTTP call."""
        missing = [c for c in ("ltuid", "ltoken") if not cookies.get(c)]
        if missing:
            raise CheckinError(f"Missing required cookies: {missing}")  # noqa: TRY003

    def generate_ds(
        self,
        body: str = "",
        query: str = "",
        t: int | None = None,
        r: str | None = None,
    ) -> str:
        """Generate the HoYoLAB DS request signature.

        Format: "{t},{r},{md5(salt&t&r&body&query)}" (cf. genshin.py DS, MIT).

        Args:
            body: Request body string ("" for GET).
            query: Raw query string (e.g. "act_id=...&lang=...").
            t: Unix timestamp (defaults to now; inject in tests).
            r: 6-char random string (generated when omitted).

        Returns:
            DS header value.
        """
        stamp = t if t is not None else int(time.time())
        rand = r if r is not None else "".join(
            random.choices(string.ascii_letters + string.digits, k=DS_RANDOM_LENGTH)
        )
        digest = hashlib.md5(
            f"salt={OS_DS_SALT}&t={stamp}&r={rand}&b={body}&q={query}".encode()
        ).hexdigest()
        return f"{stamp},{rand},{digest}"

    def build_headers(
        self, cookies: dict[str, str], ctx: CheckinContext, query: str = "", body: str = ""
    ) -> dict[str, str]:
        """Build HoYoLAB event API headers for one game.

        Args:
            cookies: Auth cookies (ltuid, ltoken, ...).
            ctx: Check-in context (game, device id, language).
            query: Raw query string used for the DS signature.
            body: Request body string used for the DS signature.

        Returns:
            Dictionary of HTTP headers.
        """
        conf = self._conf(ctx.game)
        cookie_parts = [f"{k}={v}" for k, v in cookies.items() if v]
        return {
            "Cookie": "; ".join(cookie_parts),
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": self.DEFAULT_REFERER,
            "Origin": "https://act.hoyolab.com",
            "x-rpc-signgame": conf["sign_game"],
            "x-rpc-client_type": "4",
            "x-rpc-app_version": "2.34.1",
            "x-rpc-device_id": ctx.device_id,
            "x-rpc-language": ctx.lang,
            "DS": self.generate_ds(body=body, query=query),
        }

    async def _call_with_retry(
        self, label: str, fn: Callable[[], Coroutine[Any, Any, dict[str, Any]]]
    ) -> dict[str, Any]:
        """Call one API endpoint with exponential backoff on network errors.

        API-level errors (non-zero retcode) are returned, never retried.
        Programming errors (CheckinError) propagate immediately.

        Args:
            label: Endpoint label for logging.
            fn: Zero-arg async callable performing the request.

        Returns:
            Raw JSON payload.
        """
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await fn()
            except CheckinError:
                raise
            except (TimeoutError, aiohttp.ClientError) as e:
                last_error = e
                if attempt >= self.max_retries:
                    break
                delay = self.retry_base_delay * (2**attempt)
                logger.warning(
                    "Check-in %s attempt %d/%d failed: %s; retry in %.1fs",
                    label,
                    attempt + 1,
                    self.max_retries + 1,
                    e,
                    delay,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
        assert last_error is not None  # loop always runs at least once
        raise last_error

    def _query(self, ctx: CheckinContext) -> tuple[str, dict[str, str]]:
        """Build (query_string, params) pair for event endpoints."""
        conf = self._conf(ctx.game)
        params = {"act_id": conf["act_id"], "lang": ctx.lang}
        return f"act_id={conf['act_id']}&lang={ctx.lang}", params

    async def get_state(self, ctx: CheckinContext, cookies: dict[str, str]) -> dict[str, Any]:
        """Fetch today's check-in state via GET info.

        Args:
            ctx: Check-in context (game, device id, language).
            cookies: Auth cookies.

        Returns:
            Dict with retcode, message, today (int), total_sign_day (int),
            is_sign (bool), first_bind (bool).
        """
        conf = self._conf(ctx.game)
        query, params = self._query(ctx)
        headers = self.build_headers(cookies, ctx, query=query)
        data = await self.transport.get_json(
            f"{conf['base_url']}/info", headers=headers, params=params
        )
        payload = data.get("data") or {}
        return {
            "retcode": data.get("retcode", -1),
            "message": data.get("message", "Unknown error"),
            "today": int(payload.get("today") or 0),
            "total_sign_day": int(payload.get("total_sign_day") or 0),
            "is_sign": bool(payload.get("is_sign", False)),
            "first_bind": bool(payload.get("first_bind", False)),
        }

    async def claim(self, ctx: CheckinContext, cookies: dict[str, str]) -> dict[str, Any]:
        """Perform the daily claim via POST sign (raw payload, classified by run).

        Args:
            ctx: Check-in context (game, device id, language).
            cookies: Auth cookies.

        Returns:
            Raw JSON payload from /sign.
        """
        conf = self._conf(ctx.game)
        query, params = self._query(ctx)
        headers = self.build_headers(cookies, ctx, query=query, body="{}")
        return await self.transport.post_json(
            f"{conf['base_url']}/sign", headers=headers, params=params, body={}
        )

    async def fetch_reward(
        self, ctx: CheckinContext, cookies: dict[str, str], today: int
    ) -> tuple[str, int]:
        """Look up today's reward via GET home.

        Args:
            ctx: Check-in context (game, device id, language).
            cookies: Auth cookies.
            today: Day of month (1-based) from /info.

        Returns:
            (reward_name, reward_amount); ("", 0) when unavailable.
        """
        conf = self._conf(ctx.game)
        query, params = self._query(ctx)
        headers = self.build_headers(cookies, ctx, query=query)
        try:
            data = await self.transport.get_json(
                f"{conf['base_url']}/home", headers=headers, params=params
            )
        except (TimeoutError, aiohttp.ClientError) as e:
            logger.warning("Check-in reward lookup failed for %s: %s", ctx.game, e)
            return "", 0
        awards = (data.get("data") or {}).get("awards") or []
        idx = today - 1
        if 0 <= idx < len(awards) and isinstance(awards[idx], dict):
            item = awards[idx]
            name = str(item.get("name") or "")
            amount = item.get("cnt", item.get("count", item.get("amount", 0)))
            try:
                return name, int(amount)
            except (TypeError, ValueError):
                return name, 0
        return "", 0

    @staticmethod
    def _cookie_expired_message() -> str:
        """User-facing hint for expired/invalid cookies."""
        return "Check-in unavailable: cookie expired, refresh account cookies"

    def _failed(
        self, game: str, claimed_date: str, message: str
    ) -> CheckinResult:
        """Build a failed CheckinResult."""
        return CheckinResult(game, claimed_date, STATUS_FAILED, message=message)

    def _api_error_result(
        self, game: str, claimed_date: str, retcode: int, message: str
    ) -> CheckinResult:
        """Classify a non-zero API retcode into a CheckinResult."""
        if retcode in RETCODE_COOKIE_EXPIRED:
            return self._failed(game, claimed_date, self._cookie_expired_message())
        return self._failed(game, claimed_date, message)

    async def _signed_result(
        self,
        ctx: CheckinContext,
        cookies: dict[str, str],
        claimed_date: str,
        state: dict[str, Any],
    ) -> CheckinResult:
        """Build an already-claimed result (pre-claim state or -5003 race)."""
        name, amount = await self.fetch_reward(ctx, cookies, state["today"])
        return CheckinResult(
            ctx.game,
            claimed_date,
            STATUS_ALREADY_CLAIMED,
            reward_name=name,
            reward_amount=amount,
            total_sign_day=state["total_sign_day"],
            message="Already signed in today",
        )

    async def _claim_result(
        self,
        ctx: CheckinContext,
        cookies: dict[str, str],
        claimed_date: str,
        state: dict[str, Any],
        raw: dict[str, Any],
    ) -> CheckinResult:
        """Classify a /sign payload into a CheckinResult (fetches reward on success)."""
        retcode = raw.get("retcode", -1)
        if retcode == RETCODE_ALREADY_CLAIMED:
            return await self._signed_result(ctx, cookies, claimed_date, state)
        if retcode != RETCODE_SUCCESS:
            return self._api_error_result(
                ctx.game, claimed_date, retcode, str(raw.get("message") or "Unknown error")
            )
        name, amount = await self.fetch_reward(ctx, cookies, state["today"])
        logger.info("Check-in success for %s: %s x%s", ctx.game, name, amount)
        return CheckinResult(
            ctx.game,
            claimed_date,
            STATUS_SUCCESS,
            reward_name=name,
            reward_amount=amount,
            total_sign_day=state["total_sign_day"],
            message="OK",
        )

    async def run(
        self,
        game: str,
        cookies: dict[str, str],
        device_id: str,
        claimed_date: str,
        lang: str = "en-us",
    ) -> CheckinResult:
        """Run the full daily cycle: info -> sign -> home.

        Never raises on API/network problems (returns failed); raises CheckinError
        only on programming errors (unknown game, missing cookies).

        Args:
            game: Game id from GAME_CHECKIN_CONF.
            cookies: Auth cookies.
            device_id: Stable per-account device id.
            claimed_date: Local date YYYY-MM-DD this attempt belongs to.
            lang: Language code.

        Returns:
            CheckinResult with classified status.
        """
        ctx = CheckinContext(game=game, device_id=device_id, lang=lang)
        self._conf(game)
        self._require_cookies(cookies)

        try:
            state = await self._call_with_retry(
                f"{game}/info", lambda: self.get_state(ctx, cookies)
            )
        except (TimeoutError, aiohttp.ClientError) as e:
            logger.exception("Check-in info failed for %s", game)
            return self._failed(game, claimed_date, str(e))

        if state["retcode"] != RETCODE_SUCCESS:
            return self._api_error_result(
                game, claimed_date, state["retcode"], state["message"]
            )
        if state["is_sign"]:
            return await self._signed_result(ctx, cookies, claimed_date, state)
        if state["first_bind"]:
            return CheckinResult(
                game,
                claimed_date,
                STATUS_SKIPPED,
                total_sign_day=state["total_sign_day"],
                message="First check-in must be done manually in HoYoLAB",
            )

        try:
            raw = await self._call_with_retry(
                f"{game}/sign", lambda: self.claim(ctx, cookies)
            )
        except (TimeoutError, aiohttp.ClientError) as e:
            logger.exception("Check-in sign failed for %s", game)
            return self._failed(game, claimed_date, str(e))
        return await self._claim_result(ctx, cookies, claimed_date, state, raw)
