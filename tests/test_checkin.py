"""Unit tests for the HoYoLAB daily check-in runner."""

import re

import aiohttp
import pytest

from src.checkin import GAME_CHECKIN_CONF, CheckinContext, CheckinResult, CheckinRunner
from src.exceptions import CheckinError

#: Expected fixtures shared across assertions (avoid PLR2004 magic values).
EXPECTED_REWARD_AMOUNT: int = 100
EXPECTED_TOTAL_SIGN_DAY: int = 2
EXPECTED_INFO_CALLS_AFTER_RETRIES: int = 3


def make_info(
    *,
    is_sign: bool = False,
    today: str = "3",
    total_sign_day: int = 2,
    first_bind: bool = False,
) -> dict:
    """Build a mock /info response payload."""
    return {
        "retcode": 0,
        "message": "OK",
        "data": {
            "today": today,
            "total_sign_day": total_sign_day,
            "is_sign": is_sign,
            "first_bind": first_bind,
        },
    }


def make_home() -> dict:
    """Build a mock /home response payload (3 awards, day 3 = Primogem x100)."""
    return {
        "retcode": 0,
        "message": "OK",
        "data": {
            "awards": [
                {"name": "Mora", "cnt": 5000},
                {"name": "Hero's Wit", "cnt": 2},
                {"name": "Primogem", "cnt": 100},
            ],
        },
    }


def make_sign(retcode: int = 0, message: str = "OK") -> dict:
    """Build a mock /sign response payload."""
    return {"retcode": retcode, "message": message, "data": {}}


class FakeTransport:
    """Scripted fake HTTP transport for CheckinRunner tests."""

    def __init__(
        self,
        info=None,
        sign=None,
        home=None,
    ) -> None:
        self.info = info if info is not None else make_info()
        self.sign_script = list(sign) if sign is not None else [make_sign()]
        self.home = home if home is not None else make_home()
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def _resolve(scripted):
        if isinstance(scripted, Exception):
            raise scripted
        return scripted

    async def get_json(
        self,
        url: str,
        headers: dict | None = None,  # noqa: ARG002
        params: dict | None = None,  # noqa: ARG002
    ) -> dict:
        self.calls.append(("GET", url))
        if url.endswith("/info"):
            return self._resolve(self.info)
        if url.endswith("/home"):
            return self._resolve(self.home)
        raise AssertionError(url)

    async def post_json(
        self,
        url: str,
        headers: dict | None = None,  # noqa: ARG002
        params: dict | None = None,  # noqa: ARG002
        body: dict | None = None,  # noqa: ARG002
    ) -> dict:
        self.calls.append(("POST", url))
        if url.endswith("/sign"):
            if not self.sign_script:
                raise AssertionError(url)
            return self._resolve(self.sign_script.pop(0))
        raise AssertionError(url)

    def count(self, method: str, suffix: str) -> int:
        """Count calls by method and URL suffix."""
        return sum(1 for m, u in self.calls if m == method and u.endswith(suffix))


@pytest.fixture
def cookies() -> dict:
    """Valid cookies dictionary for testing."""
    return {
        "ltuid": "123456789",
        "ltoken": "abcdef123456",
        "cookie_token": "xyz789",
        "account_id": "123456789",
    }


@pytest.fixture
def runner() -> CheckinRunner:
    """CheckinRunner with zero backoff for fast tests."""
    return CheckinRunner(transport=FakeTransport(), retry_base_delay=0.0)


class TestGameCheckinConf:
    """Tests for the per-game check-in configuration table."""

    def test_mvp_games_present(self) -> None:
        """MVP covers genshin + hsr; wave 2 adds zzz + hi3."""
        assert "genshin" in GAME_CHECKIN_CONF
        assert "hsr" in GAME_CHECKIN_CONF
        assert "zzz" in GAME_CHECKIN_CONF
        assert "hi3" in GAME_CHECKIN_CONF

    def test_entries_have_required_fields(self) -> None:
        """Each entry carries base_url and act_id (sign_game may be empty = omit)."""
        for game, conf in GAME_CHECKIN_CONF.items():
            assert conf["base_url"].startswith("https://"), game
            assert conf["act_id"].startswith("e"), game
            assert "sign_game" in conf, game

    def test_sign_game_mapping(self) -> None:
        """x-rpc-signgame values match HoYoLAB expectations."""
        assert GAME_CHECKIN_CONF["genshin"]["sign_game"] == "hk4e"
        assert GAME_CHECKIN_CONF["hsr"]["sign_game"] == "hkrpg"
        assert GAME_CHECKIN_CONF["zzz"]["sign_game"] == "zzz"


