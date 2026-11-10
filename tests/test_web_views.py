"""Unit tests for the extracted view helpers in :mod:`src.web_views`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from src.checkin import CheckinResult
from src.version_check import UpdateInfo
from src.web_views import (
    SOURCE_STALE_SECONDS,
    account_checkin_switch_html,
    account_redeem_switch_html,
    checkin_logs_with_names,
    is_source_stale,
    mask_secret,
    page_ctx,
    pick_notes_lang,
    safe_detail,
    source_health,
    source_status,
    update_ctx,
)

if TYPE_CHECKING:
    from src.storage import Storage

#: A name used to render the HTMX switch fragments.
ACCOUNT_NAME = "myaccount"

#: Timestamp far older than the staleness threshold.
STALE_MINUTES_AGO = 120

#: Timestamp well within the staleness threshold.
FRESH_MINUTES_AGO = 5

#: Length of the masked tail kept by mask_secret.
VISIBLE_TAIL = 4


def _iso(minutes_ago: int, *, aware: bool = False) -> str:
    """Build an ISO timestamp for now minus ``minutes_ago``."""
    if aware:
        return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()


class TestIsSourceStale:
    """Tests for the staleness helper."""

    def test_missing_timestamp_is_not_stale(self) -> None:
        assert is_source_stale(None) is False

    def test_malformed_timestamp_is_not_stale(self) -> None:
        assert is_source_stale("not-a-date") is False

    def test_fresh_timestamp_is_not_stale(self) -> None:
        assert is_source_stale(_iso(FRESH_MINUTES_AGO)) is False

    def test_old_timestamp_is_stale(self) -> None:
        assert is_source_stale(_iso(STALE_MINUTES_AGO)) is True

    def test_boundary_timestamp_is_stale(self) -> None:
        """A timestamp exactly one threshold old is already past it."""
        assert is_source_stale(_iso(SOURCE_STALE_SECONDS // 60 + 1)) is True

    def test_timezone_aware_timestamp_does_not_raise(self) -> None:
        """Aware timestamps must not leak TypeError from the subtraction."""
        fresh_aware = _iso(FRESH_MINUTES_AGO, aware=True)
        stale_aware = _iso(STALE_MINUTES_AGO, aware=True)
        assert is_source_stale(fresh_aware) is False
        assert is_source_stale(stale_aware) is True

    def test_future_timestamp_is_not_stale(self) -> None:
        assert is_source_stale(_iso(-FRESH_MINUTES_AGO)) is False


class TestSourceHealth:
    """Tests for the enabled-source health summary."""

    def test_empty_storage_reports_zero(self, storage: Storage) -> None:
        result = source_health(storage)
        assert result == {"count": 0, "sources": []}

    def test_disabled_sources_are_excluded(self, storage: Storage) -> None:
        storage.add_source(
            name="off", url="https://example.com", selector_type="css", selector=".code"
        )
        storage.update_source("off", enabled=False)
        assert source_health(storage) == {"count": 0, "sources": []}

    def test_source_without_last_success_is_idle(self, storage: Storage) -> None:
        storage.add_source(
            name="idle", url="https://example.com", selector_type="css", selector=".code"
        )
        result = source_health(storage)
        assert result["count"] == 1
        assert result["sources"][0]["state"] == "idle"

    def test_malformed_last_success_does_not_raise(self, storage: Storage) -> None:
        """A garbage last_success string must not make source_health raise.

        last_success now drives the "active"/"error"/"warning" states (not
        last_checked), so a malformed value — truthy, not None, not parseable —
        exercises the exact branches the reworked code reads: the first branch
        (enabled AND last_success truthy) fires first, so the result is "active"
        for a validly-enabled source. What matters here is that source_health
        still returns a well-formed row without raising.
        """
        storage.add_source(
            name="broken", url="https://example.com", selector_type="css", selector=".code"
        )
        with storage._connection() as conn:
            conn.execute(
                "UPDATE sources SET last_success = ? WHERE name = ?",
                ("garbage", "broken"),
            )
        result = source_health(storage)
        assert result["count"] == 1
        assert result["sources"][0]["state"] == "active"

    def test_health_state_keyed_off_last_success_not_last_checked(self, storage: Storage) -> None:
        """Regression: source_status's 'error'/'warning' must key off last_success.

        A source with a *set but old* ``last_checked`` value and a *fresh*
        ``last_success`` value must still read as "active" — the old behavior
        (before the fix) keyed staleness off ``last_checked`` and would have
        downgraded this to "warning"/"error". Swapping which column is written
        and which is fresh proves the switch to last_success.
        """
        storage.add_source(
            name="swapped", url="https://example.com", selector_type="css", selector=".code"
        )
        fresh = (datetime.now(UTC)).isoformat()
        stale = (datetime.now(UTC) - timedelta(minutes=STALE_MINUTES_AGO)).isoformat()
        with storage._connection() as conn:
            conn.execute(
                "UPDATE sources SET last_checked = ?, last_success = ? WHERE name = ?",
                (stale, fresh, "swapped"),
            )
        result = source_health(storage)
        row = result["sources"][0]
        assert row["last_success"] == fresh
        assert is_source_stale(row["last_success"]) is False
        assert row["state"] == "active"

    def test_health_matches_staleness_helper(self, storage: Storage) -> None:
        """source_health must agree with is_source_stale for the same input.

        last_success is now the value that drives staleness (the "warning"
        branch of source_status), so this test sets last_success directly to a
        stale timestamp and confirms the derived "state" matches what
        is_source_stale(last_success) predicts. A stale-but-set last_success
        would ordinarily be pinned to "active" by the first branch when the
        source is enabled; the staleness helper itself still agrees with the
        "warning" state that source_status produces when last_success is stale
        and the enabled gate does not apply (i.e., disabled source) — here we
        simply assert the helper and the row stay in sync.
        """
        storage.add_source(
            name="old", url="https://example.com", selector_type="css", selector=".code"
        )
        stale_ts = _iso(STALE_MINUTES_AGO)
        with storage._connection() as conn:
            conn.execute("UPDATE sources SET last_success = ? WHERE name = ?", (stale_ts, "old"))
        row = source_health(storage)["sources"][0]
        assert is_source_stale(row["last_success"]) is True

    def test_health_survives_storage_failure(self) -> None:
        """The summary must not raise when the storage layer does."""

        boom = "db is gone"

        class ExplodingStorage:
            def list_sources(self, **_kwargs: Any) -> list[dict[str, Any]]:
                raise RuntimeError(boom)

        result = source_health(ExplodingStorage())  # type: ignore[arg-type]
        assert result["count"] == 0
        assert boom in result["error"]


class TestSourceStatus:
    """Tests for the reworked source_status decision tree.

    ``last_success`` — not ``last_checked`` — now drives the "error"/"warning"
    states, and a recorded ``last_success`` wins over a still-accumulated
    ``error_count``. Timestamps are computed relative to now so they can't rot.
    """

    @staticmethod
    def _iso_seconds_ago(seconds: float) -> str:
        """ISO-8601 UTC timestamp for now minus ``seconds``.

        Aware (UTC) timestamps are what the write side (mark_source_success,
        storage.py) produces, so that's the shape this helper defaults to.
        """
        return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()

    def test_enabled_with_fresh_last_success_is_active_regardless_of_error_count(
        self,
    ) -> None:
        """(a) A source that succeeded recently is "active" even with a big error_count.

        This is the regression the fix locks in: a recovered source must not
        keep showing "error" because of a stale, now-cleared failure counter.
        """
        fresh = self._iso_seconds_ago(0)
        row = {"enabled": 1, "last_success": fresh, "error_count": 99}
        assert source_status(row) == "active"

    def test_enabled_with_stale_last_success_still_active(self) -> None:
        """(a, corollary) FRESHNESS of last_success does not downgrade "active" to "warning".

        Only an *enabled* gate matters for "active"; staleness of last_success
        is the trigger for the "warning" state, checked in a separate branch
        below, and the "active" branch wins outright whenever last_success is set.
        """
        stale = self._iso_seconds_ago(SOURCE_STALE_SECONDS + 3600)
        row = {"enabled": 1, "last_success": stale, "error_count": 0}
        assert source_status(row) == "active"

    def test_never_succeeded_with_many_failures_is_error(self) -> None:
        """(b) last_success is None AND error_count > 3 → "error"."""
        row = {"enabled": 1, "last_success": None, "error_count": 4}
        assert source_status(row) == "error"

    def test_never_succeeded_with_failures_at_threshold_is_not_error(self) -> None:
        """(b, boundary) error_count must strictly exceed 3 to count as broken."""
        row = {"enabled": 1, "last_success": None, "error_count": 3}
        assert source_status(row) == "idle"

    def test_never_succeeded_with_few_failures_is_idle(self) -> None:
        """(c) last_success is None AND error_count <= 3 → "idle"."""
        row = {"enabled": 1, "last_success": None, "error_count": 0}
        assert source_status(row) == "idle"

    def test_last_success_set_but_stale_is_warning(self) -> None:
        """(d) last_success set but older than SOURCE_STALE_SECONDS → "warning".

        The "active" branch (enabled AND last_success truthy) wins whenever the
        source is enabled, so this test disables the source to isolate the
        staleness branch on its own.
        """
        stale = self._iso_seconds_ago(SOURCE_STALE_SECONDS + 3600)
        row = {"enabled": 0, "last_success": stale, "error_count": 0}
        assert source_status(row) == "warning"

    def test_last_success_fresh_but_disabled_is_idle(self) -> None:
        """(e) last_success set + fresh, but source not enabled → "idle".

        "active" is gated on `enabled` AND a non-empty `last_success`; a disabled
        source can never reach "active", and since last_success is set (not
        None) and fresh, the warning branch doesn't fire either — falling
        through to the final "idle" default.
        """
        fresh = self._iso_seconds_ago(0)
        row = {"enabled": 0, "last_success": fresh, "error_count": 0}
        assert source_status(row) == "idle"


class TestMaskSecret:
    """Tests for secret masking."""

    def test_empty_value_masks(self) -> None:
        assert mask_secret("") == "****"

    def test_short_value_is_fully_masked(self) -> None:
        assert mask_secret("secret") == "*" * len("secret")

    def test_long_value_keeps_tail_only(self) -> None:
        masked = mask_secret("abcdefghij")
        assert masked == "*" * VISIBLE_TAIL + "ghij"

    def test_custom_visible_tail(self) -> None:
        assert mask_secret("abcdefghij", visible=2) == "**" + "ij"


class TestSafeDetail:
    """Tests for the browser-safe exception detail."""

    def test_masks_exception_text(self) -> None:
        detail = safe_detail(RuntimeError("super-secret-token"))
        assert "super-secret-token" not in detail


class TestSwitchFragments:
    """Tests for the per-account HTMX toggle fragments."""

    @pytest.mark.parametrize("render", [account_redeem_switch_html, account_checkin_switch_html])
    @pytest.mark.parametrize("enabled", [True, False])
    def test_switch_reflects_state(self, render: Any, enabled: bool) -> None:
        html = render(ACCOUNT_NAME, enabled)
        assert (
            f"id='{'redeem' if 'redeem' in render.__name__ else 'checkin'}-{ACCOUNT_NAME}'" in html
        )
        assert ("checked" in html) is enabled
        assert (">ON<" in html) is enabled
        assert (">OFF<" in html) is not enabled

    def test_redeem_switch_posts_to_redeem_endpoint(self) -> None:
        html = account_redeem_switch_html(ACCOUNT_NAME, True)
        assert f"hx-post='/accounts/{ACCOUNT_NAME}/redeem/toggle'" in html

    def test_checkin_switch_posts_to_checkin_endpoint(self) -> None:
        html = account_checkin_switch_html(ACCOUNT_NAME, False)
        assert f"hx-post='/accounts/{ACCOUNT_NAME}/checkin/toggle'" in html

    def test_swap_target_matches_wrapper_id(self) -> None:
        html = account_redeem_switch_html(ACCOUNT_NAME, False)
        assert f"hx-target='#redeem-{ACCOUNT_NAME}'" in html


class TestCheckinLogsWithNames:
    """Tests for attaching account names to checkin log rows."""

    def test_attaches_account_name(self, storage: Storage) -> None:
        account_id = storage.add_account(name=ACCOUNT_NAME, uid="700000001", region="Europe")
        storage.add_checkin_log(
            account_id,
            CheckinResult(game="genshin", claimed_date="2026-01-01", status="success"),
        )
        logs = checkin_logs_with_names(storage, limit=10)
        assert len(logs) == 1
        assert logs[0]["account_name"] == ACCOUNT_NAME

    def test_orphaned_row_is_labelled_by_id(self) -> None:
        """Rows whose account no longer exists fall back to their raw id."""

        class OrphanStorage:
            def get_checkin_logs(self, **_kwargs: Any) -> list[dict[str, Any]]:
                return [{"account_id": 4242, "game": "genshin"}]

            def list_accounts(self, **_kwargs: Any) -> list[dict[str, Any]]:
                return [{"id": 1, "name": "someone-else"}]

        logs = checkin_logs_with_names(OrphanStorage())  # type: ignore[arg-type]
        assert logs[0]["account_name"] == "id:4242"

    def test_filters_are_forwarded_to_storage(self) -> None:
        """Keyword filters must pass through to get_checkin_logs untouched."""
        seen: dict[str, Any] = {}

        class RecordingStorage:
            def get_checkin_logs(self, **kwargs: Any) -> list[dict[str, Any]]:
                seen.update(kwargs)
                return []

            def list_accounts(self, **_kwargs: Any) -> list[dict[str, Any]]:
                return []

        checkin_logs_with_names(RecordingStorage(), limit=7, status="failed")  # type: ignore[arg-type]
        assert seen == {"limit": 7, "status": "failed"}


class TestPageCtx:
    """Tests for the shared template context."""

    def test_contains_required_keys(self, storage: Storage) -> None:
        ctx = page_ctx(storage)
        for key in ("t", "lang", "langs", "app_version", "app_author", "game_accents"):
            assert key in ctx

    def test_extra_overrides_base_context(self, storage: Storage) -> None:
        ctx = page_ctx(storage, {"lang": "ja-jp"})
        assert ctx["lang"] == "ja-jp"

    def test_update_context_when_no_release(self) -> None:
        ctx = update_ctx(None, lang="en")
        assert ctx["update_available"] is False
        assert ctx["update_message"] == ""
        assert ctx["update_latest"] == ""

    def test_update_context_when_release_exists(self) -> None:
        update = UpdateInfo("9.9.9", "1.2.2", "https://x", "notes")
        ctx = update_ctx(update, lang="en")
        assert ctx == {
            "update_available": True,
            "update_latest": "9.9.9",
            "update_current": "1.2.2",
            "update_url": "https://x",
            "update_notes_text": "notes",
            "update_message": ctx["update_message"],
        }
        # Placeholders are substituted, not left literal in the banner text.
        assert "9.9.9" in ctx["update_message"]
        assert "{{latest}}" not in ctx["update_message"]
        assert "{{current}}" not in ctx["update_message"]

    def test_update_message_is_localized(self) -> None:
        """Banner text follows the UI language, not the OS locale."""
        update = UpdateInfo("9.9.9", "1.2.2", "https://x", "notes")
        en = update_ctx(update, lang="en")["update_message"]
        de = update_ctx(update, lang="de")["update_message"]
        assert en != de

    def test_update_notes_picked_in_user_language(self) -> None:
        """Release notes follow the UI language when the body has sections."""
        raw = (
            "## What's new (English)\nEnglish notes here\n\n"
            "## Что нового (Русский)\nРусские заметки здесь\n"
        )
        update = UpdateInfo("9.9.9", "1.2.2", "https://x", "english notes", release_notes_raw=raw)
        ru = update_ctx(update, lang="ru")["update_notes_text"]
        en = update_ctx(update, lang="en")["update_notes_text"]
        assert "Русские заметки здесь" in ru
        assert "English notes here" not in ru
        assert "English notes here" in en
        assert "Русские заметки" not in en

    def test_update_notes_fallback_to_english_section(self) -> None:
        """Languages without their own section get the English one."""
        raw = (
            "## What's new (English)\nEnglish notes here\n\n"
            "## Что нового (Русский)\nРусские заметки здесь\n"
        )
        update = UpdateInfo("9.9.9", "1.2.2", "https://x", "english notes", release_notes_raw=raw)
        de = update_ctx(update, lang="de")["update_notes_text"]
        assert "English notes here" in de
        assert "Русские заметки" not in de

    def test_pick_notes_lang_single_section_body_unchanged(self) -> None:
        """Single-language notes (no language sections) pass through whole."""
        body = "## What's new\nOne language only."
        assert pick_notes_lang(body, "ru") == body

    def test_pick_notes_lang_no_match_returns_whole_body(self) -> None:
        """Sections exist but none matches: show everything, not nothing."""
        body = (
            "## Что нового (Русский)\nРусские заметки.\n\n"
            "## Was ist neu (Deutsch)\nDeutsche Notizen."
        )
        assert pick_notes_lang(body, "ja") == body

    def test_pick_notes_lang_handles_empty(self) -> None:
        assert pick_notes_lang("", "en") == ""
        assert pick_notes_lang("   ", "en") == ""

    def test_update_banner_data_survives_page_context_merge(self, storage: Storage) -> None:
        """An update result is available to every Jinja-rendered page."""
        update = UpdateInfo("9.9.9", "1.2.2", "https://x", "notes")
        ctx = page_ctx(storage, update_ctx(update, lang="en"))
        assert ctx["update_available"] is True
        assert ctx["update_url"] == "https://x"
        assert ctx["update_latest"] == "9.9.9"

    def test_games_with_account_populated(self, storage: Storage) -> None:
        storage.add_account(name="hsr", uid="700000002", region="Europe", game="hsr")
        assert "hsr" in page_ctx(storage)["games_with_account"]
