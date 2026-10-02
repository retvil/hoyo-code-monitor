"""Scheduler module for Genshin code monitor.

Provides a background scheduler that periodically checks sources for new codes
and attempts redemption if enabled.
"""

import asyncio
import contextlib
import logging
import random
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Callable

from src.checkin import (
    GAME_CHECKIN_CONF,
    STATUS_ALREADY_CLAIMED,
    STATUS_FAILED,
    STATUS_SUCCESS,
    CheckinResult,
    CheckinRunner,
)
from src.config import Config, load_config_from_storage
from src.constants import (
    CHECKIN_FALLBACK_HOUR,
    CHECKIN_FALLBACK_MINUTE,
    DEFAULT_CHECKIN_JITTER_MINUTES,
    DEFAULT_CHECKIN_TIME,
    MAX_CHECKIN_HOUR,
    MAX_CHECKIN_JITTER_MINUTES,
    MAX_CHECKIN_MINUTE,
)
from src.exceptions import CheckinError, ConfigError
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
        last_checkin_run: Last daily check-in time (ISO format string) or None.
        last_checkin_success: Whether the last check-in run had no failures.
        last_checkin_claimed: Games claimed (fresh or earlier) in last check-in run.
        last_checkin_failed: Failed slots in last check-in run.
        next_checkin_run: Next scheduled check-in time (ISO format string) or None.
    """

    running: bool = False
    next_run: str | None = None
    last_run: str | None = None
    last_run_success: bool = True
    last_run_codes_found: int = 0
    last_run_codes_redeemed: int = 0
    error_message: str | None = None
    last_checkin_run: str | None = None
    last_checkin_success: bool = True
    last_checkin_claimed: int = 0
    last_checkin_failed: int = 0
    next_checkin_run: str | None = None


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
        checkin_runner: CheckinRunner | None = None,
    ) -> None:
        """Initialize the scheduler.

        Args:
            storage: Storage instance for database operations.
            config: Configuration instance. If None, loads from storage.
            redeemer: Redeemer instance for code redemption.
            checkin_runner: Check-in runner for daily sign-ins.
        """
        self.storage = storage
        self.config = config or load_config_from_storage(storage)
        self.redeemer = redeemer or Redeemer()
        self.checkin_runner = checkin_runner or CheckinRunner()

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._status = SchedulerStatus()
        self._status_lock = threading.Lock()
        self._run_callback: Callable[[], None] | None = None
        self._seed_done = False
        self._last_checkin_date: str | None = None
        self._next_checkin_run: datetime | None = None
        # Check-in progress tracking
        self._checkin_progress: dict[str, Any] = {}
        self._checkin_progress_lock = threading.Lock()

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
                last_checkin_run=self._status.last_checkin_run,
                last_checkin_success=self._status.last_checkin_success,
                last_checkin_claimed=self._status.last_checkin_claimed,
                last_checkin_failed=self._status.last_checkin_failed,
                next_checkin_run=self._status.next_checkin_run,
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

    def _checkin_enabled(self) -> bool:
        """Global daily check-in kill-switch (storage config, default on)."""
        val = self.storage.get_config("checkin_enabled", "true")
        return val is not None and val.lower() == "true"

    def _parse_checkin_time(self) -> tuple[int, int]:
        """Parse checkin_time config, falling back to 04:00 on bad values."""
        raw = self.storage.get_config("checkin_time", DEFAULT_CHECKIN_TIME)
        raw = raw if raw else DEFAULT_CHECKIN_TIME
        try:
            hour_str, minute_str = raw.strip().split(":")
            hour, minute = int(hour_str), int(minute_str)
        except (ValueError, IndexError, AttributeError):
            logger.warning("Invalid checkin_time %r, falling back", raw)
            return CHECKIN_FALLBACK_HOUR, CHECKIN_FALLBACK_MINUTE
        if not (0 <= hour <= MAX_CHECKIN_HOUR and 0 <= minute <= MAX_CHECKIN_MINUTE):
            logger.warning("Invalid checkin_time %r, falling back", raw)
            return CHECKIN_FALLBACK_HOUR, CHECKIN_FALLBACK_MINUTE
        return hour, minute

    def _parse_checkin_jitter(self) -> int:
        """Parse checkin_jitter_minutes config, clamped to a sane range."""
        try:
            jitter = int(
                self.storage.get_config(
                    "checkin_jitter_minutes", str(DEFAULT_CHECKIN_JITTER_MINUTES)
                )
                or DEFAULT_CHECKIN_JITTER_MINUTES
            )
        except (TypeError, ValueError):
            return DEFAULT_CHECKIN_JITTER_MINUTES
        return max(0, min(jitter, MAX_CHECKIN_JITTER_MINUTES))

    def _next_checkin_datetime(self, now: datetime) -> datetime:
        """Calculate the next daily check-in time (defensive against bad config)."""
        hour, minute = self._parse_checkin_time()
        jitter = self._parse_checkin_jitter()
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        candidate += timedelta(minutes=random.randint(0, jitter))
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    async def _run_checkin_slot(
        self, acc: dict[str, Any], game: str, today: str, summary: dict[str, Any]
    ) -> None:
        """Run one account x game slot, folding the outcome into summary."""
        cookies = self.storage.load_account_cookies(acc["name"]) or {}
        device_id = self.storage.get_account_device_id(acc["name"])
        lang = acc.get("lang", "en-us") or "en-us"
        # Update progress
        with self._checkin_progress_lock:
            self._checkin_progress = {
                "is_running": True,
                "current_account": acc["name"],
                "current_game": game,
                "today": today,
            }
        try:
            existing = self.storage.last_checkin_status(acc["id"], game)
            if (
                existing
                and existing.get("claimed_date") == today
                and existing.get("status") in (STATUS_SUCCESS, STATUS_ALREADY_CLAIMED)
            ):
                summary["already"] += 1
                summary["games_claimed"] += 1
                return
            if existing and existing.get("claimed_date") == today:
                # Stale failed/skipped row: clear it so the retry can insert fresh.
                self.storage.delete_checkin_log(acc["id"], game, today)
            result = await self.checkin_runner.run(game, cookies, device_id, today, lang=lang)
            try:
                self.storage.add_checkin_log(acc["id"], result)
            except sqlite3.IntegrityError:
                summary["already"] += 1
                summary["games_claimed"] += 1
                return
            self._tally_result(acc["name"], game, result, summary)
        except (TimeoutError, aiohttp.ClientError, CheckinError) as e:
            logger.exception("Check-in slot failed for %s/%s", acc["name"], game)
            summary["failed"] += 1
            summary["errors"].append(f"{acc['name']}/{game}: {e}")
            with contextlib.suppress(sqlite3.IntegrityError):
                self.storage.add_checkin_log(
                    acc["id"], CheckinResult(game, today, STATUS_FAILED, message=str(e))
                )

    @staticmethod
    def _tally_result(
        account_name: str, game: str, result: CheckinResult, summary: dict[str, Any]
    ) -> None:
        """Fold one slot result into the pass summary."""
        if result.status == STATUS_SUCCESS:
            summary["success_count"] += 1
            summary["games_claimed"] += 1
        elif result.status == STATUS_ALREADY_CLAIMED:
            summary["already"] += 1
            summary["games_claimed"] += 1
        elif result.status == STATUS_FAILED:
            summary["failed"] += 1
            summary["errors"].append(f"{account_name}/{game}: {result.message}")
        else:
            summary["skipped"] += 1

    async def run_daily_checkins(self, claimed_date: str | None = None) -> dict[str, Any]:
        """Run one daily check-in pass over enabled accounts x games.

        Each slot is isolated: per-slot failures are logged and counted,
        never aborting the pass. Re-running for the same date is a no-op
        (slots already logged are skipped).

        Args:
            claimed_date: Local date YYYY-MM-DD (defaults to today).

        Returns:
            Summary dict with games_claimed / already / failed / skipped counts.
        """
        today = claimed_date or date.today().isoformat()
        summary: dict[str, Any] = {
            "success": True,
            "claimed_date": today,
            "games_claimed": 0,
            "success_count": 0,
            "already": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }
        if not self._checkin_enabled():
            logger.info("Daily check-ins disabled, skipping")
            return summary

        accounts = [
            a for a in self.storage.list_accounts()
            if self.storage.is_account_checkin_enabled(a["name"])
        ]
        if not accounts:
            logger.info("No accounts with auto-check-in enabled")
            return summary

        gap = getattr(self.config, "redemption_min_gap_seconds", 8)
        for acc in accounts:
            for game in GAME_CHECKIN_CONF:
                await self._run_checkin_slot(acc, game, today, summary)
                await asyncio.sleep(gap)

        summary["success"] = summary["failed"] == 0
        self._update_status(
            last_checkin_run=datetime.now().isoformat(),
            last_checkin_success=summary["success"],
            last_checkin_claimed=summary["games_claimed"],
            last_checkin_failed=summary["failed"],
        )
        # Clear progress when done
        with self._checkin_progress_lock:
            self._checkin_progress = {}
        return summary

    def get_checkin_progress(self) -> dict[str, Any]:
        """Get current check-in progress (thread-safe).

        Returns:
            Dict with is_running, current_account, current_game, today.
        """
        with self._checkin_progress_lock:
            return dict(self._checkin_progress)

    def _maybe_run_daily_checkins(self) -> None:
        """Fire the daily pass when due (called from the background loop)."""
        try:
            if not self._checkin_enabled():
                return
            today = date.today().isoformat()
            if self._last_checkin_date == today:
                return
            now = datetime.now()
            if self._next_checkin_run is None:
                self._next_checkin_run = self._next_checkin_datetime(now)
            self._update_status(next_checkin_run=self._next_checkin_run.isoformat())
            if now < self._next_checkin_run:
                return
            if self._loop is None:
                return
            self._loop.run_until_complete(self.run_daily_checkins(today))
            self._last_checkin_date = today
            self._next_checkin_run = self._next_checkin_datetime(datetime.now())
            self._update_status(next_checkin_run=self._next_checkin_run.isoformat())
        except Exception:
            logger.exception("Daily check-in pass failed")

    async def catch_up_missed_checkins(self) -> dict[str, Any] | None:
        """Run check-ins for today if the scheduled time has passed and no log exists.

        Called on scheduler startup to handle the case where the PC was off during
        the scheduled check-in time.

        Returns:
            Summary dict from run_daily_checkins if catch-up was needed, None otherwise.
        """
        if not self._checkin_enabled():
            return None
        today = date.today().isoformat()
        if self._last_checkin_date == today:
            return None
        now = datetime.now()
        # Check if scheduled time has already passed today
        hour, minute = self._parse_checkin_time()
        scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < scheduled_today:
            return None  # Scheduled time hasn't passed yet today
        # Skip only if today already has terminal (claimed) entries and nothing
        # failed/skipped waiting for a retry.
        today_rows = [
            row
            for row in self.storage.get_checkin_logs(limit=500)
            if row.get("claimed_date") == today
        ]
        if today_rows and all(
            row.get("status") in (STATUS_SUCCESS, STATUS_ALREADY_CLAIMED)
            for row in today_rows
        ):
            self._last_checkin_date = today
            return None
        logger.info("Catch-up: running missed check-ins for %s", today)
        result = await self.run_daily_checkins(today)
        self._last_checkin_date = today
        return result

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

            # Catch up on missed check-ins once at startup (same thread: no DB contention)
            try:
                self._loop.run_until_complete(self.catch_up_missed_checkins())
            except Exception:
                logger.exception("Check-in catch-up failed")

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

                # Daily HoYoLAB check-ins (independent pipeline, own schedule)
                self._maybe_run_daily_checkins()

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
        # Close the check-in runner's HTTP session (best-effort, non-blocking)
        try:
            asyncio.run(self.close())
        except Exception:
            logger.debug("Failed to close check-in runner", exc_info=True)
        return True

    async def close(self) -> None:
        """Close the check-in runner's underlying HTTP session."""
        await self.checkin_runner.close()

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

    def run_checkins_now(self, claimed_date: str | None = None) -> dict[str, Any]:
        """Run a daily check-in pass immediately (blocking, for manual triggers).

        Args:
            claimed_date: Local date YYYY-MM-DD (defaults to today).

        Returns:
            Summary dict from run_daily_checkins.
        """
        logger.info("Running daily check-ins on demand...")
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.run_daily_checkins(claimed_date))
        finally:
            loop.close()

    def is_running(self) -> bool:
        """Check if scheduler is currently running."""
        return self._thread is not None and self._thread.is_alive()


def create_scheduler_from_storage(db_path: str | None = None) -> Scheduler:
    """Create a scheduler instance with default components from storage.

    Args:
        db_path: Path to SQLite database (defaults to app data dir).

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