class TestGenerateDs:
    """Tests for the DS request signature."""

    def test_ds_format(self, runner: CheckinRunner) -> None:
        """DS looks like 't,r,md5hex'."""
        ds = runner.generate_ds()
        assert re.fullmatch(r"\d{10},[A-Za-z0-9]{6},[a-f0-9]{32}", ds), ds

    def test_ds_deterministic_for_fixed_inputs(self, runner: CheckinRunner) -> None:
        """Same t/r/body/query produce the same DS."""
        first = runner.generate_ds(body="{}", query="act_id=e1", t=1700000000, r="abc123")
        second = runner.generate_ds(body="{}", query="act_id=e1", t=1700000000, r="abc123")
        assert first == second

    def test_ds_changes_with_inputs(self, runner: CheckinRunner) -> None:
        """Different random part changes the DS."""
        first = runner.generate_ds(t=1700000000, r="abc123")
        second = runner.generate_ds(t=1700000000, r="xyz789")
        assert first != second


class TestBuildHeaders:
    """Tests for check-in request headers."""

    def test_headers_content(self, runner: CheckinRunner, cookies: dict) -> None:
        """Headers carry cookies, signgame, DS and referer."""
        headers = runner.build_headers(cookies, CheckinContext("genshin", "dev-1"))
        assert "ltoken=abcdef123456" in headers["Cookie"]
        assert headers["x-rpc-signgame"] == "hk4e"
        assert re.fullmatch(r"\d{10},[A-Za-z0-9]{6},[a-f0-9]{32}", headers["DS"])
        assert "act.hoyolab.com" in headers["Referer"]
        assert headers["x-rpc-device_id"] == "dev-1"

    def test_headers_hsr_signgame(self, runner: CheckinRunner, cookies: dict) -> None:
        """HSR uses the hkrpg signgame."""
        headers = runner.build_headers(cookies, CheckinContext("hsr", "dev-1"))
        assert headers["x-rpc-signgame"] == "hkrpg"

    def test_headers_hi3_omits_signgame(self, runner: CheckinRunner, cookies: dict) -> None:
        """HI3 sends no signgame header (matches reference clients)."""
        headers = runner.build_headers(cookies, CheckinContext("hi3", "dev-1"))
        assert "x-rpc-signgame" not in headers


class TestRunSuccess:
    """Happy-path daily check-in."""

    @pytest.mark.asyncio
    async def test_run_success(self, cookies: dict) -> None:
        """Full cycle: info -> sign -> home, reward parsed."""
        transport = FakeTransport()
        runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert isinstance(result, CheckinResult)
        assert result.status == "success"
        assert result.reward_name == "Primogem"
        assert result.reward_amount == EXPECTED_REWARD_AMOUNT
        assert result.total_sign_day == EXPECTED_TOTAL_SIGN_DAY
        assert result.claimed_date == "2026-09-24"
        assert transport.count("GET", "/info") == 1
        assert transport.count("POST", "/sign") == 1

    @pytest.mark.asyncio
    async def test_run_success_with_full_date(self, cookies: dict) -> None:
        """Real API returns today as YYYY-MM-DD, not a day number."""
        home = make_home()
        home["data"]["awards"] = [
            {"name": "Mora", "cnt": 5000},
            {"name": "Primogem", "cnt": 100},
        ]
        transport = FakeTransport(info=make_info(today="2026-10-02"), home=home)
        runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
        result = await runner.run("genshin", cookies, "dev-1", "2026-10-02")

        assert result.status == "success"
        assert result.reward_name == "Primogem"
        assert result.reward_amount == EXPECTED_REWARD_AMOUNT


