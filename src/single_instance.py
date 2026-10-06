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


class SingleInstance:
    """File-lock guard. Hold the object while the app runs."""

    def __init__(self, lock_path: str | Path | None = None) -> None:
        """Initialize the guard.

        Args:
            lock_path: Lock file path (defaults to app data dir).
        """
        if lock_path is None:
            from src.paths import app_data_dir

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

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if this is the only instance."""
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.lock_path, "w", encoding="utf-8")
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
                logger.warning("Single-instance lock unavailable on this platform")
                self._close_quietly()
                return False
        except Exception:
            self._close_quietly()
            return False
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
