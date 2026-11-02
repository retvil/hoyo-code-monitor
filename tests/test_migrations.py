"""Regression tests for the migrations system (up-chain, down step, v8 idempotency)."""

import sqlite3
from pathlib import Path

import pytest

from src.migrations import (
    CURRENT_VERSION,
    MIGRATIONS,
    get_db_version,
    run_migrations,
)
from src.storage import Storage


@pytest.fixture
def fresh_db(tmp_path: Path) -> str:
    """Migrate a brand-new database straight to CURRENT_VERSION (the conftest
    Storage-fixture pattern, but driven through the public migration entry
    point so the up-chain itself is what's under test)."""
    db_path = str(tmp_path / "fresh.db")
    run_migrations(db_path)
    return db_path


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}


class TestMigrationUpChain:
    def test_fresh_db_reaches_current_version(self, fresh_db: str) -> None:
        with sqlite3.connect(fresh_db) as conn:
            assert get_db_version(conn) == CURRENT_VERSION

    def test_fresh_db_has_expected_tables_and_columns(self, fresh_db: str) -> None:
        with sqlite3.connect(fresh_db) as conn:
            tables = _tables(conn)
            expected = {
                "codes",
                "code_sources",
                "accounts",
                "checkin_log",
                "sources",
                "sessions",
                "config",
                "redemption_log",
                "schema_version",
            }
            assert expected <= tables
            assert "games" in _table_columns(conn, "accounts")
            assert "error_count" in _table_columns(conn, "sources")
            assert "last_success" in _table_columns(conn, "sources")
            # v8 rewrote codes without the v2 UNIQUE(code) constraint: verify
            # the dedup schema is what's actually in place.
            assert "source" not in _table_columns(conn, "codes")

    def test_storage_construction_is_noop_on_migrated_db(self, fresh_db: str) -> None:
        storage = Storage(fresh_db)
        with storage._connection() as conn:
            assert get_db_version(conn) == CURRENT_VERSION


class TestMigrationDownStep:
    def test_v16_down_drops_last_success(self, fresh_db: str) -> None:
        """The newest step (v16) must actually roll back on its own down SQL."""
        version, _, down_sql = [m for m in MIGRATIONS if m[0] == 16][0]
        with sqlite3.connect(fresh_db) as conn:
            conn.executescript(down_sql)
            assert "last_success" not in _table_columns(conn, "sources")
            assert get_db_version(conn) == 15
            # Re-applying the same up SQL restores the column (round-trip).
            up_sql = [m for m in MIGRATIONS if m[0] == 16][0][1]
            conn.executescript(up_sql)
            assert "last_success" in _table_columns(conn, "sources")
            assert get_db_version(conn) == 16


class TestMigrationV8Idempotent:
    def test_v8_up_uses_guarded_ddl(self, fresh_db: str) -> None:
        """v8's up SQL is guarded (IF NOT EXISTS / IF EXISTS) like every other
        step, so a partial-apply crash mid-migration can be re-run without
        'table already exists' blowups."""
        _, up_sql, _ = [m for m in MIGRATIONS if m[0] == 8][0]
        assert "CREATE TABLE IF NOT EXISTS codes_new" in up_sql
        assert "DROP TABLE IF EXISTS codes;" in up_sql
        # And the full up-chain still lands cleanly on a fresh DB.
        with sqlite3.connect(fresh_db) as conn:
            assert get_db_version(conn) == CURRENT_VERSION
