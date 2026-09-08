"""Central constants for Genshin Code Monitor.

All magic values extracted here for ruff PLR2004 compliance and readability.
"""

from __future__ import annotations

# --- Masking ---
MASK_VISIBLE_CHARS: int = 4
MASK_CHAR: str = "*"

# --- Codes ---
MIN_CODE_LENGTH: int = 8
MAX_CODE_LENGTH: int = 14
CODE_PATTERN: str = r"\b[A-Z0-9]{8,14}\b"

# --- Sources defaults ---
DEFAULT_TIMEOUT_SECONDS: int = 30
DEFAULT_RATE_LIMIT_SECONDS: float = 1.0
DEFAULT_BROWSER_WAIT_SECONDS: int = 5
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BASE_DELAY: float = 1.0

# --- Scheduler ---
DEFAULT_POLL_INTERVAL_SECONDS: int = 900
DEFAULT_REDEMPTION_MIN_GAP_SECONDS: int = 8
DEFAULT_SOURCE_TIMEOUT_SECONDS: int = 30
DEFAULT_MAX_RETRY_ATTEMPTS: int = 3

# --- Storage ---
DEFAULT_DB_PATH: str = "data/monitor.db"
DEFAULT_CODE_SOURCES_LIMIT: int = 100

# --- Logging ---
DEFAULT_MAX_LOG_SIZE: int = 10 * 1024 * 1024  # 10 MB
DEFAULT_BACKUP_COUNT: int = 5
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_LOG_FILE: str = "logs/app.log"

# --- Health / Tray ---
HEALTH_RATE_LIMIT_SECONDS: float = 5.0
TRAY_ICON_SIZE: int = 64

# --- HTTP ---
HTTP_TOO_MANY_REQUESTS: int = 429
HTTP_INTERNAL_ERROR: int = 500
HTTP_BAD_GATEWAY: int = 502
HTTP_SERVICE_UNAVAILABLE: int = 503
HTTP_GATEWAY_TIMEOUT: int = 504
HTTP_SERVER_ERROR_MIN: int = 500
HTTP_SERVER_ERROR_MAX: int = 600

# --- Validation ---
MIN_REDEMPTION_GAP: int = 6

# --- Web ---
WEB_HOST: str = "127.0.0.1"
WEB_PORT: int = 8000

# --- App identity ---
APP_VERSION: str = "0.1.0"
APP_AUTHOR: str = "Nod33Eset"

# --- CLI / Display ---
MAX_DISPLAY_CODES: int = 5
MAX_DISPLAY_SOURCES: int = 10

# --- Tests helpers ---
TEST_VISIBLE_CHARS: int = 4  # same as MASK_VISIBLE, used in tests masking assertions