class TestRunAlreadyClaimed:
    """Already-signed paths never call /sign."""

    @pytest.mark.asyncio
    async def test_already_signed_skips_claim(self, cookies: dict) -> None:
        """is_sign=true short-circuits before claim."""
        transport = FakeTransport(info=make_info(is_sign=True, total_sign_day=3))
        runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert result.status == "already_claimed"
        assert transport.count("POST", "/sign") == 0

    @pytest.mark.asyncio
    async def test_sign_race_treated_as_claimed(self, cookies: dict) -> None:
        """retcode -5003 from /sign means a concurrent claim won the race."""
        transport = FakeTransport(sign=[make_sign(-5003, "Already signed in")])
        runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert result.status == "already_claimed"
        assert transport.count("POST", "/sign") == 1


class TestRunFailures:
    """Failure classification."""

    @pytest.mark.asyncio
    async def test_cookie_expired(self, cookies: dict) -> None:
        """retcode 10001 maps to failed with a cookie hint."""
        transport = FakeTransport(sign=[make_sign(10001, "Not logged in")])
        runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert result.status == "failed"
        assert "cookie" in result.message.lower()

    @pytest.mark.asyncio
    async def test_first_bind_skips(self, cookies: dict) -> None:
        """first_bind requires one manual sign-in; claim is not attempted."""
        transport = FakeTransport(info=make_info(first_bind=True))
        runner = CheckinRunner(transport=transport, retry_base_delay=0.0)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert result.status == "skipped"
        assert transport.count("POST", "/sign") == 0

    @pytest.mark.asyncio
    async def test_unknown_game_raises(self, cookies: dict, runner: CheckinRunner) -> None:
        """Unsupported game id is a programming error, not a failed claim."""
        with pytest.raises(CheckinError):
            await runner.run("nope", cookies, "dev-1", "2026-09-24")

    @pytest.mark.asyncio
    async def test_missing_cookies_raise(self, runner: CheckinRunner) -> None:
        """Missing ltuid/ltoken fails fast before any HTTP call."""
        transport = runner.transport
        assert isinstance(transport, FakeTransport)
        with pytest.raises(CheckinError):
            await runner.run("genshin", {"ltuid": "1"}, "dev-1", "2026-09-24")
        assert transport.calls == []


class TestRunRetry:
    """Network-error retry behaviour (API errors are not retried)."""

    @pytest.mark.asyncio
    async def test_transient_errors_recovered(self, cookies: dict) -> None:
        """Two network blips then success."""

        class FlakyTransport(FakeTransport):
            def __init__(self) -> None:
                super().__init__()
                self.info_calls = 0

            async def get_json(self, url, headers=None, params=None):  # noqa: ARG002
                if url.endswith("/info"):
                    self.info_calls += 1
                    if self.info_calls < EXPECTED_INFO_CALLS_AFTER_RETRIES:
                        raise aiohttp.ClientConnectionError("down")
                    return make_info()
                return await super().get_json(url)

        flaky = FlakyTransport()
        runner = CheckinRunner(transport=flaky, retry_base_delay=0.0, max_retries=3)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert result.status == "success"
        assert flaky.info_calls == EXPECTED_INFO_CALLS_AFTER_RETRIES

    @pytest.mark.asyncio
    async def test_persistent_errors_fail_after_retries(self, cookies: dict) -> None:
        """Exhausted retries surface as failed, not an exception."""

        class DeadTransport(FakeTransport):
            async def get_json(self, url, headers=None, params=None):  # noqa: ARG002
                self.calls.append(("GET", url))
                raise aiohttp.ClientConnectionError("down")

        dead = DeadTransport()
        runner = CheckinRunner(transport=dead, retry_base_delay=0.0, max_retries=2)
        result = await runner.run("genshin", cookies, "dev-1", "2026-09-24")

        assert result.status == "failed"
        assert dead.count("GET", "/info") == EXPECTED_INFO_CALLS_AFTER_RETRIES
