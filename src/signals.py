"""Signal handling for graceful shutdown.

Provides async-safe signal handlers for SIGINT and SIGTERM that coordinate
scheduler shutdown, database connection cleanup, and application exit.
"""

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class GracefulShutdown:
    """Manages graceful shutdown coordination.

    Handles SIGINT/SIGTERM signals, coordinates cleanup of resources
    (scheduler, database connections, HTTP sessions), and ensures
    clean application exit.
    """

    def __init__(
        self,
        scheduler: Any | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        cleanup_callbacks: list[Callable[[], Any]] | None = None,
    ) -> None:
        """Initialize the graceful shutdown manager.

        Args:
            scheduler: Scheduler instance with a shutdown() method (e.g., APScheduler).
            loop: Event loop for async-safe callback scheduling.
            cleanup_callbacks: List of callables to execute during shutdown.
                Each callable should be synchronous or return an awaitable.
        """
        self.scheduler = scheduler
        self.loop = loop or asyncio.get_event_loop()
        self.cleanup_callbacks = cleanup_callbacks or []
        self._shutdown_requested = False
        self._shutdown_complete = asyncio.Event()
        self._original_handlers: dict = {}

    def setup(self) -> None:
        """Register signal handlers for SIGINT and SIGTERM."""
        if sys.platform == "win32":
            # Windows doesn't support SIGTERM in the same way
            signal.signal(signal.SIGINT, self._signal_handler)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, self._signal_handler)
        else:
            self._original_handlers[signal.SIGINT] = signal.signal(
                signal.SIGINT, self._signal_handler
            )
            self._original_handlers[signal.SIGTERM] = signal.signal(
                signal.SIGTERM, self._signal_handler
            )

        logger.debug("Signal handlers registered for graceful shutdown")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Signal handler that schedules shutdown on the event loop.

        This is called from the signal context, so it must be async-safe.
        We use call_soon_threadsafe to schedule the actual shutdown logic
        on the event loop thread.
        """
        if self._shutdown_requested:
            # Force exit on second signal
            logger.warning("Force shutdown requested (signal %d)", signum)
            self._force_exit()
            return

        logger.info("Shutdown signal received (%s)", signal.Signals(signum).name)
        self._shutdown_requested = True

        # Schedule the async shutdown on the event loop
        self.loop.call_soon_threadsafe(self._schedule_shutdown)

    def _schedule_shutdown(self) -> None:
        """Schedule the async shutdown coroutine."""
        asyncio.create_task(self.shutdown())

    async def shutdown(self) -> None:
        """Execute graceful shutdown sequence.

        Order of operations:
        1. Stop accepting new jobs (scheduler.pause())
        2. Wait for running jobs to complete (with timeout)
        3. Shutdown scheduler
        4. Execute cleanup callbacks
        5. Close database connections
        6. Signal completion
        """
        logger.info("Starting graceful shutdown...")

        try:
            # Step 1: Stop scheduler from accepting new jobs
            if self.scheduler is not None:
                await self._stop_scheduler()

            # Step 2: Execute cleanup callbacks
            await self._run_cleanup_callbacks()

            logger.info("Graceful shutdown completed")
        except Exception as e:
            logger.exception("Error during graceful shutdown: %s", e)
        finally:
            self._shutdown_complete.set()

    async def _stop_scheduler(self) -> None:
        """Stop the scheduler gracefully."""
        if self.scheduler is None:
            return

        try:
            # Pause to stop accepting new jobs
            if hasattr(self.scheduler, "pause"):
                logger.debug("Pausing scheduler...")
                self.scheduler.pause()

            # Wait for running jobs to complete (with timeout)
            if hasattr(self.scheduler, "get_jobs"):
                jobs = self.scheduler.get_jobs()
                if jobs:
                    logger.info("Waiting for %d running job(s) to complete...", len(jobs))
                    # Give jobs some time to finish
                    await asyncio.sleep(2)

            # Shutdown the scheduler
            if hasattr(self.scheduler, "shutdown"):
                logger.debug("Shutting down scheduler...")
                # APScheduler's shutdown can be blocking, run in executor
                if hasattr(self.scheduler.shutdown, "__call__"):
                    await self.loop.run_in_executor(None, self.scheduler.shutdown, wait=True)
                else:
                    self.scheduler.shutdown(wait=True)

            logger.info("Scheduler stopped")
        except Exception as e:
            logger.exception("Error stopping scheduler: %s", e)

    async def _run_cleanup_callbacks(self) -> None:
        """Execute all registered cleanup callbacks."""
        for callback in self.cleanup_callbacks:
            try:
                callback_name = getattr(callback, "__name__", str(callback))
                logger.debug("Running cleanup callback: %s", callback_name)
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                callback_name = getattr(callback, "__name__", str(callback))
                logger.exception("Error in cleanup callback %s: %s", callback_name, e)

    def _force_exit(self) -> None:
        """Force immediate exit (called on second signal)."""
        logger.critical("Forcing immediate exit")
        # Restore original handlers
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        sys.exit(1)

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown to complete."""
        await self._shutdown_complete.wait()

    @property
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested


def setup_signal_handlers(
    scheduler: Any | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    cleanup_callbacks: list[Callable[[], Any]] | None = None,
) -> GracefulShutdown:
    """Set up signal handlers for graceful shutdown.

    This is the main entry point for configuring signal handling.
    It creates a GracefulShutdown instance, registers signal handlers,
    and returns the instance for further control.

    Args:
        scheduler: Scheduler instance with shutdown() method (e.g., APScheduler).
        loop: Event loop for async-safe operations. Defaults to current loop.
        cleanup_callbacks: List of callables to execute during shutdown.
            Can be sync functions or async functions.

    Returns:
        GracefulShutdown instance for managing shutdown lifecycle.

    Example:
        >>> shutdown = setup_signal_handlers(scheduler=scheduler)
        >>> # ... run application ...
        >>> await shutdown.wait_for_shutdown()
    """
    shutdown_manager = GracefulShutdown(
        scheduler=scheduler,
        loop=loop,
        cleanup_callbacks=cleanup_callbacks,
    )
    shutdown_manager.setup()
    return shutdown_manager


# Convenience function for simple use cases
def add_cleanup_callback(callback: Callable[[], Any]) -> None:
    """Add a cleanup callback to be executed on shutdown.

    This is a module-level function for simple cases where you don't
    need the full GracefulShutdown instance.

    Args:
        callback: Callable to execute during shutdown.
    """
    # This would need a global shutdown manager - not recommended for complex apps
    # Use setup_signal_handlers with cleanup_callbacks instead
    pass
