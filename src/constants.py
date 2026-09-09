"""Central constants for HoYo Code Monitor.

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

# --- Games (multi-game support, Phase 2) ---
DEFAULT_GAME: str = "genshin"

GAME_CONF: dict[str, dict[str, str]] = {
    "genshin": {
        "name": "Genshin Impact",
        "game_biz": "hk4e_global",
        "api_host": "sg-hk4e-api.hoyoverse.com",
        "accent": "#3ec6b8",
        "gift_url": "https://genshin.hoyoverse.com/en/gift?code={code}",
    },
    "hsr": {
        "name": "Honkai: Star Rail",
        "game_biz": "hkrpg_global",
        "api_host": "sg-hkrpg-api.hoyoverse.com",
        "accent": "#e5484d",
        "gift_url": "https://hsr.hoyoverse.com/gift?code={code}",
    },
    "zzz": {
        "name": "Zenless Zone Zero",
        "game_biz": "nap_global",
        "api_host": "public-operation-nap.hoyoverse.com",
        "accent": "#8b5cf6",
        "gift_url": "https://zenless.hoyoverse.com/redemption?code={code}",
    },
    "hi3": {
        "name": "Honkai Impact 3rd",
        "game_biz": "bh3_global",
        "api_host": "sg-bh3-api.hoyoverse.com",
        "accent": "#f5a623",
        "gift_url": "https://www.hoyolab.com/article/4886?code={code}",
    },
    "tot": {
        "name": "Tears of Themis",
        "game_biz": "nxx_global",
        "api_host": "sg-nxx-api.hoyoverse.com",
        "accent": "#ec4899",
        "gift_url": "https://tot.hoyoverse.com/en/gift?code={code}",
    },
}

GAMES: tuple[str, ...] = tuple(GAME_CONF.keys())

# --- Redeem links ---
GIFT_URL: str = "https://genshin.hoyoverse.com/en/gift?code={code}"


def gift_url(code: str) -> str:
    """Official web redemption link with pre-filled code."""
    return GIFT_URL.format(code=code)


# --- CLI / Display ---
MAX_DISPLAY_CODES: int = 5
MAX_DISPLAY_SOURCES: int = 10

# --- Tests helpers ---
TEST_VISIBLE_CHARS: int = 4  # same as MASK_VISIBLE, used in tests masking assertions
