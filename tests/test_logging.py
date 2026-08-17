"""Unit tests for logging_setup module."""

import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.logging_setup import (
    SensitiveDataFilter,
    _create_console_handler,
    _create_rotating_file_handler,
    _get_log_level,
    get_logger,
    setup_logging,
)


class TestGetLogLevel:
    """Tests for _get_log_level function."""

    def test_default_info(self) -> None:
        """Test default log level is INFO."""
        assert _get_log_level(None) == logging.INFO
        assert _get_log_level("") == logging.INFO

    def test_valid_levels(self) -> None:
        """Test all valid log level strings."""
        assert _get_log_level("DEBUG") == logging.DEBUG
        assert _get_log_level("INFO") == logging.INFO
        assert _get_log_level("WARNING") == logging.WARNING
        assert _get_log_level("ERROR") == logging.ERROR
        assert _get_log_level("CRITICAL") == logging.CRITICAL

    def test_case_insensitive(self) -> None:
        """Test log level parsing is case insensitive."""
        assert _get_log_level("debug") == logging.DEBUG
        assert _get_log_level("Info") == logging.INFO
        assert _get_log_level("warning") == logging.WARNING

    def test_invalid_defaults_to_info(self) -> None:
        """Test invalid log level defaults to INFO."""
        assert _get_log_level("INVALID") == logging.INFO
        assert _get_log_level("NOT_A_LEVEL") == logging.INFO


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter class."""

    @pytest.fixture
    def filter_instance(self) -> SensitiveDataFilter:
        """Create a SensitiveDataFilter instance."""
        return SensitiveDataFilter()

    def test_masks_ltuid_cookie(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that ltuid cookie value is masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="ltuid=12345; ltoken=abcdef", args=(), exc_info=None
        )
        filter_instance.filter(record)
        assert "ltuid=***" in record.msg
        assert "ltoken=***" in record.msg
        assert "12345" not in record.msg
        assert "abcdef" not in record.msg

    def test_masks_cookie_token_v2(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that cookie_token_v2 is masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="cookie_token_v2=xyz789", args=(), exc_info=None
        )
        filter_instance.filter(record)
        assert "cookie_token_v2=***" in record.msg
        assert "xyz789" not in record.msg

    def test_masks_bearer_token(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that Bearer tokens are masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", args=(), exc_info=None
        )
        filter_instance.filter(record)
        assert "Bearer ***" in record.msg
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in record.msg

    def test_masks_authorization_header(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that Authorization header is masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Authorization: Basic dXNlcjpwYXNz", args=(), exc_info=None
        )
        filter_instance.filter(record)
        assert "Authorization: ***" in record.msg
        assert "dXNlcjpwYXNz" not in record.msg

    def test_masks_cookie_header(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that Cookie header is masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Cookie: session=abc123; user=john", args=(), exc_info=None
        )
        filter_instance.filter(record)
        assert "Cookie: ***" in record.msg
        assert "session=abc123" not in record.msg

    def test_masks_generic_token_patterns(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that generic token/password patterns are masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="api_key=secret123 password=pass456 token=xyz789", args=(), exc_info=None
        )
        filter_instance.filter(record)
        assert "api_key=***" in record.msg
        assert "password=***" in record.msg
        assert "token=***" in record.msg
        assert "secret123" not in record.msg
        assert "pass456" not in record.msg
        assert "xyz789" not in record.msg

    def test_masks_args(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that sensitive data in log args is masked."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="User cookie: %s", args=("ltuid=12345; ltoken=abcdef",), exc_info=None
        )
        filter_instance.filter(record)
        assert "ltuid=***" in record.args[0]
        assert "ltoken=***" in record.args[0]

    def test_non_string_args_unchanged(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that non-string args are not modified."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Count: %d, Name: %s", args=(42, "test"), exc_info=None
        )
        filter_instance.filter(record)
        assert record.args[0] == 42
        assert record.args[1] == "test"

    def test_returns_true(self, filter_instance: SensitiveDataFilter) -> None:
        """Test that filter returns True to allow the record."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Normal message", args=(), exc_info=None
        )
        assert filter_instance.filter(record) is True


class TestRotatingFileHandler:
    """Tests for _create_rotating_file_handler function."""

    def test_creates_log_directory(self) -> None:
        """Test that log directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "nested" / "logs" / "app.log"
            handler = _create_rotating_file_handler(log_path)
            assert log_path.parent.exists()
            handler.close()

    def test_sets_correct_max_bytes(self) -> None:
        """Test that maxBytes is set correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            handler = _create_rotating_file_handler(log_path, max_bytes=5 * 1024 * 1024)
            assert handler.maxBytes == 5 * 1024 * 1024
            handler.close()

    def test_sets_correct_backup_count(self) -> None:
        """Test that backupCount is set correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            handler = _create_rotating_file_handler(log_path, backup_count=3)
            assert handler.backupCount == 3
            handler.close()

    def test_sets_formatter(self) -> None:
        """Test that formatter is set with correct format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            handler = _create_rotating_file_handler(log_path)
            assert handler.formatter is not None
            # Check format string contains expected fields
            fmt = handler.formatter._fmt
            assert "%(asctime)s" in fmt
            assert "%(levelname)" in fmt
            assert "%(name)s" in fmt
            assert "%(message)s" in fmt
            handler.close()

    def test_has_sensitive_data_filter(self) -> None:
        """Test that SensitiveDataFilter is added to handler."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            handler = _create_rotating_file_handler(log_path)
            filters = handler.filters
            assert any(isinstance(f, SensitiveDataFilter) for f in filters)
            handler.close()

    def test_handles_disk_full_gracefully(self) -> None:
        """Test that emit handles OSError gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "app.log"
            handler = _create_rotating_file_handler(log_path)

            # Mock the original emit to raise OSError
            handler._original_emit = MagicMock(side_effect=OSError("No space left on device"))

            # Should not raise exception
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="Test message", args=(), exc_info=None
            )
            # The safe_emit wrapper should catch the OSError
            try:
                handler.emit(record)
            except OSError:
                pytest.fail("OSError should be caught and not re-raised")
            finally:
                handler.close()


