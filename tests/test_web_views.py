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

    def test_malformed_last_checked_falls_back_to_idle(self, storage: Storage) -> None:
        storage.add_source(
            name="broken", url="https://example.com", selector_type="css", selector=".code"
        )
        with storage._connection() as conn:
            conn.execute(
                "UPDATE sources SET last_checked = ? WHERE name = ?",
                ("garbage", "broken"),
            )
        result = source_health(storage)
        assert result["sources"][0]["state"] == "idle"

    def test_health_matches_staleness_helper(self, storage: Storage) -> None:
        """source_health must agree with is_source_stale for the same input."""
        storage.add_source(
            name="old", url="https://example.com", selector_type="css", selector=".code"
        )
        stale_ts = _iso(STALE_MINUTES_AGO)
        with storage._connection() as conn:
            conn.execute(
                "UPDATE sources SET last_checked = ? WHERE name = ?", (stale_ts, "old")
            )
        row = source_health(storage)["sources"][0]
        assert is_source_stale(row["last_checked"]) is True
        assert row["state"] == "warning"

    def test_health_survives_storage_failure(self) -> None:
        """The summary must not raise when the storage layer does."""

        boom = "db is gone"

        class ExplodingStorage:
            def list_sources(self, **_kwargs: Any) -> list[dict[str, Any]]:
                raise RuntimeError(boom)

        result = source_health(ExplodingStorage())  # type: ignore[arg-type]
        assert result["count"] == 0
        assert boom in result["error"]


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
        assert f"id='{'redeem' if 'redeem' in render.__name__ else 'checkin'}-{ACCOUNT_NAME}'" in html
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
            "## Что нового (Русский)\nРусские заметки здесь\n"  # noqa: RUF001
        )
        update = UpdateInfo(
            "9.9.9", "1.2.2", "https://x", "english notes", release_notes_raw=raw
        )
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
            "## Что нового (Русский)\nРусские заметки здесь\n"  # noqa: RUF001
        )
        update = UpdateInfo(
            "9.9.9", "1.2.2", "https://x", "english notes", release_notes_raw=raw
        )
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
            "## Что нового (Русский)\nРусские заметки.\n\n"  # noqa: RUF001
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
