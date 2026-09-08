"""SQLite storage wrapper for Genshin code monitor.

Provides CRUD operations for codes, sources, accounts, sessions, and config.
Uses versioned migrations for schema management.
"""

import contextlib
import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from src.migrations import CURRENT_VERSION, run_migrations

logger = logging.getLogger(__name__)


class Storage:
    """SQLite storage for codes, sources, accounts, sessions, and configuration.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "data/monitor.db") -> None:
        """Initialize storage with database path.

        Args:
            db_path: Path to SQLite database file. Defaults to "data/monitor.db".
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = self._get_or_create_fernet()
        run_migrations(str(self.db_path), CURRENT_VERSION)

    def _get_or_create_fernet(self) -> Fernet:
        """Get or create Fernet instance for cookie encryption.

        Tries in order:
        1. Environment variable GENSHIN_ENCRYPTION_KEY
        2. Keyring (system credential store)
        3. File data/.key (600 perms)
        4. Generate and persist to file + keyring

        Returns:
            Fernet instance for encryption/decryption.
        """
        # 1. Env
        key_env = os.environ.get("GENSHIN_ENCRYPTION_KEY")
        if key_env:
            try:
                return Fernet(key_env.encode() if isinstance(key_env, str) else key_env)
            except Exception as e:
                logger.warning("Invalid GENSHIN_ENCRYPTION_KEY: %s, falling back", e)

        # Try keyring
        try:
            import keyring

            key = keyring.get_password("genshin-code-monitor", "encryption-key")
            if key:
                return Fernet(key.encode())
        except Exception:
            pass

        # 3. File fallback data/.key
        try:
            key_path = self.db_path.parent / ".key"
            alt_path = Path("data") / ".key"
            for p in (key_path, alt_path):
                if p.exists():
                    return Fernet(p.read_text(encoding="utf-8").strip().encode())
        except Exception:
            pass

        # 4. Generate new key and persist
        key = Fernet.generate_key().decode()
        try:
            import keyring

            keyring.set_password("genshin-code-monitor", "encryption-key", key)
            logger.info("Generated new encryption key and stored in keyring")
        except Exception:
            pass
        try:
            key_path = self.db_path.parent / ".key"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_text(key, encoding="utf-8")
            try:
                os.chmod(key_path, 0o600)
            except Exception:
                pass
            logger.info("Stored encryption key at %s", key_path)
        except Exception as e:
            logger.warning("Could not persist encryption key: %s; using ephemeral key", e)
        return Fernet(key.encode())

    @contextlib.contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections.

        Yields:
            sqlite3.Connection: Database connection with row factory set.

        Uses DEFERRED transaction, timeout 30s, and proper commit/rollback.
        """
        conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, check_same_thread=False, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # --- Codes CRUD ---

    def add_code(
        self,
        code: str,
        source: str,
        attempted_at: datetime | None = None,
        published_at: datetime | str | None = None,
        expires_at: datetime | str | None = None,
    ) -> int:
        """Add a new code to the database.

        Args:
            code: The promotional code string.
            source: Name of the source where code was found.
            attempted_at: Timestamp when code was attempted. Defaults to now.

        Returns:
            The ID of the inserted or existing code row.

        Raises:
            sqlite3.IntegrityError: If code already exists from the same source.
        """
        if attempted_at is None:
            attempted_at = datetime.now()

        def _ts(v: datetime | str | None) -> str | None:
            if v is None:
                return None
            return v.isoformat() if isinstance(v, datetime) else str(v)

        with self._connection() as conn:
            # Check if code already exists
            existing = conn.execute("SELECT id FROM codes WHERE code = ?", (code,)).fetchone()

            if existing:
                code_id = existing[0]
                # Check if this source is already associated
                existing_source = conn.execute(
                    "SELECT 1 FROM code_sources WHERE code_id = ? AND source = ?",
                    (code_id, source),
                ).fetchone()
                if existing_source:
                    raise sqlite3.IntegrityError(  # noqa: TRY003 -- validation message needs interpolation
                        f"Code '{code}' already exists from source '{source}'"
                    )
                # Add new source association
                conn.execute(
                    "INSERT INTO code_sources (code_id, source) VALUES (?, ?)",
                    (code_id, source),
                )
                conn.commit()
                return code_id

            # Insert new code
            cursor = conn.execute(
                """
                INSERT INTO codes (code, attempted_at, published_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (code, attempted_at.isoformat(), _ts(published_at), _ts(expires_at)),
            )
            code_id = cursor.lastrowid

            # Insert into code_sources junction table
            conn.execute(
                "INSERT INTO code_sources (code_id, source) VALUES (?, ?)",
                (code_id, source),
            )
            conn.commit()
            return code_id

    def set_code_dates(
        self,
        code: str,
        published_at: datetime | str | None = None,
        expires_at: datetime | str | None = None,
    ) -> bool:
        """Set known publish/expiry dates for a code (when source provides them)."""

        def _ts(v: datetime | str | None) -> str | None:
            if v is None:
                return None
            return v.isoformat() if isinstance(v, datetime) else str(v)

        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE codes SET published_at = ?, expires_at = ? WHERE code = ?",
                (_ts(published_at), _ts(expires_at), code),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_code(self, code: str) -> dict[str, Any] | None:
        """Retrieve a code by its code string.

        Args:
            code: The promotional code to look up.

        Returns:
            Dictionary with code data including sources list, or None if not found.
        """
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
            if not row:
                return None
            data = dict(row)
            src_rows = conn.execute(
                "SELECT source FROM code_sources WHERE code_id = ?", (data["id"],)
            ).fetchall()
            data["sources"] = [r[0] for r in src_rows]
            return data

    def update_code_redemption(
        self,
        code: str,
        redeemed: bool,
        reward: str | None = None,
        redeemed_at: datetime | None = None,
    ) -> bool:
        """Update redemption status for a code.

        Args:
            code: The promotional code to update.
            redeemed: Whether the code was successfully redeemed.
            reward: Description of the reward received.
            redeemed_at: Timestamp of redemption. Defaults to now if redeemed.

        Returns:
            True if row was updated, False if code not found.
        """
        if redeemed_at is None and redeemed:
            redeemed_at = datetime.now()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE codes
                SET redeemed = ?, reward = ?, redeemed_at = ?
                WHERE code = ?
                """,
                (int(redeemed), reward, redeemed_at.isoformat() if redeemed_at else None, code),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_codes(
        self,
        limit: int = 100,
        offset: int = 0,
        only_unredeemed: bool = False,
    ) -> list[dict[str, Any]]:
        """List codes with pagination.

        Args:
            limit: Maximum number of codes to return.
            offset: Number of codes to skip.
            only_unredeemed: If True, only return codes not yet redeemed.

        Returns:
            List of code dictionaries with sources.
        """
        query = "SELECT * FROM codes"
        params: list[Any] = []

        if only_unredeemed:
            query += " WHERE redeemed = 0"

        query += " ORDER BY attempted_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            if not rows:
                return []
            result: list[dict[str, Any]] = [dict(r) for r in rows]
            ids = [r["id"] for r in result]
            placeholders = ",".join("?" for _ in ids)
            src_rows = conn.execute(
                f"SELECT code_id, source FROM code_sources WHERE code_id IN ({placeholders})",
                ids,
            ).fetchall()
            mapping: dict[int, list[str]] = {i: [] for i in ids}
            for cid, src in src_rows:
                mapping[cid].append(src)
            for d in result:
                d["sources"] = mapping.get(d["id"], [])
            return result

    def get_stats(self) -> dict[str, Any]:
        """Get redemption statistics.

        Returns:
            Dictionary with total_codes, successful, failed, and by_source counts.
        """
        with self._connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
            successful = conn.execute("SELECT COUNT(*) FROM codes WHERE redeemed = 1").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM codes WHERE redeemed = 0").fetchone()[0]
            by_source_rows = conn.execute(
                "SELECT cs.source, COUNT(*) FROM codes c JOIN code_sources cs ON c.id = cs.code_id GROUP BY cs.source"
            ).fetchall()
            by_source = {row[0]: row[1] for row in by_source_rows}
            return {
                "total_codes": total,
                "successful": successful,
                "failed": failed,
                "by_source": by_source,
            }

    # --- Sources CRUD ---

    def add_source(
        self,
        name: str,
        url: str,
        selector_type: str,
        selector: str,
        enabled: bool = True,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        rate_limit_seconds: float = 1.0,
        requires_browser: bool = False,
        browser_wait_selector: str | None = None,
        browser_wait_seconds: int = 5,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> int:
        """Add a new source to the database."""
        headers_json = json.dumps(headers or {})
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sources (name, url, selector_type, selector, enabled, headers, timeout_seconds, rate_limit_seconds, requires_browser, browser_wait_selector, browser_wait_seconds, max_retries, retry_base_delay)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    url,
                    selector_type,
                    selector,
                    int(enabled),
                    headers_json,
                    timeout_seconds,
                    rate_limit_seconds,
                    int(requires_browser),
                    browser_wait_selector,
                    browser_wait_seconds,
                    max_retries,
                    retry_base_delay,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_source(self, name: str) -> dict[str, Any] | None:
        """Retrieve a source by name.

        Args:
            name: Name of the source to look up.

        Returns:
            Dictionary with source data or None if not found.
        """
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
            return self._decode_source_row(row) if row else None

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """List all sources.

        Args:
            enabled_only: If True, only return enabled sources.

        Returns:
            List of source dictionaries.
        """
        query = "SELECT * FROM sources"
        params: list[Any] = []

        if enabled_only:
            query += " WHERE enabled = 1"

        query += " ORDER BY name"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._decode_source_row(r) for r in rows]

    @staticmethod
    def _decode_source_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["headers"] = json.loads(data.get("headers") or "{}")
        except Exception:
            data["headers"] = {}
        data["enabled"] = bool(data.get("enabled", 1))
        data["requires_browser"] = bool(data.get("requires_browser", 0))
        return data

    def update_source(
        self,
        name: str,
        url: str | None = None,
        selector_type: str | None = None,
        selector: str | None = None,
        enabled: bool | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
        rate_limit_seconds: float | None = None,
        requires_browser: bool | None = None,
        browser_wait_selector: str | None = None,
        browser_wait_seconds: int | None = None,
        max_retries: int | None = None,
        retry_base_delay: float | None = None,
    ) -> bool:
        """Update a source's fields.

        Args:
            name: Name of the source to update.
            url: New URL (optional).
            selector_type: New selector type (optional).
            selector: New selector (optional).
            enabled: New enabled status (optional).

        Returns:
            True if row was updated, False if source not found.
        """
        fields = []
        params: list[Any] = []

        if url is not None:
            fields.append("url = ?")
            params.append(url)
        if selector_type is not None:
            fields.append("selector_type = ?")
            params.append(selector_type)
        if selector is not None:
            fields.append("selector = ?")
            params.append(selector)
        if enabled is not None:
            fields.append("enabled = ?")
            params.append(int(enabled))
        if headers is not None:
            fields.append("headers = ?")
            params.append(json.dumps(headers))
        if timeout_seconds is not None:
            fields.append("timeout_seconds = ?")
            params.append(timeout_seconds)
        if rate_limit_seconds is not None:
            fields.append("rate_limit_seconds = ?")
            params.append(rate_limit_seconds)
        if requires_browser is not None:
            fields.append("requires_browser = ?")
            params.append(int(requires_browser))
        if browser_wait_selector is not None:
            fields.append("browser_wait_selector = ?")
            params.append(browser_wait_selector)
        if browser_wait_seconds is not None:
            fields.append("browser_wait_seconds = ?")
            params.append(browser_wait_seconds)
        if max_retries is not None:
            fields.append("max_retries = ?")
            params.append(max_retries)
        if retry_base_delay is not None:
            fields.append("retry_base_delay = ?")
            params.append(retry_base_delay)

        if not fields:
            return False

        params.append(name)

        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE sources SET {', '.join(fields)} WHERE name = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_source(self, name: str) -> bool:
        """Delete a source by name.

        Args:
            name: Name of the source to delete.

        Returns:
            True if row was deleted, False if source not found.
        """
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM sources WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0

    # --- Accounts CRUD ---

    def add_account(
        self,
        name: str,
        uid: str,
        region: str,
        game_biz: str = "hk4e_global",
        lang: str = "en-us",
        s_lang_key: str = "en-us",
    ) -> int:
        """Add a new account.

        Args:
            name: Unique name for the account.
            uid: Hoyolab user ID.
            region: Server region (e.g., "os_usa", "os_euro", "os_asia", "os_cht").
            game_biz: Game business identifier.
            lang: Language code.
            s_lang_key: Secondary language key.

        Returns:
            The ID of the inserted row.

        Raises:
            sqlite3.IntegrityError: If account name already exists.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO accounts (name, uid, region, game_biz, lang, s_lang_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, uid, region, game_biz, lang, s_lang_key),
            )
            conn.commit()
            return cursor.lastrowid

    def get_account(self, name: str) -> dict[str, Any] | None:
        """Retrieve an account by name."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    def list_accounts(self) -> list[dict[str, Any]]:
        """List all accounts."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
            return [dict(row) for row in rows]

    def update_account(
        self,
        name: str,
        uid: str | None = None,
        region: str | None = None,
        game_biz: str | None = None,
        lang: str | None = None,
        s_lang_key: str | None = None,
    ) -> bool:
        """Update an account's fields."""
        fields = []
        params: list[Any] = []

        if uid is not None:
            fields.append("uid = ?")
            params.append(uid)
        if region is not None:
            fields.append("region = ?")
            params.append(region)
        if game_biz is not None:
            fields.append("game_biz = ?")
            params.append(game_biz)
        if lang is not None:
            fields.append("lang = ?")
            params.append(lang)
        if s_lang_key is not None:
            fields.append("s_lang_key = ?")
            params.append(s_lang_key)

        if not fields:
            return False

        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(name)

        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE accounts SET {', '.join(fields)} WHERE name = ?",
                params,
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_account(self, name: str) -> bool:
        """Delete an account by name (cascades to sessions)."""
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM accounts WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0

    # --- Sessions CRUD ---

    def add_session(
        self,
        account_id: int,
        cookies_encrypted: str,
        user_agent: str | None = None,
        expires_at: datetime | None = None,
    ) -> int:
        """Add a new session for an account."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO sessions (account_id, cookies_encrypted, user_agent, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    account_id,
                    cookies_encrypted,
                    user_agent,
                    expires_at.isoformat() if expires_at else None,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_active_session(self, account_id: int) -> dict[str, Any] | None:
        """Get the active session for an account."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM sessions
                WHERE account_id = ? AND is_active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                (account_id,),
            ).fetchone()
            return dict(row) if row else None

    def deactivate_sessions(self, account_id: int) -> int:
        """Deactivate all sessions for an account."""
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET is_active = 0 WHERE account_id = ?",
                (account_id,),
            )
            conn.commit()
            return cursor.rowcount

    # --- Redemption Log CRUD ---

    def add_redemption_log(
        self,
        code: str,
        account_id: int,
        status: str,
        reward: str | None = None,
        error_message: str | None = None,
        attempted_at: datetime | None = None,
        redeemed_at: datetime | None = None,
    ) -> int:
        """Add a redemption log entry."""
        if attempted_at is None:
            attempted_at = datetime.now()

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO redemption_log (code, account_id, status, reward, error_message, attempted_at, redeemed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    account_id,
                    status,
                    reward,
                    error_message,
                    attempted_at.isoformat(),
                    redeemed_at.isoformat() if redeemed_at else None,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_redemption_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get redemption logs with pagination."""
        query = "SELECT * FROM redemption_log"
        params: list[Any] = []

        if account_id is not None:
            query += " WHERE account_id = ?"
            params.append(account_id)

        query += " ORDER BY attempted_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    # --- Config CRUD ---

    def set_config(self, key: str, value: str) -> None:
        """Set a configuration value.

        Args:
            key: Configuration key.
            value: Configuration value (stored as text).
        """
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """Get a configuration value.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def delete_config(self, key: str) -> bool:
        """Delete a configuration key.

        Args:
            key: Configuration key to delete.

        Returns:
            True if key was deleted, False if not found.
        """
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM config WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def list_config(self) -> dict[str, str]:
        """List all configuration key-value pairs.

        Returns:
            Dictionary of all config entries.
        """
        with self._connection() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
            return {row["key"]: row["value"] for row in rows}

    # --- Cookie encryption ---

    def encrypt_cookies(self, cookies: dict[str, str]) -> str:
        """Encrypt cookies for storage using Fernet.

        Args:
            cookies: Dictionary of cookie name-value pairs.

        Returns:
            Encrypted string representation (base64 encoded).
        """
        data = json.dumps(cookies, separators=(",", ":")).encode()
        return self._fernet.encrypt(data).decode()

    def decrypt_cookies(self, encrypted: str) -> dict[str, str]:
        """Decrypt cookies from storage using Fernet.

        Args:
            encrypted: Encrypted string from storage.

        Returns:
            Dictionary of cookie name-value pairs.
        """
        try:
            data = self._fernet.decrypt(encrypted.encode())
            return json.loads(data.decode())
        except Exception:
            logger.warning("Failed to decrypt cookies; returning empty dict")
            return {}

    def store_cookies(self, cookies: dict[str, str]) -> None:
        """Store encrypted cookies in config.

        Args:
            cookies: Dictionary of cookie name-value pairs.
        """
        encrypted = self.encrypt_cookies(cookies)
        self.set_config("cookies", encrypted)

    def load_cookies(self) -> dict[str, str]:
        """Load and decrypt cookies from config.

        Returns:
            Dictionary of cookie name-value pairs, empty if not found.
        """
        encrypted = self.get_config("cookies")
        if encrypted is None:
            return {}
        return self.decrypt_cookies(encrypted)

    # --- Account cookies (per-account, encrypted) ---

    def _decrypt_maybe(self, value: str) -> dict[str, str]:
        """Try Fernet decrypt, fallback to plain JSON for legacy rows."""
        if not value:
            return {}
        try:
            return self.decrypt_cookies(value)
        except Exception:
            pass
        try:
            return json.loads(value)
        except Exception:
            logger.warning("Failed to decode account cookies; returning empty")
            return {}

    def store_account_cookies(self, account_name: str, cookies: dict[str, str]) -> None:
        """Store encrypted per-account cookies."""
        enc = self.encrypt_cookies(cookies)
        self.set_config(f"account_cookies_{account_name}", enc)

    def load_account_cookies(self, account_name: str) -> dict[str, str]:
        """Load per-account cookies (handles legacy plain JSON)."""
        val = self.get_config(f"account_cookies_{account_name}")
        if val is None:
            return {}
        return self._decrypt_maybe(val)

    def is_account_redeem_enabled(self, account_name: str) -> bool:
        """Check per-account auto-redeem flag (falls back to global flag)."""
        val = self.get_config(f"account_redeem_{account_name}")
        if val is None:
            return self.get_config("redemption_enabled", "false").lower() == "true"
        return val.lower() == "true"

    def set_account_redeem(self, account_name: str, enabled: bool) -> None:
        """Set per-account auto-redeem flag."""
        self.set_config(f"account_redeem_{account_name}", "true" if enabled else "false")


if __name__ == "__main__":
    # Quick test
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        storage = Storage(db_path)
        print("Storage initialized successfully")
        print("Tables:", storage.list_config())
    finally:
        Path(db_path).unlink(missing_ok=True)
