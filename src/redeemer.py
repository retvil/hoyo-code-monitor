"""Hoyolab API code redemption module.

Provides async redemption of Genshin Impact promotional codes via Hoyolab API.
"""

import logging
from dataclasses import dataclass
from typing import Any, Self

import aiohttp

from src.exceptions import RedeemerError
from src.http_session import get_session

logger = logging.getLogger(__name__)


@dataclass
class RedemptionResult:
    """Result of a code redemption attempt.

    Attributes:
        success: Whether the redemption was successful.
        reward: Description of the reward received (empty if failed).
        message: Human-readable message from the API.
        raw_response: Full raw JSON response from the API.
    """

    success: bool
    reward: str
    message: str
    raw_response: dict[str, Any]


class Redeemer:
    """Async client for redeeming Genshin Impact codes via Hoyolab API.

    Attributes:
        endpoint: API endpoint URL for code redemption.
        default_headers: Default HTTP headers for requests.
        default_form_data: Default form data parameters for redemption.
    """

    DEFAULT_ENDPOINT = "https://sg-hk4e-api.hoyoverse.com/common/apicdkey/api/webExchangeCdkey"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    DEFAULT_REFERER = "https://webstatic-sea.mihoyo.com/"

    def __init__(
        self,
        endpoint: str | None = None,
        user_agent: str | None = None,
        referer: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the Redeemer client.

        Args:
            endpoint: API endpoint URL. Defaults to Hoyolab's webExchangeCdkey endpoint.
            user_agent: Custom User-Agent header. Defaults to a Chrome-like UA.
            referer: Custom Referer header. Defaults to Hoyolab's webstatic domain.
            timeout: Request timeout in seconds. Defaults to 30.0.
        """
        self.endpoint = endpoint or self.DEFAULT_ENDPOINT
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.referer = referer or self.DEFAULT_REFERER
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        # True while ``_session`` was injected by a caller (tests, or a caller
        # that manages its own session): those must be closed on ``close()``.
        # Set to False when the session is borrowed from the shared pool,
        # because a borrower must never close a session other components use.
        self._owns_session = True

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get the shared aiohttp ClientSession.

        The session comes from the process-wide pool (see ``http_session``),
        so redemption no longer owns its own connection pool. ``self.timeout``
        is applied per request rather than per session, because the pooled
        session is shared with components that have different budgets.

        Returns:
            aiohttp.ClientSession: The shared session instance.
        """
        if self._session is None or self._session.closed:
            self._session = get_session()
            self._owns_session = False
        return self._session

    async def close(self) -> None:
        """Release the underlying aiohttp session.

        Only sessions this instance created (i.e. injected by a caller) are
        closed. A pooled session is left open for the rest of the process and
        is torn down at shutdown by ``http_session.close_all()``.
        """
        session, self._session = self._session, None
        if session is not None and not session.closed and self._owns_session:
            await session.close()
        self._owns_session = True

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - closes session."""
        await self.close()

    def _build_cookie_header(self, cookies: dict[str, str]) -> str:
        """Build Cookie header string from cookies dictionary.

        Args:
            cookies: Dictionary of cookie name-value pairs.
                Expected keys: ltuid, ltoken, cookie_token_v2 (or similar).

        Returns:
            Formatted Cookie header string.
        """
        # Filter out None/empty values and build cookie string
        cookie_parts = [f"{key}={value}" for key, value in cookies.items() if value]
        return "; ".join(cookie_parts)

    def _build_headers(self, cookies: dict[str, str]) -> dict[str, str]:
        """Build request headers including cookies.

        Args:
            cookies: Dictionary of cookie name-value pairs.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "Cookie": self._build_cookie_header(cookies),
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "x-rpc-app_version": "2.34.1",
            "x-rpc-client_type": "4",
        }

    def _build_form_data(
        self,
        code: str,
        uid: str,
        region: str,
        game_biz: str = "hk4e_global",
        lang: str = "en-us",
        s_lang_key: str = "en-us",
    ) -> dict[str, str]:
        """Build form data for the redemption request.

        Args:
            code: The promotional code to redeem.
            uid: User ID (numeric string).
            region: Server region (e.g., "os_usa", "os_euro", "os_asia", "os_cht").
            game_biz: Game business identifier. Defaults to "hk4e_global".
            lang: Language code. Defaults to "en-us".
            s_lang_key: Secondary language key. Defaults to "en-us".

        Returns:
            Dictionary of form data parameters.
        """
        return {
            "uid": uid,
            "region": region,
            "game_biz": game_biz,
            "cdkey": code,
            "lang": lang,
            "sLangKey": s_lang_key,
        }

    def _parse_response(self, data: dict[str, Any]) -> RedemptionResult:
        """Parse Hoyolab API response into RedemptionResult.

        Hoyolab API response format:
        {
            "retcode": 0,  # 0 = success, non-zero = error
            "message": "OK",
            "data": {
                "award": "Primogem x100",
                ...
            }
        }

        Args:
            data: Parsed JSON response from the API.

        Returns:
            RedemptionResult with parsed fields.
        """
        retcode = data.get("retcode", -1)
        message = data.get("message", "Unknown error")
        response_data = data.get("data", {})

        success = retcode == 0
        reward = ""

        if success and response_data:
            # Extract reward description from data (shapes vary: dict/list)
            reward = ""
            if isinstance(response_data, dict):
                reward = str(response_data.get("award") or response_data.get("name") or "")
                if not reward:
                    parts = []
                    for k, v in response_data.items():
                        if isinstance(v, (int, float)) and k not in ("id",):
                            parts.append(f"{k} x{v}")
                        elif isinstance(v, str) and v:
                            parts.append(v)
                    reward = ", ".join(parts[:5])
            elif isinstance(response_data, list):
                parts = []
                for item in response_data[:5]:
                    if isinstance(item, dict):
                        name = item.get("name", "")
                        cnt = item.get("cnt", item.get("count", item.get("amount", "")))
                        parts.append(f"{name} x{cnt}".strip() if name else str(item))
                    else:
                        parts.append(str(item))
                reward = ", ".join(parts)
            if not reward:
                reward = message if message and message != "OK" else "Redeemed"

        return RedemptionResult(
            success=success,
            reward=reward,
            message=message,
            raw_response=data,
        )

    async def redeem_code(
        self,
        code: str,
        cookies: dict[str, str],
        uid: str,
        region: str,
        game_biz: str | None = None,
        lang: str = "en-us",
        s_lang_key: str = "en-us",
        game: str = "genshin",
    ) -> RedemptionResult:
        """Redeem a promotional code via Hoyolab API.

        Args:
            code: The promotional code to redeem.
            cookies: Dictionary containing authentication cookies.
                Required keys: ltuid, ltoken (and optionally cookie_token_v2).
            uid: User ID (numeric string).
            region: Server region (e.g., "os_usa", "os_euro", "os_asia", "os_cht").
            game_biz: Game business identifier. Defaults to "hk4e_global".
            lang: Language code. Defaults to "en-us".
            s_lang_key: Secondary language key. Defaults to "en-us".
            game: Game id for endpoint selection ("genshin", "hsr", "zzz").
                ZZZ uses the Risk POST endpoint.

        Returns:
            RedemptionResult with success status, reward, message, and raw response.

        Raises:
            aiohttp.ClientError: On network/connection errors.
            ValueError: If required cookies are missing.
        """
        from src.constants import GAME_CONF

        # Validate required cookies first
        required_cookies = ["ltuid", "ltoken"]
        missing = [c for c in required_cookies if not cookies.get(c)]
        if missing:
            raise RedeemerError(f"Missing required cookies: {missing}")  # noqa: TRY003 -- validation message needs interpolation

        conf = GAME_CONF.get(game, GAME_CONF["genshin"])
        resolved_biz = game_biz or conf["game_biz"]
        endpoint = f"https://{conf['api_host']}/common/apicdkey/api/webExchangeCdkey"
        if game == "zzz":
            return await self._redeem_risk(code, cookies, uid, region, conf, lang, s_lang_key)
        original_endpoint = self.endpoint
        self.endpoint = endpoint
        try:
            return await self._redeem_get(
                code, cookies, uid, region, resolved_biz, lang, s_lang_key
            )
        finally:
            self.endpoint = original_endpoint

    async def _redeem_get(
        self,
        code: str,
        cookies: dict[str, str],
        uid: str,
        region: str,
        game_biz: str,
        lang: str,
        s_lang_key: str,
    ) -> RedemptionResult:
        """Redeem via GET webExchangeCdkey (Genshin/HSR/HI3/ToT)."""
        session = await self._get_session()
        headers = self._build_headers(cookies)
        form_data = self._build_form_data(
            code=code,
            uid=uid,
            region=region,
            game_biz=game_biz,
            lang=lang,
            s_lang_key=s_lang_key,
        )

        logger.info("Attempting to redeem code: %s", code[:4] + "****")

        # Hoyolab webExchangeCdkey accepts GET with query params (POST -> 405)
        params = dict(form_data)
        try:
            async with session.get(
                self.endpoint, headers=headers, params=params, timeout=self.timeout
            ) as response:
                response.raise_for_status()
                json_data = await response.json()

                result = self._parse_response(json_data)

                if result.success:
                    logger.info(
                        "Code redeemed successfully: %s - Reward: %s",
                        code[:4] + "****",
                        result.reward,
                    )
                else:
                    logger.warning(
                        "Code redemption failed: %s - Reason: %s",
                        code[:4] + "****",
                        result.message,
                    )

                return result

        except aiohttp.ClientResponseError as e:
            logger.error("HTTP error redeeming code %s: %s", code[:4] + "****", e)
            return RedemptionResult(
                success=False,
                reward="",
                message=f"HTTP {e.status}: {e.message}",
                raw_response={"retcode": -1, "message": str(e), "data": {}},
            )
        except aiohttp.ClientError as e:
            logger.error("Network error redeeming code %s: %s", code[:4] + "****", e)
            return RedemptionResult(
                success=False,
                reward="",
                message=f"Network error: {e}",
                raw_response={"retcode": -1, "message": str(e), "data": {}},
            )
        except Exception as e:
            logger.exception("Unexpected error redeeming code %s", code[:4] + "****")
            return RedemptionResult(
                success=False,
                reward="",
                message=f"Unexpected error: {e}",
                raw_response={"retcode": -1, "message": str(e), "data": {}},
            )

    async def _redeem_risk(
        self,
        code: str,
        cookies: dict[str, str],
        uid: str,
        region: str,
        conf: dict[str, str],
        lang: str,
        s_lang_key: str,
    ) -> RedemptionResult:
        """Redeem via POST webExchangeCdkeyRisk (ZZZ)."""
        session = await self._get_session()
        headers = self._build_headers(cookies)
        headers["Content-Type"] = "application/json"
        payload = {
            "game_biz": conf["game_biz"],
            "uid": uid,
            "region": region,
            "cdkey": code,
            "lang": lang,
        }
        url = f"https://{conf['api_host']}/common/apicdkey/api/webExchangeCdkeyRisk"

        logger.info("Attempting to redeem ZZZ code: %s", code[:4] + "****")

        try:
            async with session.post(url, headers=headers, json=payload, timeout=self.timeout) as response:
                response.raise_for_status()
                result = self._parse_response(await response.json())
                if result.success:
                    logger.info("ZZZ code redeemed: %s", code[:4] + "****")
                else:
                    logger.warning(
                        "ZZZ redemption failed: %s - %s", code[:4] + "****", result.message
                    )
                return result
        except aiohttp.ClientResponseError as e:
            logger.error("HTTP error redeeming ZZZ code %s: %s", code[:4] + "****", e)
            return RedemptionResult(
                success=False,
                reward="",
                message=f"HTTP {e.status}: {e.message}",
                raw_response={"retcode": -1, "message": str(e), "data": {}},
            )
        except aiohttp.ClientError as e:
            logger.error("Network error redeeming ZZZ code %s: %s", code[:4] + "****", e)
            return RedemptionResult(
                success=False,
                reward="",
                message=f"Network error: {e}",
                raw_response={"retcode": -1, "message": str(e), "data": {}},
            )
        except Exception as e:
            logger.exception("Unexpected error redeeming ZZZ code %s", code[:4] + "****")
            return RedemptionResult(
                success=False,
                reward="",
                message=f"Unexpected error: {e}",
                raw_response={"retcode": -1, "message": str(e), "data": {}},
            )