class TestConsoleHandler:
    """Tests for _create_console_handler function."""

    def test_creates_handler_without_colorlog(self) -> None:
        """Test console handler creation when colorlog is not available."""
        with patch.dict("sys.modules", {"colorlog": None}):
            handler = _create_console_handler()
            assert isinstance(handler, logging.StreamHandler)
            assert handler.formatter is not None

    def test_has_sensitive_data_filter(self) -> None:
        """Test that SensitiveDataFilter is added to console handler."""
        with patch.dict("sys.modules", {"colorlog": None}):
            handler = _create_console_handler()
            filters = handler.filters
            assert any(isinstance(f, SensitiveDataFilter) for f in filters)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def _cleanup_logger(self) -> None:
        """Clean up root logger handlers."""
        root = logging.getLogger()
        for handler in root.handlers[:]:
            handler.close()
            root.removeHandler(handler)

    def test_creates_root_logger_with_handlers(self) -> None:
        """Test that setup_logging configures root logger with handlers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "logs" / "app.log"
            config = {"log_file": str(log_file), "console_enabled": False}

            try:
                logger = setup_logging(config)

                assert logger is logging.getLogger()
                assert logger.level == logging.INFO
                assert len(logger.handlers) == 1  # Only file handler
                assert isinstance(logger.handlers[0], logging.handlers.RotatingFileHandler)
            finally:
                self._cleanup_logger()

    def test_uses_config_log_level(self) -> None:
        """Test that log level from config is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            config = {"log_level": "DEBUG", "log_file": str(log_file), "console_enabled": False}

            try:
                logger = setup_logging(config)

                assert logger.level == logging.DEBUG
            finally:
                self._cleanup_logger()

    def test_creates_console_handler_when_enabled(self) -> None:
        """Test that console handler is created when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            config = {"log_file": str(log_file), "console_enabled": True}

            try:
                logger = setup_logging(config)

                assert len(logger.handlers) == 2
                handler_types = [type(h) for h in logger.handlers]
                assert logging.handlers.RotatingFileHandler in handler_types
                assert logging.StreamHandler in handler_types
            finally:
                self._cleanup_logger()

    def test_does_not_create_console_handler_when_disabled(self) -> None:
        """Test that console handler is not created when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            config = {"log_file": str(log_file), "console_enabled": False}

            try:
                logger = setup_logging(config)

                assert len(logger.handlers) == 1
                assert isinstance(logger.handlers[0], logging.handlers.RotatingFileHandler)
            finally:
                self._cleanup_logger()

    def test_clears_existing_handlers(self) -> None:
        """Test that existing handlers are cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"

            # Add a dummy handler first
            root = logging.getLogger()
            dummy_handler = logging.StreamHandler()
            root.addHandler(dummy_handler)

            config = {"log_file": str(log_file), "console_enabled": False}
            try:
                setup_logging(config)

                # Should only have the new file handler (plus pytest's log capture handlers)
                # We check that our dummy handler was removed
                assert dummy_handler not in root.handlers
                # And that we have at least one RotatingFileHandler
                assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers)
            finally:
                self._cleanup_logger()

    def test_log_file_rotation_works(self) -> None:
        """Test that log file rotation works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            config = {
                "log_file": str(log_file),
                "console_enabled": False,
                "log_max_bytes": 100,  # Very small to force rotation
                "log_backup_count": 3,
            }

            logger = setup_logging(config)

            try:
                # Write enough logs to trigger rotation
                for i in range(50):
                    logger.info("Test message %d " + "x" * 50, i)

                # Check that backup files were created
                log_files = list(Path(tmpdir).glob("app.log*"))
                assert len(log_files) > 1  # Main + at least one backup
            finally:
                self._cleanup_logger()

    def test_sensitive_data_not_logged(self) -> None:
        """Test that sensitive data is filtered from log output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            config = {"log_file": str(log_file), "console_enabled": False}

            logger = setup_logging(config)

            try:
                # Log a message with sensitive data
                logger.info("User cookie: ltuid=12345; ltoken=abcdef; cookie_token_v2=xyz")

                # Read the log file
                log_content = log_file.read_text()

                # Verify sensitive data is masked
                assert "ltuid=***" in log_content
                assert "ltoken=***" in log_content
                assert "cookie_token_v2=***" in log_content
                assert "12345" not in log_content
                assert "abcdef" not in log_content
                assert "xyz" not in log_content
            finally:
                self._cleanup_logger()


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_instance(self) -> None:
        """Test that get_logger returns a Logger instance."""
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

    def test_returns_same_logger_for_same_name(self) -> None:
        """Test that get_logger returns the same instance for the same name."""
        logger1 = get_logger("test.module")
        logger2 = get_logger("test.module")
        assert logger1 is logger2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
