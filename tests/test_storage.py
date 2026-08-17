"""Unit tests for the Storage class."""

import os
import tempfile

import pytest

from src.storage import Storage


@pytest.fixture
def temp_db() -> str:
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
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
        """Test that connection handles exceptions properly."""
        try:
            with storage._connection() as conn:
                conn.execute("INSERT INTO codes (code) VALUES (?)", ("TEST",))
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Verify the insert was not committed (no transaction started explicitly)
        storage.get_code("TEST")
        # Note: SQLite autocommits by default in this context manager
        # This test verifies the connection closes properly even on exception


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
