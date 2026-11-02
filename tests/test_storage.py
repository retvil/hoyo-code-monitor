"""Unit tests for the Storage class."""

import gc
import json
import os
import sqlite3
import tempfile
import time

import pytest

from src.storage import Storage

#: Number of times a source error counter is incremented in the tests below.
EXPECTED_ERROR_COUNT: int = 2


@pytest.fixture
def temp_db() -> str:
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Drop strong references to any Storage instances that might still hold
    # the sqlite3 connection open (Windows locks the file until the handle is closed).
    gc.collect()
    if os.path.exists(db_path):
        for _ in range(10):
            try:
                os.unlink(db_path)
                break
            except PermissionError:
                time.sleep(0.25)
        else:
            os.unlink(db_path)


@pytest.fixture
def storage(temp_db: str) -> Storage:
    """Create a Storage instance with temporary database."""
    return Storage(temp_db)


class TestStorageInitialization:
    """Tests for database initialization."""

    def test_init_creates_tables(self, storage: Storage) -> None:
        """Test that all three tables are created on initialization."""
        with storage._connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row["name"] for row in tables}
            assert "codes" in table_names
            assert "sources" in table_names
            assert "config" in table_names

    def test_init_creates_parent_directory(self, temp_db: str) -> None:
        """Test that parent directory is created if it doesn't exist."""
        nested_path = os.path.join(os.path.dirname(temp_db), "nested", "monitor.db")
        Storage(nested_path)
        assert os.path.exists(nested_path)


