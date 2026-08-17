"""Unit tests for the Redeemer class."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.redeemer import Redeemer, RedemptionResult


@asynccontextmanager
async def mock_async_context_manager(response):
    """Create an async context manager that yields the given response."""
    yield response


@pytest.fixture
def redeemer() -> Redeemer:
    """Create a Redeemer instance for testing."""
    return Redeemer()


@pytest.fixture
def valid_cookies() -> dict:
    """Valid cookies dictionary for testing."""
    return {
        "ltuid": "123456789",
        "ltoken": "abcdef123456",
        "cookie_token_v2": "xyz789",
    }


@pytest.fixture
def mock_success_response() -> dict:
    """Mock successful API response."""
    return {
        "retcode": 0,
        "message": "OK",
        "data": {
            "award": "Primogem x100",
            "name": "Primogem x100",
        },
    }


@pytest.fixture
def mock_failure_response() -> dict:
    """Mock failed API response (code already used)."""
    return {
        "retcode": -2003,
        "message": "This code has already been used.",
        "data": {},
    }


@pytest.fixture
def mock_invalid_code_response() -> dict:
    """Mock invalid code API response."""
    return {
        "retcode": -2017,
        "message": "Invalid code.",
        "data": {},
    }


class TestRedemptionResult:
    """Tests for RedemptionResult dataclass."""

    def test_redemption_result_creation(self) -> None:
        """Test creating a RedemptionResult."""
        result = RedemptionResult(
            success=True,
            reward="Primogem x100",
            message="OK",
            raw_response={"retcode": 0, "message": "OK", "data": {}},
        )
        assert result.success is True
        assert result.reward == "Primogem x100"
        assert result.message == "OK"
        assert result.raw_response["retcode"] == 0

    def test_redemption_result_failure(self) -> None:
        """Test creating a failed RedemptionResult."""
        result = RedemptionResult(
            success=False,
            reward="",
            message="Invalid code.",
            raw_response={"retcode": -2017, "message": "Invalid code.", "data": {}},
        )
        assert result.success is False
        assert result.reward == ""
        assert result.message == "Invalid code."


class TestRedeemerInitialization:
    """Tests for Redeemer initialization."""

    def test_default_initialization(self) -> None:
        """Test default initialization values."""
        redeemer = Redeemer()
        assert redeemer.endpoint == Redeemer.DEFAULT_ENDPOINT
        assert redeemer.user_agent == Redeemer.DEFAULT_USER_AGENT
        assert redeemer.referer == Redeemer.DEFAULT_REFERER
        assert redeemer.timeout.total == 30.0

    def test_custom_initialization(self) -> None:
        """Test custom initialization values."""
        custom_endpoint = "https://custom.api/endpoint"
        custom_ua = "CustomAgent/1.0"
        custom_referer = "https://custom.referer"
        custom_timeout = 60.0

        redeemer = Redeemer(
            endpoint=custom_endpoint,
            user_agent=custom_ua,
            referer=custom_referer,
            timeout=custom_timeout,
        )
        assert redeemer.endpoint == custom_endpoint
        assert redeemer.user_agent == custom_ua
        assert redeemer.referer == custom_referer
        assert redeemer.timeout.total == custom_timeout


class TestRedeemerHeaders:
    """Tests for header building."""

    def test_build_cookie_header(self, redeemer: Redeemer) -> None:
        """Test building Cookie header from cookies dict."""
        cookies = {
            "ltuid": "12345",
            "ltoken": "abcdef",
            "cookie_token_v2": "xyz",
        }
        header = redeemer._build_cookie_header(cookies)
        assert "ltuid=12345" in header
        assert "ltoken=abcdef" in header
        assert "cookie_token_v2=xyz" in header

    def test_build_cookie_header_skips_empty(self, redeemer: Redeemer) -> None:
        """Test that empty cookie values are skipped."""
        cookies = {
            "ltuid": "12345",
            "ltoken": "",
            "cookie_token_v2": "xyz",
        }
        header = redeemer._build_cookie_header(cookies)
        assert "ltuid=12345" in header
        assert "cookie_token_v2=xyz" in header
        assert "ltoken=" not in header

    def test_build_headers(self, redeemer: Redeemer, valid_cookies: dict) -> None:
        """Test building complete headers dict."""
        headers = redeemer._build_headers(valid_cookies)
        assert "Cookie" in headers
        assert "Referer" in headers
        assert "User-Agent" in headers
        assert "Content-Type" in headers
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert headers["Referer"] == redeemer.referer
        assert headers["User-Agent"] == redeemer.user_agent


class TestRedeemerFormData:
    """Tests for form data building."""

    def test_build_form_data_defaults(self, redeemer: Redeemer) -> None:
        """Test building form data with default values."""
        form_data = redeemer._build_form_data(
            code="GENSHIN123",
            uid="123456789",
            region="os_usa",
        )
        assert form_data["cdkey"] == "GENSHIN123"
        assert form_data["uid"] == "123456789"
        assert form_data["region"] == "os_usa"
        assert form_data["game_biz"] == "hk4e_global"
        assert form_data["lang"] == "en-us"
        assert form_data["sLangKey"] == "en-us"

    def test_build_form_data_custom(self, redeemer: Redeemer) -> None:
        """Test building form data with custom values."""
        form_data = redeemer._build_form_data(
            code="GENSHIN123",
            uid="123456789",
            region="os_euro",
            game_biz="hk4e_cn",
            lang="zh-cn",
            s_lang_key="zh-cn",
        )
        assert form_data["region"] == "os_euro"
        assert form_data["game_biz"] == "hk4e_cn"
        assert form_data["lang"] == "zh-cn"
        assert form_data["sLangKey"] == "zh-cn"


class TestRedeemerParseResponse:
    """Tests for response parsing."""

    def test_parse_success_response(
        self, redeemer: Redeemer, mock_success_response: dict
    ) -> None:
        """Test parsing successful response."""
        result = redeemer._parse_response(mock_success_response)
        assert result.success is True
        assert result.reward == "Primogem x100"
        assert result.message == "OK"
        assert result.raw_response == mock_success_response

    def test_parse_failure_response(
        self, redeemer: Redeemer, mock_failure_response: dict
    ) -> None:
        """Test parsing failed response."""
        result = redeemer._parse_response(mock_failure_response)
        assert result.success is False
        assert result.reward == ""
        assert result.message == "This code has already been used."
        assert result.raw_response == mock_failure_response

    def test_parse_invalid_code_response(
        self, redeemer: Redeemer, mock_invalid_code_response: dict
    ) -> None:
        """Test parsing invalid code response."""
        result = redeemer._parse_response(mock_invalid_code_response)
        assert result.success is False
        assert result.reward == ""
        assert result.message == "Invalid code."

    def test_parse_response_missing_retcode(self, redeemer: Redeemer) -> None:
        """Test parsing response with missing retcode defaults to failure."""
        response = {"message": "OK", "data": {}}
        result = redeemer._parse_response(response)
        assert result.success is False
        assert result.message == "OK"

    def test_parse_response_missing_data(self, redeemer: Redeemer) -> None:
        """Test parsing response with missing data field."""
        response = {"retcode": 0, "message": "OK"}
        result = redeemer._parse_response(response)
        assert result.success is True
        assert result.reward == ""


class TestRedeemerRedeemCode:
    """Tests for redeem_code method."""

    @pytest.mark.asyncio
    async def test_redeem_code_success(
        self,
        redeemer: Redeemer,
        valid_cookies: dict,
        mock_success_response: dict,
    ) -> None:
        """Test successful code redemption."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_success_response)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_async_context_manager(mock_response))
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            result = await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=valid_cookies,
                uid="123456789",
                region="os_usa",
            )

        assert result.success is True
        assert result.reward == "Primogem x100"
        assert result.message == "OK"
        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_redeem_code_failure(
        self,
        redeemer: Redeemer,
        valid_cookies: dict,
        mock_failure_response: dict,
    ) -> None:
        """Test failed code redemption (already used)."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_failure_response)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_async_context_manager(mock_response))
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            result = await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=valid_cookies,
                uid="123456789",
                region="os_usa",
            )

        assert result.success is False
        assert result.reward == ""
        assert result.message == "This code has already been used."

    @pytest.mark.asyncio
    async def test_redeem_code_invalid_code(
        self,
        redeemer: Redeemer,
        valid_cookies: dict,
        mock_invalid_code_response: dict,
    ) -> None:
        """Test invalid code redemption."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_invalid_code_response)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_async_context_manager(mock_response))
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            result = await redeemer.redeem_code(
                code="INVALID",
                cookies=valid_cookies,
                uid="123456789",
                region="os_usa",
            )

        assert result.success is False
        assert result.message == "Invalid code."

    @pytest.mark.asyncio
    async def test_redeem_code_missing_ltuid(self, redeemer: Redeemer) -> None:
        """Test redemption with missing ltuid cookie raises ValueError."""
        cookies = {"ltoken": "abcdef"}

        with pytest.raises(ValueError) as exc_info:
            await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=cookies,
                uid="123456789",
                region="os_usa",
            )

        assert "ltuid" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_redeem_code_missing_ltoken(self, redeemer: Redeemer) -> None:
        """Test redemption with missing ltoken cookie raises ValueError."""
        cookies = {"ltuid": "12345"}

        with pytest.raises(ValueError) as exc_info:
            await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=cookies,
                uid="123456789",
                region="os_usa",
            )

        assert "ltoken" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_redeem_code_http_error(
        self, redeemer: Redeemer, valid_cookies: dict
    ) -> None:
        """Test handling of HTTP error response."""
        import aiohttp

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=403,
                message="Forbidden",
            )
        )

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_async_context_manager(mock_response))
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            result = await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=valid_cookies,
                uid="123456789",
                region="os_usa",
            )

        assert result.success is False
        assert "HTTP 403" in result.message

    @pytest.mark.asyncio
    async def test_redeem_code_network_error(
        self, redeemer: Redeemer, valid_cookies: dict
    ) -> None:
        """Test handling of network error."""
        import aiohttp

        mock_session = AsyncMock()
        mock_session.post = MagicMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            result = await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=valid_cookies,
                uid="123456789",
                region="os_usa",
            )

        assert result.success is False
        assert "Network error" in result.message

    @pytest.mark.asyncio
    async def test_redeem_code_custom_params(
        self,
        redeemer: Redeemer,
        valid_cookies: dict,
        mock_success_response: dict,
    ) -> None:
        """Test redemption with custom game_biz, lang, s_lang_key."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_success_response)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_async_context_manager(mock_response))
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            await redeemer.redeem_code(
                code="GENSHIN123",
                cookies=valid_cookies,
                uid="123456789",
                region="os_asia",
                game_biz="hk4e_cn",
                lang="zh-cn",
                s_lang_key="zh-cn",
            )

        # Verify form data was passed correctly
        call_args = mock_session.post.call_args
        form_data = call_args.kwargs["data"]
        assert form_data["region"] == "os_asia"
        assert form_data["game_biz"] == "hk4e_cn"
        assert form_data["lang"] == "zh-cn"
        assert form_data["sLangKey"] == "zh-cn"


class TestRedeemerContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, redeemer: Redeemer) -> None:
        """Test async context manager opens and closes session."""
        mock_session = AsyncMock()
        mock_session.closed = False
        redeemer._session = mock_session

        async with redeemer as r:
            assert r is redeemer

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_method(self, redeemer: Redeemer) -> None:
        """Test explicit close method."""
        mock_session = AsyncMock()
        mock_session.closed = False
        redeemer._session = mock_session

        await redeemer.close()

        mock_session.close.assert_called_once()
        assert redeemer._session is None


class TestRedeemerLogging:
    """Tests for logging behavior (no sensitive data)."""

    @pytest.mark.asyncio
    async def test_logs_code_masked(
        self,
        redeemer: Redeemer,
        valid_cookies: dict,
        mock_success_response: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that logs mask the code."""
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_success_response)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)
        mock_session.closed = False

        with patch.object(redeemer, "_get_session", return_value=mock_session):
            with caplog.at_level("INFO"):
                await redeemer.redeem_code(
                    code="GENSHIN123",
                    cookies=valid_cookies,
                    uid="123456789",
                    region="os_usa",
                )

        # Check that code is masked in logs
        log_messages = [record.message for record in caplog.records]
        assert any("GENS****" in msg for msg in log_messages)
        assert not any("GENSHIN123" in msg for msg in log_messages)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
