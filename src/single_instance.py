"""Single-instance guard via file lock.

Prevents two schedulers/trays from running at once.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SingleInstance:
    """File-lock guard. Hold the object while the app runs."""

    def __init__(self, lock_path: str | Path = "data/app.lock") -> None:
        self.lock_path = Path(lock_path)
        self._fh: Any | None = None

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if this is the only instance."""
        try:
            import portalocker
        except ImportError:
            logger.warning("portalocker not installed, single-instance guard disabled")
            return True
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.lock_path, "w", encoding="utf-8")
            portalocker.lock(self._fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
            self._fh.write(str(__import__("os").getpid()))
            self._fh.flush()
            return True
        except Exception:
            try:
                if self._fh:
                    self._fh.close()
            except Exception:
                pass
            self._fh = None
            return False

    def release(self) -> None:
        """Release the lock."""
        try:
            if self._fh:
                try:
                    import portalocker

                    portalocker.unlock(self._fh)
                except Exception:
                    pass
                self._fh.close()
        except Exception:
            pass
        finally:
            self._fh = None
