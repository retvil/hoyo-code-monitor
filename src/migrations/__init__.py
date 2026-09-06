"""Database migration system for Genshin code monitor.

Provides versioned schema migrations with up/down support.
"""

from __future__ import annotations

import sqlite3

Migration = tuple[int, str, str]  # (version, up_sql, down_sql)


MIGRATIONS: list[Migration] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR REPLACE INTO schema_version (version) VALUES (1);
        """,
        """
        DROP TABLE IF EXISTS schema_version;
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            attempted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            redeemed BOOLEAN NOT NULL DEFAULT 0,
            reward TEXT,
            redeemed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_codes_source ON codes(source);
        CREATE INDEX IF NOT EXISTS idx_codes_redeemed ON codes(redeemed);
        CREATE INDEX IF NOT EXISTS idx_codes_attempted_at ON codes(attempted_at);
        UPDATE schema_version SET version = 2;
        """,
        """
        DROP INDEX IF EXISTS idx_codes_attempted_at;
        DROP INDEX IF EXISTS idx_codes_redeemed;
        DROP INDEX IF EXISTS idx_codes_source;
        DROP TABLE IF EXISTS codes;
        UPDATE schema_version SET version = 1;
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            selector_type TEXT NOT NULL,
            selector TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            last_checked TIMESTAMP,
            last_error TEXT,
            check_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);
        UPDATE schema_version SET version = 3;
        """,
        """
        DROP INDEX IF EXISTS idx_sources_enabled;
        DROP TABLE IF EXISTS sources;
        UPDATE schema_version SET version = 2;
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        UPDATE schema_version SET version = 4;
        """,
        """
        DROP TABLE IF EXISTS config;
        UPDATE schema_version SET version = 3;
        """,
    ),
    (
        5,
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            uid TEXT NOT NULL,
            region TEXT NOT NULL,
            game_biz TEXT NOT NULL DEFAULT 'hk4e_global',
            lang TEXT NOT NULL DEFAULT 'en-us',
            s_lang_key TEXT NOT NULL DEFAULT 'en-us',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        UPDATE schema_version SET version = 5;
        """,
        """
        DROP TABLE IF EXISTS accounts;
        UPDATE schema_version SET version = 4;
        """,
    ),
    (
        6,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            cookies_encrypted TEXT NOT NULL,
            user_agent TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active BOOLEAN NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_account_id ON sessions(account_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_is_active ON sessions(is_active);
        UPDATE schema_version SET version = 6;
        """,
        """
        DROP INDEX IF EXISTS idx_sessions_is_active;
        DROP INDEX IF EXISTS idx_sessions_account_id;
        DROP TABLE IF EXISTS sessions;
        UPDATE schema_version SET version = 5;
        """,
    ),
    (
        7,
        """
        CREATE TABLE IF NOT EXISTS redemption_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            reward TEXT,
            error_message TEXT,
            attempted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            redeemed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_redemption_log_code ON redemption_log(code);
        CREATE INDEX IF NOT EXISTS idx_redemption_log_account_id ON redemption_log(account_id);
        CREATE INDEX IF NOT EXISTS idx_redemption_log_attempted_at ON redemption_log(attempted_at);
        UPDATE schema_version SET version = 7;
        """,
        """
        DROP INDEX IF EXISTS idx_redemption_log_attempted_at;
        DROP INDEX IF EXISTS idx_redemption_log_account_id;
        DROP INDEX IF EXISTS idx_redemption_log_code;
        DROP TABLE IF EXISTS redemption_log;
        UPDATE schema_version SET version = 6;
        """,
    ),
    (
        8,
        """
        -- Migration v8: Code deduplication across sources
        -- Remove UNIQUE constraint on codes.code, add code_sources junction table
        
        -- Create new codes table without UNIQUE constraint on code
        CREATE TABLE codes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            attempted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            redeemed BOOLEAN NOT NULL DEFAULT 0,
            reward TEXT,
            redeemed_at TIMESTAMP
        );
        
        -- Copy data from old codes table
        INSERT INTO codes_new (id, code, attempted_at, redeemed, reward, redeemed_at)
        SELECT id, code, attempted_at, redeemed, reward, redeemed_at FROM codes;
        
        -- Create code_sources junction table
        CREATE TABLE code_sources (
            code_id INTEGER NOT NULL REFERENCES codes_new(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            PRIMARY KEY (code_id, source)
        );
        
        -- Populate code_sources from old codes table
        INSERT INTO code_sources (code_id, source)
        SELECT id, source FROM codes;
        
        -- Drop old codes table and rename new one
        DROP TABLE codes;
        ALTER TABLE codes_new RENAME TO codes;
        
        -- Recreate indexes
        CREATE INDEX IF NOT EXISTS idx_codes_redeemed ON codes(redeemed);
        CREATE INDEX IF NOT EXISTS idx_codes_attempted_at ON codes(attempted_at);
        CREATE INDEX IF NOT EXISTS idx_code_sources_source ON code_sources(source);
        
        UPDATE schema_version SET version = 8;
        """,
        """
        -- Rollback v8: Restore UNIQUE constraint on codes.code
        DROP INDEX IF EXISTS idx_code_sources_source;
        DROP TABLE IF EXISTS code_sources;
        
        CREATE TABLE codes_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            attempted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            redeemed BOOLEAN NOT NULL DEFAULT 0,
            reward TEXT,
            redeemed_at TIMESTAMP
        );
        
        INSERT INTO codes_old (id, code, source, attempted_at, redeemed, reward, redeemed_at)
        SELECT c.id, c.code, cs.source, c.attempted_at, c.redeemed, c.reward, c.redeemed_at
        FROM codes c
        JOIN code_sources cs ON c.id = cs.code_id;
        
        DROP TABLE codes;
        ALTER TABLE codes_old RENAME TO codes;
        
        CREATE INDEX IF NOT EXISTS idx_codes_source ON codes(source);
        CREATE INDEX IF NOT EXISTS idx_codes_redeemed ON codes(redeemed);
        CREATE INDEX IF NOT EXISTS idx_codes_attempted_at ON codes(attempted_at);
        
        UPDATE schema_version SET version = 7;
        """,
    ),
    (
        9,
        """
        -- Migration v9: Persist all SourceConfig fields in sources table
        ALTER TABLE sources ADD COLUMN headers TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE sources ADD COLUMN timeout_seconds INTEGER NOT NULL DEFAULT 30;
        ALTER TABLE sources ADD COLUMN rate_limit_seconds REAL NOT NULL DEFAULT 1.0;
        ALTER TABLE sources ADD COLUMN requires_browser BOOLEAN NOT NULL DEFAULT 0;
        ALTER TABLE sources ADD COLUMN browser_wait_selector TEXT;
        ALTER TABLE sources ADD COLUMN browser_wait_seconds INTEGER NOT NULL DEFAULT 5;
        ALTER TABLE sources ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 3;
        ALTER TABLE sources ADD COLUMN retry_base_delay REAL NOT NULL DEFAULT 1.0;
        UPDATE schema_version SET version = 9;
        """,
        """
        -- Rollback v9: recreate sources without new columns (SQLite compat)
        CREATE TABLE sources_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            selector_type TEXT NOT NULL,
            selector TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            last_checked TIMESTAMP,
            last_error TEXT,
            check_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO sources_old (id, name, url, selector_type, selector, enabled, last_checked, last_error, check_count, success_count)
        SELECT id, name, url, selector_type, selector, enabled, last_checked, last_error, check_count, success_count FROM sources;
        DROP TABLE sources;
        ALTER TABLE sources_old RENAME TO sources;
        CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);
        UPDATE schema_version SET version = 8;
        """,
    ),
]

CURRENT_VERSION = 9


def get_db_version(conn: sqlite3.Connection) -> int:
    """Get current database schema version."""
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def set_db_version(conn: sqlite3.Connection, version: int) -> None:
    """Set database schema version."""
    conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,))


def run_migrations(db_path: str, target_version: int = CURRENT_VERSION) -> None:
    """Run migrations up to target version."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        current = get_db_version(conn)

        if current > target_version:
            # Rollback
            for version, _, down_sql in reversed(MIGRATIONS):
                if version > target_version and version <= current:
                    conn.executescript(down_sql)
                    conn.commit()
        elif current < target_version:
            # Apply
            for version, up_sql, _ in MIGRATIONS:
                if version > current and version <= target_version:
                    conn.executescript(up_sql)
                    conn.commit()


def get_migration_status(db_path: str) -> list[dict]:
    """Get status of all migrations."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        current = get_db_version(conn)
        return [
            {
                "version": version,
                "applied": version <= current,
                "current": version == current,
            }
            for version, _, _ in MIGRATIONS
        ]


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/monitor.db"
    run_migrations(db_path)
    print(f"Migrations applied to {db_path}")
