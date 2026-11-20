"""Logging configuration for Genshin code monitor.

Provides rotating file handler with size-based rotation, optional colored
console output, and sensitive data filtering for cookies/tokens.
"""

import logging
import logging.handlers
import re
from pathlib import Path
from typing import Any

# Sensitive data patterns to filter from logs
SENSITIVE_PATTERNS = [
    # Bearer tokens (before Authorization header)
    (re.compile(r"Bearer\s+([A-Za-z0-9\-._~+/]+=*)"), r"Bearer ***"),
    # Cookie patterns - match key=value pairs (before Cookie header)
    (
        re.compile(r"(ltuid|ltoken|cookie_token_v2|account_id|session_id)\s*=\s*([^;,\s]+)"),
        r"\1=***",
    ),
    # Generic token patterns - match key=value
    (re.compile(r"(token|secret|password|api_key|auth)\s*=\s*([^&,\s]+)"), r"\1=***"),
    # Authorization headers
    (re.compile(r"Authorization:\s*([^\r\n]+)"), r"Authorization: ***"),
    # Cookie headers
    (re.compile(r"Cookie:\s*([^\r\n]+)"), r"Cookie: ***"),
]


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive data in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record, masking sensitive data in message and args."""
        if isinstance(record.msg, str):
            record.msg = self._mask_sensitive(record.msg)

        if record.args:
            record.args = tuple(
                self._mask_sensitive(arg) if isinstance(arg, str) else arg for arg in record.args
            )

        return True

    def _mask_sensitive(self, text: str) -> str:
        """Apply all sensitive data patterns to mask sensitive information."""
        for pattern, replacement in SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


def _default_log_file() -> str:
    """Default log file path (app data dir aware)."""
    from src.paths import (
        default_log_path,
    )

    return default_log_path()


def _get_log_level(level_str: str | None) -> int:
    """Convert log level string to logging constant."""
    if not level_str:
        return logging.INFO

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_str.upper(), logging.INFO)


def _create_rotating_file_handler(
    log_path: Path,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    level: int = logging.INFO,
) -> logging.handlers.RotatingFileHandler:
    """Create a rotating file handler with error handling for disk full."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    # Add sensitive data filter
    handler.addFilter(SensitiveDataFilter())

    # Wrap emit to handle disk full gracefully
    original_emit = handler.emit

    def safe_emit(record: logging.LogRecord) -> None:
        try:
            original_emit(record)
        except OSError as e:
            # Disk full or other I/O error - log to stderr as fallback
            import sys

            print(f"LOGGING ERROR (disk full?): {e}", file=sys.stderr)  # noqa: T201 -- last-resort stderr fallback, no active logger available
            # Don't re-raise to avoid crashing the application

    # Store original emit for testing
    handler._original_emit = original_emit  # type: ignore[attr-defined]
    handler.emit = safe_emit  # type: ignore[method-assign]

    return handler


def _create_console_handler(level: int = logging.INFO) -> logging.Handler:
    """Create console handler with optional colorlog support."""
    try:
        import colorlog

        handler = colorlog.StreamHandler()
        handler.setLevel(level)

        formatter = colorlog.ColoredFormatter(
            fmt="%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
        handler.setFormatter(formatter)
    except ImportError:
        # Fallback to standard StreamHandler
        handler = logging.StreamHandler()
        handler.setLevel(level)

        standard_formatter: logging.Formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(standard_formatter)

    # Add sensitive data filter
    handler.addFilter(SensitiveDataFilter())

    return handler


def setup_logging(config: dict[str, Any] | None = None) -> logging.Logger:
    """Configure application logging with rotating file and console handlers.

    Args:
        config: Configuration dictionary with optional keys:
            - log_level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            - log_file: Path to log file (default: logs/app.log)
            - log_max_bytes: Max size per log file in bytes (default: 10MB)
            - log_backup_count: Number of backup files to keep (default: 5)
            - console_enabled: Whether to enable console output (default: True)
            - console_level: Console log level (default: same as log_level)

    Returns:
        The root logger instance.
    """
    config = config or {}

    log_level = _get_log_level(config.get("log_level"))
    log_file = Path(config.get("log_file") or _default_log_file())
    if not log_file.is_absolute():
        from src.paths import app_data_dir

        log_file = app_data_dir() / log_file
    max_bytes = config.get("log_max_bytes", 10 * 1024 * 1024)
    backup_count = config.get("log_backup_count", 5)
    console_enabled = config.get("console_enabled", True)
    console_level = _get_log_level(config.get("console_level"))

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Add rotating file handler
    file_handler = _create_rotating_file_handler(log_file, max_bytes, backup_count, log_level)
    root_logger.addHandler(file_handler)

    # Add console handler if enabled
    if console_enabled:
        console_handler = _create_console_handler(console_level)
        root_logger.addHandler(console_handler)

    # Log startup message
    root_logger.info("Logging initialized (level=%s, file=%s)", log_level, log_file)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name.

    This is a convenience function for modules to get a logger
    that inherits the root logger's configuration.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Logger instance.
    """
    return logging.getLogger(name)
