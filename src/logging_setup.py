"""Logging configuration for Genshin code monitor.

Provides rotating file handler with size-based rotation, optional colored
console output, sensitive data filtering for cookies/tokens, and Prometheus metrics.
"""

import logging
import logging.handlers
import re
from pathlib import Path
from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Sensitive data patterns to filter from logs
SENSITIVE_PATTERNS = [
    # Bearer tokens (before Authorization header)
    (re.compile(r'Bearer\s+([A-Za-z0-9\-._~+/]+=*)'), r'Bearer ***'),
    # Cookie patterns - match key=value pairs (before Cookie header)
    (re.compile(r'(ltuid|ltoken|cookie_token_v2|account_id|session_id)\s*=\s*([^;,\s]+)'), r'\1=***'),
    # Generic token patterns - match key=value
    (re.compile(r'(token|secret|password|api_key|auth)\s*=\s*([^&,\s]+)'), r'\1=***'),
    # Authorization headers
    (re.compile(r'Authorization:\s*([^\r\n]+)'), r'Authorization: ***'),
    # Cookie headers
    (re.compile(r'Cookie:\s*([^\r\n]+)'), r'Cookie: ***'),
]

# Prometheus metrics (created lazily)
_metrics = {}

def get_metrics():
    """Get or create Prometheus metrics."""
    global _metrics
    if not PROMETHEUS_AVAILABLE:
        return None

    if not _metrics:
        _metrics = {
            'codes_found_total': Counter(
                'genshin_codes_found_total',
                'Total codes found',
                ['source']
            ),
            'codes_redeemed_total': Counter(
                'genshin_codes_redeemed_total',
                'Total codes successfully redeemed',
                ['source', 'account']
            ),
            'redemption_attempts_total': Counter(
                'genshin_redemption_attempts_total',
                'Total redemption attempts',
                ['status']  # success, failed, error
            ),
            'fetch_duration_seconds': Histogram(
                'genshin_fetch_duration_seconds',
                'Source fetch duration in seconds',
                ['source'],
                buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
            ),
            'fetch_errors_total': Counter(
                'genshin_fetch_errors_total',
                'Total fetch errors',
                ['source', 'error_type']
            ),
            'scheduler_runs_total': Counter(
                'genshin_scheduler_runs_total',
                'Total scheduler runs',
                ['status']  # success, failed
            ),
            'scheduler_cycle_duration_seconds': Histogram(
                'genshin_scheduler_cycle_duration_seconds',
                'Scheduler cycle duration in seconds',
                buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
            ),
            'active_sources': Gauge(
                'genshin_active_sources',
                'Number of active sources'
            ),
            'stored_codes': Gauge(
                'genshin_stored_codes',
                'Number of stored codes',
                ['status']  # redeemed, unredeemed
            ),
        }
    return _metrics


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive data in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record, masking sensitive data in message and args."""
        if isinstance(record.msg, str):
            record.msg = self._mask_sensitive(record.msg)

        if record.args:
            record.args = tuple(
                self._mask_sensitive(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )

        return True

    def _mask_sensitive(self, text: str) -> str:
        """Apply all sensitive data patterns to mask sensitive information."""
        for pattern, replacement in SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


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
            print(f"LOGGING ERROR (disk full?): {e}", file=sys.stderr)
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

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)

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
    log_file = Path(config.get("log_file", "logs/app.log"))
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
    file_handler = _create_rotating_file_handler(
        log_file, max_bytes, backup_count, log_level
    )
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


# Metrics helper functions
def record_code_found(source: str) -> None:
    """Record a code found from a source."""
    metrics = get_metrics()
    if metrics:
        metrics['codes_found_total'].labels(source=source).inc()


def record_code_redeemed(source: str, account: str) -> None:
    """Record a successful code redemption."""
    metrics = get_metrics()
    if metrics:
        metrics['codes_redeemed_total'].labels(source=source, account=account).inc()


def record_redemption_attempt(status: str) -> None:
    """Record a redemption attempt."""
    metrics = get_metrics()
    if metrics:
        metrics['redemption_attempts_total'].labels(status=status).inc()


def record_fetch_duration(source: str, duration: float) -> None:
    """Record source fetch duration."""
    metrics = get_metrics()
    if metrics:
        metrics['fetch_duration_seconds'].labels(source=source).observe(duration)


def record_fetch_error(source: str, error_type: str) -> None:
    """Record a fetch error."""
    metrics = get_metrics()
    if metrics:
        metrics['fetch_errors_total'].labels(source=source, error_type=error_type).inc()


def record_scheduler_run(status: str) -> None:
    """Record a scheduler run."""
    metrics = get_metrics()
    if metrics:
        metrics['scheduler_runs_total'].labels(status=status).inc()


def record_scheduler_cycle_duration(duration: float) -> None:
    """Record scheduler cycle duration."""
    metrics = get_metrics()
    if metrics:
        metrics['scheduler_cycle_duration_seconds'].observe(duration)


def set_active_sources(count: int) -> None:
    """Set number of active sources."""
    metrics = get_metrics()
    if metrics:
        metrics['active_sources'].set(count)


def set_stored_codes(redeemed: int, unredeemed: int) -> None:
    """Set stored codes count."""
    metrics = get_metrics()
    if metrics:
        metrics['stored_codes'].labels(status='redeemed').set(redeemed)
        metrics['stored_codes'].labels(status='unredeemed').set(unredeemed)


def get_prometheus_metrics() -> bytes | None:
    """Get Prometheus metrics in text format."""
    if not PROMETHEUS_AVAILABLE:
        return None
    return generate_latest()
