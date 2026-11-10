"""Single-instance guard via file lock.

Prevents two schedulers/trays from running at once.
Uses portalocker when available, falls back to msvcrt (Windows stdlib) so
frozen builds without the optional dependency still enforce single instance.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Windows-only: check if a PID is still alive using psutil (project dependency)
# or ctypes fallback. Since the entire app is Windows-only, we use psutil first.
try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover - psutil is a required dependency
    _HAS_PSUTIL = False


def _is_process_alive(pid: int) -> bool:
    """Return True if a process with *pid* is still running.

    Uses psutil when available; otherwise falls back to ctypes (Windows API).
    Returns False if the PID cannot be read / the process is gone.
    """
    if _HAS_PSUTIL:
        try:
            return bool(psutil.Process(pid).is_running())
        except Exception:
            return False
    # ctypes fallback - Windows API only
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION=0x1000, FALSE, pid)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_uint(0)
        alive = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
    except Exception:
        return False
    else:
        return alive and exit_code.value == 0x00000001


class SingleInstance:
    """File-lock guard. Hold the object while the app runs."""

    def __init__(self, lock_path: str | Path | None = None) -> None:
        """Initialize the guard.

        Args:
            lock_path: Lock file path (defaults to app data dir).
        """
        if lock_path is None:
            from src.paths import (
                app_data_dir,
            )

            lock_path = app_data_dir() / "app.lock"
        self.lock_path = Path(lock_path)
        self._fh: Any | None = None
        self._use_portalocker = False

    def _close_quietly(self) -> None:
        """Close the lock file handle, ignoring errors."""
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass
        finally:
            self._fh = None

    def _handle_stale_lock(self) -> bool | None:
        """Check a lock we couldn't grab: handle it here when both lockers failed.

        Returns:
            True if the lock was acquired after a stale-lock recovery,
            False if it must be treated as held by a live process,
            None if the holder PID could not be read.
        """
        try:
            content = self.lock_path.read_text(encoding="utf-8").strip()
            if not content:
                return None
            holder_pid = int(content)
            if _is_process_alive(holder_pid):
                # Holder is alive - another instance is truly running.
                self._close_quietly()
                return False
            # Holder is dead - stale lock. Remove the lock file and retry
            # acquisition once.
            try:
                self.lock_path.unlink()
            except Exception:
                logger.warning("Could not remove stale lock file %s", self.lock_path)
            # Release our (empty) file handle and retry
            self._close_quietly()
            return self.acquire()
        except (ValueError, OSError):
            # If we can't read/parse the PID, just give up.
            self._close_quietly()
            return False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if this is the only instance."""

        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.lock_path.open("w", encoding="utf-8")
        except OSError as e:
            logger.warning("Single-instance lock file unavailable: %s", e)
            return False
        try:
            import portalocker

            portalocker.lock(self._fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
            self._use_portalocker = True
        except ImportError:
            try:
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                self._use_portalocker = False
            except (ImportError, OSError):
                # Both portalocker and msvcrt failed.
                outcome = self._handle_stale_lock()
                if outcome is None:
                    self._close_quietly()
                    return False
                return outcome
        except Exception:
            self._close_quietly()
            return False
        # Successfully acquired the lock via portalocker or msvcrt.
        # Write our PID and return success.
        try:
            self._fh.write(str(os.getpid()))
            self._fh.flush()
        except OSError:
            self._close_quietly()
            return False
        return True

    def release(self) -> None:
        """Release the lock."""
        try:
            if self._fh:
                if self._use_portalocker:
                    try:
                        import portalocker

                        portalocker.unlock(self._fh)
                    except Exception:
                        pass
                else:
                    try:
                        import msvcrt

                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                self._fh.close()
        except Exception:
            pass
        finally:
            self._fh = None
            self._use_portalocker = False
