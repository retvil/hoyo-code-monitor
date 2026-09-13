"""Scheduler module for Genshin code monitor.

Provides a background scheduler that periodically checks sources for new codes
and attempts redemption if enabled.
"""

import asyncio
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from src.config import Config, load_config_from_storage
from src.exceptions import ConfigError
from src.redeemer import Redeemer
from src.sources import SourceFetcher, seed_default_sources
from src.storage import Storage

logger = logging.getLogger(__name__)


@dataclass
class SchedulerStatus:
    """Status information for the scheduler.

    Attributes:
        running: Whether the scheduler is currently running.
        next_run: Next scheduled run time (ISO format string) or None.
        last_run: Last run time (ISO format string) or None.
        last_run_success: Whether the last run completed successfully.
        last_run_codes_found: Number of codes found in last run.
        last_run_codes_redeemed: Number of codes successfully redeemed in last run.
        error_message: Error message from last run if failed.
    """

    running: bool = False
    next_run: str | None = None
    last_run: str | None = None
    last_run_success: bool = True
    last_run_codes_found: int = 0
    last_run_codes_redeemed: int = 0
    error_message: str | None = None


class Scheduler:
    """Background scheduler for periodic code checking and redemption.

    Runs in a separate thread with an asyncio event loop. Checks enabled sources
    at the configured interval and attempts to redeem new codes if redemption
    is enabled and cookies are configured.

    Attributes:
        storage: Storage instance for database operations.
        config: Configuration instance.
        status: Current scheduler status.
    """

    def __init__(
        self,
        storage: Storage,
        config: Config | None = None,
        redeemer: Redeemer | None = None,
    ) -> None:
        """Initialize the scheduler.

        Args:
            storage: Storage instance for database operations.
            config: Configuration instance. If None, loads from storage.
            redeemer: Redeemer instance for code redemption.
        """
        self.storage = storage
        self.config = config or load_config_from_storage(storage)
        self.redeemer = redeemer or Redeemer()

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._status = SchedulerStatus()
        self._status_lock = threading.Lock()
        self._run_callback: Callable[[], None] | None = None
        self._seed_done = False

    @property
    def status(self) -> SchedulerStatus:
        """Get current scheduler status (thread-safe)."""
        with self._status_lock:
            return SchedulerStatus(
                running=self._status.running,
                next_run=self._status.next_run,
                last_run=self._status.last_run,
                last_run_success=self._status.last_run_success,
                last_run_codes_found=self._status.last_run_codes_found,
                last_run_codes_redeemed=self._status.last_run_codes_redeemed,
                error_message=self._status.error_message,
            )

    def _update_status(self, **kwargs) -> None:
        """Update scheduler status (thread-safe)."""
        with self._status_lock:
            for key, value in kwargs.items():
                if hasattr(self._status, key):
                    setattr(self._status, key, value)

    def _calculate_next_run(self) -> str:
        """Calculate next run time as ISO format string."""
        interval_seconds = getattr(self.config, "poll_interval_seconds", 900)
        next_run = datetime.now().timestamp() + interval_seconds
        return datetime.fromtimestamp(next_run).isoformat()

    async def _run_check_cycle(self) -> dict[str, Any]:
        """Run a single check cycle: scrape sources, store codes, attempt redemption.

        Returns:
            Dictionary with cycle results.
        """
        gap = 8
        codes_found = 0
        codes_redeemed = 0
        errors = []

        # Seed default sources if none exist
        await seed_default_sources(self.storage)

        # Get enabled sources from database
        sources_data = self.storage.list_sources(enabled_only=True)
        if not sources_data:
            logger.info("No enabled sources configured")
            return {
                "success": True,
                "codes_found": 0,
                "codes_redeemed": 0,
                "errors": ["No enabled sources configured"],
            }

        # Check if redemption is enabled and configured
        can_redeem = (
            getattr(self.config, "redemption_enabled", False)
            and getattr(self.config, "uid", None)
            and getattr(self.config, "region", None)
            and self.config.cookies.get("ltuid")
            and self.config.cookies.get("ltoken")
        )

        # Resolve accounts for redemption (per-account flags)
        redeem_accounts: list[dict[str, Any]] = []
        if can_redeem:
            accounts = self.storage.list_accounts()
            redeem_accounts = [
                a for a in accounts if self.storage.is_account_redeem_enabled(a["name"])
            ]
            if redeem_accounts:
                acc0 = redeem_accounts[0]
                ac = self.storage.load_account_cookies(acc0["name"])
                if ac:
                    self.config.cookies = ac
            else:
                logger.warning("Redemption enabled but no accounts have auto-redeem on")
                can_redeem = False

        if getattr(self.config, "redemption_enabled", False) and not can_redeem:
            missing = []
            if not getattr(self.config, "uid", None):
                missing.append("uid")
            if not getattr(self.config, "region", None):
                missing.append("region")
            if not self.config.cookies.get("ltuid"):
                missing.append("ltuid cookie")
            if not self.config.cookies.get("ltoken"):
                missing.append("ltoken cookie")
            logger.warning("Redemption enabled but missing config: %s", ", ".join(missing))

        # Fetch codes from all sources using SourceFetcher
        try:
            async with SourceFetcher(self.storage) as fetcher:
                results = await fetcher.fetch_all_enabled()
        except Exception as e:
            logger.error("Error fetching from sources: %s", e)
            return {
                "success": False,
                "codes_found": 0,
                "codes_redeemed": 0,
                "errors": [f"Fetch error: {e}"],
            }

        from src.notify import notify_new_codes, notify_redeemed

        new_codes: list[str] = []

        # Game per source (for multi-game storage)
        source_games = {s["name"]: (s.get("game") or "genshin") for s in sources_data}

        # Process results
        for source_name, codes in results.items():
            for code in codes:
                code = code.strip()
                if not code:
                    continue

                codes_found += 1
                code_game = source_games.get(source_name, "genshin")

                # Try to add code to database (will fail if duplicate)
                try:
                    self.storage.add_code(code, source_name, game=code_game)
                    new_codes.append(code)
                    logger.info("New code found: %s from %s", code[:4] + "****", source_name)

                    # Attempt redemption if enabled and configured
                    if can_redeem:
                        try:
                            # Log redemption per account
                            for idx, acc in enumerate(redeem_accounts):
                                try:
                                    from src.constants import GAME_CONF

                                    acc_game = acc.get("game") or "genshin"
                                    gconf = GAME_CONF.get(acc_game, GAME_CONF["genshin"])
                                    cookies = (
                                        self.storage.load_account_cookies(acc["name"])
                                        or self.config.cookies
                                    )
                                    res = await self.redeemer.redeem_code(
                                        code=code,
                                        cookies=cookies,
                                        uid=acc["uid"],
                                        region=acc["region"],
                                        game_biz=acc.get("game_biz") or gconf["game_biz"],
                                        lang=acc.get("lang", "en-us"),
                                        s_lang_key=acc.get("s_lang_key", "en-us"),
                                        game=acc_game,
                                    )
                                    claimed = res.success or res.raw_response.get("retcode") in (
                                        -2017,
                                        -2018,
                                    )
                                    self.storage.update_code_redemption(
                                        code=code,
                                        redeemed=claimed,
                                        reward=res.reward if res.success else None,
                                        game=code_game,
                                    )
                                    self.storage.add_redemption_log(
                                        code=code,
                                        account_id=acc["id"],
                                        status="success" if claimed else "failed",
                                        reward=res.reward if res.success else None,
                                        error_message=None if claimed else res.message,
                                    )
                                    if claimed:
                                        codes_redeemed += 1
                                        try:
                                            await notify_redeemed(
                                                self.storage,
                                                code,
                                                acc["name"],
                                                res.reward or "claimed",
                                            )
                                        except Exception:
                                            pass
                                except Exception as e:
                                    logger.error(
                                        "Error redeeming code %s for %s: %s",
                                        code[:4] + "****",
                                        acc["name"],
                                        e,
                                    )
                                    errors.append(
                                        f"Redemption error for {code[:4]}**** ({acc['name']}): {e}"
                                    )
                                await asyncio.sleep(gap)
                        except Exception as e:
                            logger.error("Error redeeming code %s: %s", code[:4] + "****", e)
                            errors.append(f"Redemption error for {code[:4]}****: {e}")

                except sqlite3.IntegrityError:
                    continue
                except Exception as e:
                    logger.error("Error storing code %s: %s", code[:4] + "****", e)
                    errors.append(f"Storage error for {code[:4]}****: {e}")

        if new_codes:
            try:
                await notify_new_codes(self.storage, new_codes)
            except Exception:
                pass

        return {
            "success": len(errors) == 0,
            "codes_found": codes_found,
            "codes_redeemed": codes_redeemed,
            "errors": errors,
        }

    def _run_loop(self) -> None:
        """Main scheduler loop running in background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._update_status(running=True, next_run=self._calculate_next_run())
            interval_seconds = getattr(self.config, "poll_interval_seconds", 900)
            logger.info("Scheduler started with interval %d seconds", interval_seconds)

            while not self._stop_event.is_set():
                # Run check cycle
                cycle_start = datetime.now()
                self._update_status(last_run=cycle_start.isoformat())

                try:
                    result = self._loop.run_until_complete(self._run_check_cycle())

                    self._update_status(
                        last_run_success=result["success"],
                        last_run_codes_found=result["codes_found"],
                        last_run_codes_redeemed=result["codes_redeemed"],
                        error_message="; ".join(result["errors"]) if result["errors"] else None,
                    )

                except Exception as e:
                    logger.exception("Unexpected error in check cycle")
                    self._update_status(
                        last_run_success=False,
                        error_message=str(e),
                    )

                # Calculate next run
                next_run = self._calculate_next_run()
                self._update_status(next_run=next_run)

                # Wait for interval or stop event
                wait_seconds = getattr(self.config, "poll_interval_seconds", 900)
                if self._stop_event.wait(timeout=wait_seconds):
                    break  # Stop event was set

        finally:
            self._update_status(running=False, next_run=None)
            if self._loop:
                self._loop.close()
                self._loop = None
            logger.info("Scheduler stopped")

    def start(self) -> bool:
        """Start the scheduler in a background thread.

        Returns:
            True if started successfully, False if already running.

        Raises:
            ValueError: If redemption is enabled but required configuration is missing.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Scheduler already running")
            return False

        # Validate redemption configuration if enabled
        if getattr(self.config, "redemption_enabled", False):
            missing = []
            if not getattr(self.config, "uid", None):
                missing.append("uid")
            if not getattr(self.config, "region", None):
                missing.append("region")
            if not self.config.cookies.get("ltuid"):
                missing.append("ltuid cookie")
            if not self.config.cookies.get("ltoken"):
                missing.append("ltoken cookie")
            if missing:
                raise ConfigError(  # noqa: TRY003 -- validation message needs interpolation
                    f"Redemption enabled but missing required configuration: {', '.join(missing)}. "
                    f"Run 'genshin-code-monitor config set redemption_enabled false' to disable, "
                    f"or configure the missing values."
                )

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="GenshinScheduler")
        self._thread.start()
        return True

    def stop(self, timeout: float = 10.0) -> bool:
        """Stop the scheduler gracefully.

        Args:
            timeout: Maximum time to wait for thread to stop.

        Returns:
            True if stopped successfully, False if not running or timeout.
        """
        if self._thread is None or not self._thread.is_alive():
            logger.warning("Scheduler not running")
            return False

        logger.info("Stopping scheduler...")
        self._stop_event.set()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.error("Scheduler did not stop within timeout")
            return False

        self._thread = None
        logger.info("Scheduler stopped gracefully")
        return True

    def run_once(self) -> dict[str, Any]:
        """Run a single check cycle immediately (blocking).

        Returns:
            Dictionary with cycle results.
        """
        logger.info("Running single check cycle...")
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._run_check_cycle())
        finally:
            loop.close()

    def is_running(self) -> bool:
        """Check if scheduler is currently running."""
        return self._thread is not None and self._thread.is_alive()


def create_scheduler_from_storage(db_path: str = "data/monitor.db") -> Scheduler:
    """Create a scheduler instance with default components from storage.

    Args:
        db_path: Path to SQLite database.

    Returns:
        Configured Scheduler instance.
    """
    storage = Storage(db_path)
    config = load_config_from_storage(storage)
    redeemer = Redeemer()

    return Scheduler(
        storage=storage,
        config=config,
        redeemer=redeemer,
    )
