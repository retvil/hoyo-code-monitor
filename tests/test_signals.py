"""Unit tests for signals module."""

import asyncio
import signal
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.signals import GracefulShutdown, setup_signal_handlers


class TestGracefulShutdown:
    """Tests for GracefulShutdown class."""

    @pytest.fixture
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """Create a new event loop for testing."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture
    def mock_scheduler(self) -> MagicMock:
        """Create a mock scheduler with required methods."""
        scheduler = MagicMock()
        scheduler.pause = MagicMock()
        scheduler.shutdown = MagicMock()
        scheduler.get_jobs = MagicMock(return_value=[])
        return scheduler

    @pytest.fixture
    def shutdown_manager(
        self, event_loop: asyncio.AbstractEventLoop, mock_scheduler: MagicMock
    ) -> GracefulShutdown:
        """Create a GracefulShutdown instance for testing."""
        return GracefulShutdown(scheduler=mock_scheduler, loop=event_loop)

    def test_initialization(self, shutdown_manager: GracefulShutdown) -> None:
        """Test GracefulShutdown initialization."""
        assert shutdown_manager.scheduler is not None
        assert shutdown_manager.loop is not None
        assert shutdown_manager.cleanup_callbacks == []
        assert shutdown_manager._shutdown_requested is False
        assert isinstance(shutdown_manager._shutdown_complete, asyncio.Event)

    def test_initialization_with_cleanup_callbacks(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test initialization with cleanup callbacks."""
        callback1 = MagicMock()
        callback2 = MagicMock()
        manager = GracefulShutdown(
            loop=event_loop, cleanup_callbacks=[callback1, callback2]
        )
        assert len(manager.cleanup_callbacks) == 2
        assert callback1 in manager.cleanup_callbacks
        assert callback2 in manager.cleanup_callbacks

    def test_setup_registers_signal_handlers(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test that setup() registers signal handlers."""
        with patch("signal.signal") as mock_signal:
            shutdown_manager.setup()
            # Should register SIGINT at minimum
            assert mock_signal.call_count >= 1
            # Check SIGINT was registered
            calls = mock_signal.call_args_list
            sigint_call = next(
                (c for c in calls if c[0][0] == signal.SIGINT), None
            )
            assert sigint_call is not None
            assert sigint_call[0][1] == shutdown_manager._signal_handler

    def test_signal_handler_sets_shutdown_requested(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test that signal handler sets _shutdown_requested flag."""
        assert shutdown_manager._shutdown_requested is False

        # Call the signal handler directly
        shutdown_manager._signal_handler(signal.SIGINT, None)

        assert shutdown_manager._shutdown_requested is True

    def test_signal_handler_schedules_shutdown_on_loop(
        self, shutdown_manager: GracefulShutdown, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test that signal handler schedules shutdown on event loop."""
        with patch.object(event_loop, "call_soon_threadsafe") as mock_call_soon:
            shutdown_manager._signal_handler(signal.SIGINT, None)
            mock_call_soon.assert_called_once()
            # The scheduled callback should be _schedule_shutdown
            scheduled_callback = mock_call_soon.call_args[0][0]
            assert scheduled_callback == shutdown_manager._schedule_shutdown

    def test_second_signal_triggers_force_exit(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test that second signal triggers force exit."""
        shutdown_manager._shutdown_requested = True

        with patch.object(shutdown_manager, "_force_exit") as mock_force_exit:
            shutdown_manager._signal_handler(signal.SIGINT, None)
            mock_force_exit.assert_called_once()

    def test_force_exit_restores_handlers_and_exits(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test that _force_exit restores original handlers and exits."""
        shutdown_manager._original_handlers = {
            signal.SIGINT: signal.SIG_DFL,
            signal.SIGTERM: signal.SIG_DFL,
        }

        with patch("signal.signal") as mock_signal, \
             patch("sys.exit") as mock_exit:
            shutdown_manager._force_exit()

            # Should restore original handlers
            assert mock_signal.call_count == 2
            # Should call sys.exit(1)
            mock_exit.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_shutdown_stops_scheduler(
        self, shutdown_manager: GracefulShutdown, mock_scheduler: MagicMock
    ) -> None:
        """Test that shutdown() stops the scheduler."""
        # Mock run_in_executor to avoid event loop issues
        with patch.object(shutdown_manager.loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            await shutdown_manager.shutdown()

            mock_scheduler.pause.assert_called_once()
            # Verify run_in_executor was called with scheduler.shutdown
            mock_run_in_executor.assert_called_once()
            call_args = mock_run_in_executor.call_args[0]
            assert call_args[0] is None  # executor
            assert callable(call_args[1])  # function to call
            # The function should be scheduler.shutdown with wait=True
            # We can't easily test the partial, so just verify it was scheduled

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_jobs(
        self, shutdown_manager: GracefulShutdown, mock_scheduler: MagicMock
    ) -> None:
        """Test that shutdown waits for running jobs."""
        mock_scheduler.get_jobs.return_value = [MagicMock(), MagicMock()]

        with patch("asyncio.sleep") as mock_sleep, \
             patch.object(shutdown_manager.loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            await shutdown_manager.shutdown()
            mock_sleep.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_shutdown_runs_cleanup_callbacks(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test that shutdown runs all cleanup callbacks."""
        sync_callback = MagicMock()
        sync_callback.__name__ = "sync_callback"
        async_callback = AsyncMock()
        async_callback.__name__ = "async_callback"

        manager = GracefulShutdown(
            loop=event_loop, cleanup_callbacks=[sync_callback, async_callback]
        )

        with patch.object(manager.loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            await manager.shutdown()

            sync_callback.assert_called_once()
            async_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_callback_errors(
        self, event_loop: asyncio.AbstractEventLoop, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that shutdown handles errors in cleanup callbacks gracefully."""
        failing_callback = MagicMock(side_effect=ValueError("Callback failed"))
        failing_callback.__name__ = "failing_callback"
        manager = GracefulShutdown(
            loop=event_loop, cleanup_callbacks=[failing_callback]
        )

        with patch.object(manager.loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            # Should not raise exception
            await manager.shutdown()

            failing_callback.assert_called_once()
            # Should log the error
            assert "Error in cleanup callback" in caplog.text

    @pytest.mark.asyncio
    async def test_shutdown_sets_completion_event(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test that shutdown sets the completion event."""
        assert not shutdown_manager._shutdown_complete.is_set()

        with patch.object(shutdown_manager.loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            await shutdown_manager.shutdown()

            assert shutdown_manager._shutdown_complete.is_set()

    @pytest.mark.asyncio
    async def test_wait_for_shutdown(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test wait_for_shutdown waits for completion."""
        with patch.object(shutdown_manager.loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            # Start shutdown in background
            shutdown_task = asyncio.create_task(shutdown_manager.shutdown())

            # Wait for shutdown should complete when shutdown is done
            await shutdown_manager.wait_for_shutdown()

            await shutdown_task
            assert shutdown_manager._shutdown_complete.is_set()

    def test_is_shutdown_requested_property(
        self, shutdown_manager: GracefulShutdown
    ) -> None:
        """Test is_shutdown_requested property."""
        assert shutdown_manager.is_shutdown_requested is False

        shutdown_manager._shutdown_requested = True

        assert shutdown_manager.is_shutdown_requested is True


class TestSetupSignalHandlers:
    """Tests for setup_signal_handlers function."""

    @pytest.fixture
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """Create a new event loop for testing."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture
    def mock_scheduler(self) -> MagicMock:
        """Create a mock scheduler."""
        scheduler = MagicMock()
        scheduler.pause = MagicMock()
        scheduler.shutdown = MagicMock()
        scheduler.get_jobs = MagicMock(return_value=[])
        return scheduler

    def test_returns_graceful_shutdown_instance(
        self, event_loop: asyncio.AbstractEventLoop, mock_scheduler: MagicMock
    ) -> None:
        """Test that setup_signal_handlers returns GracefulShutdown instance."""
        with patch("signal.signal"):
            shutdown = setup_signal_handlers(
                scheduler=mock_scheduler, loop=event_loop
            )
            assert isinstance(shutdown, GracefulShutdown)
            assert shutdown.scheduler is mock_scheduler
            assert shutdown.loop is event_loop

    def test_registers_signal_handlers(
        self, event_loop: asyncio.AbstractEventLoop, mock_scheduler: MagicMock
    ) -> None:
        """Test that signal handlers are registered."""
        with patch("signal.signal") as mock_signal:
            setup_signal_handlers(scheduler=mock_scheduler, loop=event_loop)
            assert mock_signal.call_count >= 1

    def test_passes_cleanup_callbacks(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test that cleanup callbacks are passed to GracefulShutdown."""
        callback = MagicMock()
        callback.__name__ = "test_callback"
        with patch("signal.signal"):
            shutdown = setup_signal_handlers(
                loop=event_loop, cleanup_callbacks=[callback]
            )
            assert callback in shutdown.cleanup_callbacks

    def test_uses_current_loop_when_none_provided(
        self, mock_scheduler: MagicMock
    ) -> None:
        """Test that current event loop is used when none provided."""
        with patch("signal.signal"), \
             patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            shutdown = setup_signal_handlers(scheduler=mock_scheduler)

            assert shutdown.loop is mock_loop


class TestGracefulShutdownWindows:
    """Tests for Windows-specific signal handling."""

    @pytest.fixture
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """Create a new event loop for testing."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_registers_sigbreak_on_windows(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test that SIGBREAK is registered on Windows."""
        with patch("signal.signal") as mock_signal:
            manager = GracefulShutdown(loop=event_loop)
            manager.setup()

            # Should register SIGINT and SIGBREAK
            calls = mock_signal.call_args_list
            signals_registered = [c[0][0] for c in calls]
            assert signal.SIGINT in signals_registered
            assert hasattr(signal, "SIGBREAK")
            if hasattr(signal, "SIGBREAK"):
                assert signal.SIGBREAK in signals_registered


class TestGracefulShutdownUnix:
    """Tests for Unix-specific signal handling."""

    @pytest.fixture
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """Create a new event loop for testing."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_registers_sigterm_on_unix(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test that SIGTERM is registered on Unix."""
        with patch("signal.signal") as mock_signal:
            manager = GracefulShutdown(loop=event_loop)
            manager.setup()

            calls = mock_signal.call_args_list
            signals_registered = [c[0][0] for c in calls]
            assert signal.SIGINT in signals_registered
            assert signal.SIGTERM in signals_registered


class TestSchedulerShutdownInExecutor:
    """Tests for scheduler shutdown running in executor."""

    @pytest.fixture
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """Create a new event loop for testing."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.mark.asyncio
    async def test_scheduler_shutdown_runs_in_executor(
        self, event_loop: asyncio.AbstractEventLoop
    ) -> None:
        """Test that blocking scheduler.shutdown runs in executor."""
        mock_scheduler = MagicMock()
        mock_scheduler.pause = MagicMock()
        mock_scheduler.get_jobs = MagicMock(return_value=[])
        mock_scheduler.shutdown = MagicMock()

        manager = GracefulShutdown(scheduler=mock_scheduler, loop=event_loop)

        with patch.object(event_loop, "run_in_executor") as mock_run_in_executor:
            mock_run_in_executor.return_value = asyncio.Future()
            mock_run_in_executor.return_value.set_result(None)

            await manager.shutdown()

            # Should call run_in_executor for scheduler.shutdown
            mock_run_in_executor.assert_called()
            # First arg should be None (default executor), second should be shutdown func
            call_args = mock_run_in_executor.call_args[0]
            assert call_args[0] is None
            assert callable(call_args[1])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