class TestCodesCRUD:
    """Tests for codes CRUD operations."""

    def test_add_code_happy_path(self, storage: Storage) -> None:
        """Test adding a code successfully."""
        code_id = storage.add_code("GENSHIN123", "wiki")
        assert code_id == 1

        code = storage.get_code("GENSHIN123")
        assert code is not None
        assert code["code"] == "GENSHIN123"
        assert code["sources"] == ["wiki"]
        assert code["redeemed"] == 0
        assert code["reward"] is None
        assert code["redeemed_at"] is None

    def test_add_code_default_timestamp_is_utc(self, storage: Storage) -> None:
        """Default attempted_at is stored as a tz-aware UTC ISO string.

        codes_per_day() buckets on substr(attempted_at,1,10) against SQLite's
        UTC date('now') — storing tz-aware UTC keeps the write side aligned with
        the read side instead of drifting up to 24h.
        """
        storage.add_code("UTCCODE", "wiki")
        with storage._connection() as conn:
            row = conn.execute(
                "SELECT attempted_at FROM codes WHERE code = ?", ("UTCCODE",)
            ).fetchone()
        assert row is not None
        # Naive local isoformat ends in a plain HH:MM:SS[.ffffff]; a tz-aware
        # UTC one always carries an offset suffix ("+00:00" / "Z").
        assert row["attempted_at"].endswith("+00:00") or row[
            "attempted_at"
        ].endswith("Z")

    def test_add_redemption_log_default_timestamp_is_utc(self, storage: Storage) -> None:
        """Same UTC-aware default for the redemption_log write path."""
        account = storage.add_account("acc", "123456", "os_euro")
        storage.add_redemption_log("UTCCODE2", account, "success")
        with storage._connection() as conn:
            row = conn.execute(
                "SELECT attempted_at FROM redemption_log WHERE code = ?",
                ("UTCCODE2",),
            ).fetchone()
        assert row is not None
        assert row["attempted_at"].endswith("+00:00") or row[
            "attempted_at"
        ].endswith("Z")

    def test_add_code_duplicate_same_source_raises(self, storage: Storage) -> None:
        """Test that adding duplicate code from same source raises IntegrityError."""
        storage.add_code("GENSHIN123", "wiki")
        with pytest.raises(Exception) as exc_info:
            storage.add_code("GENSHIN123", "wiki")
        assert "already exists from source" in str(exc_info.value)

    def test_add_code_same_code_different_source_allowed(self, storage: Storage) -> None:
        """Test that same code from different source is allowed (returns existing code_id)."""
        storage.add_code("GENSHIN123", "wiki")
        code_id = storage.add_code("GENSHIN123", "reddit")
        assert code_id == 1  # Returns existing code_id

        code = storage.get_code("GENSHIN123")
        assert code is not None
        assert set(code["sources"]) == {"wiki", "reddit"}

    def test_add_code_race_losing_source_still_links(self, storage: Storage) -> None:
        """Simulate the read-then-insert race: pre-insert the codes row, then add_code
        from a fresh source should land on the IntegrityError branch and still record
        the code_sources link without raising."""
        # Manually seed the codes row so add_code's "no existing row" check will
        # pass, then the INSERT will hit the UNIQUE(code, game) index and enter
        # the except-branch that links the source to the winner's row.
        with storage._connection() as conn:
            cur = conn.execute(
                "INSERT INTO codes (code, attempted_at, game) VALUES (?, ?, ?)",
                ("RACECODE", "2026-01-01T00:00:00", "genshin"),
            )
            winner_id = cur.lastrowid
            conn.execute(
                "INSERT INTO code_sources (code_id, source) VALUES (?, ?)",
                (winner_id, "winner_source"),
            )

        # The second call uses a different source. Because the codes row already
        # exists, this goes through the except-branch and should NOT raise.
        code_id = storage.add_code("RACECODE", "loser_source", game="genshin")
        assert code_id == winner_id

        # Both source names must be linked to the same code row.
        code = storage.get_code("RACECODE", game="genshin")
        assert code is not None
        assert set(code["sources"]) == {"winner_source", "loser_source"}

    def test_add_code_same_source_race_raises(self, storage: Storage) -> None:
        """Same source racing against itself still raises IntegrityError."""
        with storage._connection() as conn:
            conn.execute(
                "INSERT INTO codes (code, attempted_at, game) VALUES (?, ?, ?)",
                ("RACECODE2", "2026-01-01T00:00:00", "genshin"),
            )
            cid = conn.execute("SELECT id FROM codes WHERE code='RACECODE2'").fetchone()[0]
            conn.execute(
                "INSERT INTO code_sources (code_id, source) VALUES (?, ?)",
                (cid, "solo"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            storage.add_code("RACECODE2", "solo", game="genshin")

    def test_get_code_not_found_returns_none(self, storage: Storage) -> None:
        """Test that getting non-existent code returns None."""
        result = storage.get_code("NONEXISTENT")
        assert result is None

    def test_update_code_redemption_success(self, storage: Storage) -> None:
        """Test updating code redemption status to success."""
        storage.add_code("GENSHIN123", "wiki")
        result = storage.update_code_redemption(
            "GENSHIN123", True, "100 Primogems"
        )
        assert result is True

        code = storage.get_code("GENSHIN123")
        assert code["redeemed"] == 1
        assert code["reward"] == "100 Primogems"
        assert code["redeemed_at"] is not None

    def test_update_code_redemption_failure(self, storage: Storage) -> None:
        """Test updating code redemption status to failure."""
        storage.add_code("GENSHIN123", "wiki")
        result = storage.update_code_redemption("GENSHIN123", False)
        assert result is True

        code = storage.get_code("GENSHIN123")
        assert code["redeemed"] == 0
        assert code["reward"] is None
        assert code["redeemed_at"] is None

    def test_update_code_redemption_not_found(self, storage: Storage) -> None:
        """Test updating non-existent code returns False."""
        result = storage.update_code_redemption("NONEXISTENT", True)
        assert result is False

    def test_list_codes_pagination(self, storage: Storage) -> None:
        """Test listing codes with pagination."""
        for i in range(5):
            storage.add_code(f"CODE{i}", "wiki")

        codes = storage.list_codes(limit=2, offset=0)
        assert len(codes) == 2
        assert codes[0]["code"] == "CODE4"  # Most recent first
        assert codes[1]["code"] == "CODE3"

        codes = storage.list_codes(limit=2, offset=2)
        assert len(codes) == 2
        assert codes[0]["code"] == "CODE2"
        assert codes[1]["code"] == "CODE1"

    def test_list_codes_only_unredeemed(self, storage: Storage) -> None:
        """Test listing only unredeemed codes."""
        storage.add_code("CODE1", "wiki")
        storage.add_code("CODE2", "wiki")
        storage.update_code_redemption("CODE1", True)

        codes = storage.list_codes(only_unredeemed=True)
        assert len(codes) == 1
        assert codes[0]["code"] == "CODE2"

    def test_list_codes_empty(self, storage: Storage) -> None:
        """Test listing codes when database is empty."""
        codes = storage.list_codes()
        assert codes == []


class TestSourcesCRUD:
    """Tests for sources CRUD operations."""

    def test_add_source_happy_path(self, storage: Storage) -> None:
        """Test adding a source successfully."""
        source_id = storage.add_source(
            "wiki", "https://example.com", "css", ".code-class"
        )
        assert source_id == 1

        source = storage.get_source("wiki")
        assert source is not None
        assert source["name"] == "wiki"
        assert source["url"] == "https://example.com"
        assert source["selector_type"] == "css"
        assert source["selector"] == ".code-class"
        assert source["enabled"] == 1

    def test_add_source_duplicate_raises_integrity_error(self, storage: Storage) -> None:
        """Test that adding duplicate source name raises IntegrityError."""
        storage.add_source("wiki", "https://example.com", "css", ".code-class")
        with pytest.raises(Exception) as exc_info:
            storage.add_source("wiki", "https://other.com", "xpath", "//div")
        assert "UNIQUE constraint failed" in str(exc_info.value)

    def test_get_source_not_found_returns_none(self, storage: Storage) -> None:
        """Test that getting non-existent source returns None."""
        result = storage.get_source("nonexistent")
        assert result is None

    def test_list_sources(self, storage: Storage) -> None:
        """Test listing all sources."""
        storage.add_source("wiki", "https://wiki.com", "css", ".code")
        storage.add_source("reddit", "https://reddit.com", "json", "data.codes")
        storage.add_source("forum", "https://forum.com", "xpath", "//code", enabled=False)

        sources = storage.list_sources()
        assert len(sources) == 3

        enabled_sources = storage.list_sources(enabled_only=True)
        assert len(enabled_sources) == 2
        assert all(s["enabled"] == 1 for s in enabled_sources)

    def test_update_source(self, storage: Storage) -> None:
        """Test updating source fields."""
        storage.add_source("wiki", "https://old.com", "css", ".old")

        result = storage.update_source("wiki", url="https://new.com", enabled=False)
        assert result is True

        source = storage.get_source("wiki")
        assert source["url"] == "https://new.com"
        assert source["enabled"] == 0
        assert source["selector"] == ".old"  # Unchanged

    def test_update_source_not_found(self, storage: Storage) -> None:
        """Test updating non-existent source returns False."""
        result = storage.update_source("nonexistent", url="https://new.com")
        assert result is False

    def test_update_source_no_changes(self, storage: Storage) -> None:
        """Test updating source with no fields returns False."""
        storage.add_source("wiki", "https://example.com", "css", ".code")
        result = storage.update_source("wiki")
        assert result is False

    def test_delete_source(self, storage: Storage) -> None:
        """Test deleting a source."""
        storage.add_source("wiki", "https://example.com", "css", ".code")
        result = storage.delete_source("wiki")
        assert result is True

        source = storage.get_source("wiki")
        assert source is None

    def test_delete_source_not_found(self, storage: Storage) -> None:
        """Test deleting non-existent source returns False."""
        result = storage.delete_source("nonexistent")
        assert result is False

    def test_increment_source_error(self, storage: Storage) -> None:
        """Test incrementing the error counter of a source."""
        storage.add_source("wiki", "https://example.com", "css", ".code")

        source = storage.get_source("wiki")
        assert source["error_count"] == 0

        storage.increment_source_error("wiki")
        storage.increment_source_error("wiki")

        source = storage.get_source("wiki")
        assert source["error_count"] == EXPECTED_ERROR_COUNT

    def test_increment_source_error_unknown_source_is_noop(self, storage: Storage) -> None:
        """Test incrementing a missing source does not raise."""
        storage.increment_source_error("nonexistent")

    def test_increment_source_error_does_not_touch_check_count(
        self, storage: Storage
    ) -> None:
        """Test that error counting is independent of check/success counts."""
        storage.add_source("wiki", "https://example.com", "css", ".code")
        storage.increment_source_error("wiki")

        source = storage.get_source("wiki")
        assert source["check_count"] == 0
        assert source["success_count"] == 0
        assert source["error_count"] == 1


class TestConfigCRUD:
    """Tests for config CRUD operations."""

    def test_set_and_get_config(self, storage: Storage) -> None:
        """Test setting and getting a config value."""
        storage.set_config("interval", "30")
        value = storage.get_config("interval")
        assert value == "30"

    def test_get_config_default(self, storage: Storage) -> None:
        """Test getting non-existent config returns default."""
        value = storage.get_config("nonexistent", "default_value")
        assert value == "default_value"

    def test_get_config_none_default(self, storage: Storage) -> None:
        """Test getting non-existent config returns None by default."""
        value = storage.get_config("nonexistent")
        assert value is None

    def test_update_config(self, storage: Storage) -> None:
        """Test updating an existing config value."""
        storage.set_config("interval", "30")
        storage.set_config("interval", "60")
        value = storage.get_config("interval")
        assert value == "60"

    def test_delete_config(self, storage: Storage) -> None:
        """Test deleting a config key."""
        storage.set_config("interval", "30")
        result = storage.delete_config("interval")
        assert result is True

        value = storage.get_config("interval")
        assert value is None

    def test_delete_config_not_found(self, storage: Storage) -> None:
        """Test deleting non-existent config returns False."""
        result = storage.delete_config("nonexistent")
        assert result is False

    def test_list_config(self, storage: Storage) -> None:
        """Test listing all config entries."""
        storage.set_config("interval", "30")
        storage.set_config("enabled", "true")
        storage.set_config("db_path", "data/monitor.db")

        config = storage.list_config()
        assert config == {
            "interval": "30",
            "enabled": "true",
            "db_path": "data/monitor.db",
        }


class TestAccountGames:
    """Tests for the per-account 'enabled games' filter (migration v15)."""

    def test_update_account_games_roundtrip(self, storage: Storage) -> None:
        """Setting the games list persists as JSON and reads back the same list."""
        storage.add_account("acc", "123456", "os_euro")
        assert storage.update_account_games("acc", ["genshin", "hsr"]) is True
        assert storage.get_account_games("acc") == ["genshin", "hsr"]

    def test_update_account_games_none_resets_to_all(self, storage: Storage) -> None:
        """Passing None clears the filter; the sentinel reads back as None."""
        storage.add_account("acc", "123456", "os_euro")
        storage.update_account_games("acc", ["hsr"])
        assert storage.update_account_games("acc", None) is True
        assert storage.get_account_games("acc") is None
        # Existing rows default to None (all games) without any explicit set.
        storage.add_account("acc2", "789012", "os_usa")
        assert storage.get_account_games("acc2") is None

    def test_update_account_games_list_accounts_exposes_column(
        self, storage: Storage
    ) -> None:
        """list_accounts rows carry the games column (SELECT * shape)."""
        storage.add_account("acc", "123456", "os_euro")
        rows = storage.list_accounts()
        assert rows and "games" in rows[0]
        assert rows[0]["games"] is None
        storage.update_account_games("acc", ["genshin"])
        rows = storage.list_accounts()
        assert rows[0]["games"] == json.dumps(["genshin"])  # raw stored JSON

    def test_update_account_games_unknown_account(self, storage: Storage) -> None:
        """Updating a missing account is a no-op."""
        assert storage.update_account_games("ghost", ["hsr"]) is False


class TestCookieEncryptionPlaceholders:
    """Tests for cookie encryption placeholder methods."""

    def test_encrypt_decrypt_cookies_roundtrip(self, storage: Storage) -> None:
        """Test that encrypt/decrypt roundtrip works (placeholder)."""
        cookies = {"ltuid": "12345", "ltoken": "abcdef", "cookie_token_v2": "xyz"}
        encrypted = storage.encrypt_cookies(cookies)
        decrypted = storage.decrypt_cookies(encrypted)
        assert decrypted == cookies

    def test_store_and_load_cookies(self, storage: Storage) -> None:
        """Test storing and loading cookies via config."""
        cookies = {"ltuid": "12345", "ltoken": "abcdef"}
        storage.store_cookies(cookies)
        loaded = storage.load_cookies()
        assert loaded == cookies

    def test_load_cookies_not_found(self, storage: Storage) -> None:
        """Test loading cookies when not stored returns empty dict."""
        loaded = storage.load_cookies()
        assert loaded == {}

    def test_decrypt_invalid_json(self, storage: Storage) -> None:
        """Test decrypting invalid JSON returns empty dict."""
        result = storage.decrypt_cookies("not valid json")
        assert result == {}


class TestContextManager:
    """Tests for the connection context manager."""

    def test_connection_closes_after_use(self, storage: Storage) -> None:
        """Test that connection is properly closed after context."""
        with storage._connection() as conn:
            conn.execute("SELECT 1")
        # Connection should be closed, no exception means success

    def test_connection_rollback_on_exception(self, storage: Storage) -> None:
        """Statements inside the context manager are rolled back on exception.

        The context manager runs a single ``BEGIN``/``COMMIT`` transaction across
        the whole block (isolation_level=None), so any write made before an
        exception inside the block must not survive the block.
        """
        with pytest.raises(ValueError, match="Test exception"):
            with storage._connection() as conn:
                conn.execute(
                    "INSERT INTO codes (code, attempted_at, game) VALUES (?, ?, ?)",
                    ("ROLBACK", "2026-01-01T00:00:00", "genshin"),
                )
                raise ValueError("Test exception")

        assert storage.get_code("ROLBACK", game="genshin") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
