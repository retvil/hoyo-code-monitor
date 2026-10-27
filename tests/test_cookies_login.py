"""Tests for the pure (browser-free) parts of src.cookies_login.

Covers _cookie_skip_filters (config fallback + custom overrides) and
_normalize (auth-cookie picking + _v2 aliasing + junk filtering).
"""

from unittest.mock import patch

from src.cookies_login import (
    SKIP_EXACT,
    SKIP_PREFIXES,
    _cookie_skip_filters,
    _normalize,
)

# _cookie_skip_filters does a local `from src.config import ConfigManager`,
# so we patch the real class in its home module.
_CFG_TARGET = "src.config.ConfigManager"


def _with_config(raw: dict | None, *, error: bool = False):
    """Context manager: make ConfigManager().get_all() return `raw` (or raise)."""
    if error:
        return patch(
            _CFG_TARGET,
            side_effect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    return patch.object(
        _get_cfg_class(), "get_all", return_value=raw, autospec=True
    )


def _get_cfg_class():
    from src.config import ConfigManager

    return ConfigManager


class TestCookieSkipFilters:
    """_cookie_skip_filters falls back to defaults when config is absent."""

    def test_defaults_when_config_missing(self) -> None:
        """No cookies config section returns the built-in constants."""
        prefixes, exact = _cookie_skip_filters()
        assert prefixes == SKIP_PREFIXES
        assert exact == SKIP_EXACT

    def test_defaults_when_cookies_section_empty(self) -> None:
        """An empty cookies section also falls back to the defaults."""
        with _with_config({"cookies": {}}):
            prefixes, exact = _cookie_skip_filters()
        assert prefixes == SKIP_PREFIXES
        assert exact == SKIP_EXACT

    def test_custom_prefixes_and_exact_from_config(self) -> None:
        """Config-supplied lists override the defaults."""
        raw = {
            "cookies": {
                "skip_cookie_prefixes": ["_xyz", "acme-"],
                "skip_cookies": ["JunkOne", "JunkTwo"],
            }
        }
        with _with_config(raw):
            prefixes, exact = _cookie_skip_filters()
        assert prefixes == ("_xyz", "acme-")
        assert exact == frozenset({"JunkOne", "JunkTwo"})

    def test_partial_override_keeps_defaults_for_absent_key(self) -> None:
        """Only prefixes overridden -> exact list still comes from the default."""
        raw = {"cookies": {"skip_cookie_prefixes": ["_only"]}}
        with _with_config(raw):
            prefixes, exact = _cookie_skip_filters()
        assert prefixes == ("_only",)
        assert exact == SKIP_EXACT

    def test_config_error_falls_back_to_defaults(self) -> None:
        """If reading config raises, the defaults are returned (never crash)."""
        with _with_config(None, error=True):
            prefixes, exact = _cookie_skip_filters()
        assert prefixes == SKIP_PREFIXES
        assert exact == SKIP_EXACT


class TestNormalize:
    """_normalize picks auth cookies and normalizes _v2 aliases."""

    def test_auth_cookies_kept_junk_dropped(self) -> None:
        """Auth cookies survive, prefixed + exact junk is filtered out."""
        cookies = [
            {"name": "ltuid", "value": "123"},
            {"name": "ltoken", "value": "abc"},
            {"name": "_ga", "value": "junk"},          # prefix default
            {"name": "mi18nLang", "value": "en"},      # exact default
            {"name": "", "value": "no-name"},          # empty name
            {"name": "empty", "value": ""},            # empty value
        ]
        out = _normalize(cookies)
        assert out == {"ltuid": "123", "ltoken": "abc"}

    def test_v2_alias_fills_missing_base(self) -> None:
        """ltuid_v2/ltoken_v2 populate the base names when absent."""
        cookies = [
            {"name": "ltuid_v2", "value": "u2"},
            {"name": "ltoken_v2", "value": "t2"},
        ]
        out = _normalize(cookies)
        assert out["ltuid"] == "u2"
        assert out["ltoken"] == "t2"

    def test_base_takes_priority_over_v2(self) -> None:
        """When both base and _v2 exist, the base value wins."""
        cookies = [
            {"name": "ltuid", "value": "base"},
            {"name": "ltuid_v2", "value": "v2"},
            {"name": "ltoken", "value": "base"},
            {"name": "ltoken_v2", "value": "v2"},
        ]
        out = _normalize(cookies)
        assert out["ltuid"] == "base"
        assert out["ltoken"] == "base"

    def test_custom_skip_filters_applied(self) -> None:
        """Config-supplied skip lists are honored by _normalize."""
        cookies = [
            {"name": "acme-cookie", "value": "1"},
            {"name": "JunkOne", "value": "2"},
            {"name": "ltuid", "value": "u"},
        ]
        with _with_config(
            {
                "cookies": {
                    "skip_cookie_prefixes": ["acme-"],
                    "skip_cookies": ["JunkOne"],
                }
            }
        ):
            out = _normalize(cookies)
        assert out == {"ltuid": "u"}

    def test_empty_input(self) -> None:
        """No cookies in, no cookies out."""
        assert _normalize([]) == {}
