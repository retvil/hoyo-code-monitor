"""Unit tests for the single-instance file lock guard."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.single_instance import SingleInstance, _is_process_alive


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    """Isolated lock file path (tmp_path needs no manual cleanup)."""
    return tmp_path / "app.lock"


class TestAcquireRelease:
    """Tests for basic lock acquire/release semantics."""

    def test_first_acquire_succeeds(self, lock_path: Path) -> None:
        """Free lock file is acquirable."""
        guard = SingleInstance(lock_path)
        try:
            assert guard.acquire() is True
            assert lock_path.exists()
        finally:
            guard.release()

    def test_second_acquire_fails(self, lock_path: Path) -> None:
        """Two guards on the same path cannot both hold the lock."""
        first = SingleInstance(lock_path)
        second = SingleInstance(lock_path)
        try:
            assert first.acquire() is True
            assert second.acquire() is False
        finally:
            first.release()
            second.release()

    def test_reacquire_after_release(self, lock_path: Path) -> None:
        """Released lock can be acquired again."""
        guard = SingleInstance(lock_path)
        assert guard.acquire() is True
        guard.release()
        try:
            assert guard.acquire() is True
        finally:
            guard.release()


class TestStaleLockDetection:
    """Tests for stale-lock detection after a crashed instance."""

    def test_dead_pid_in_lock_acquires_successfully(self, lock_path: Path) -> None:
        """Lock file containing a dead PID is treated as stale; acquisition succeeds."""
        # Spawn a short-lived subprocess and capture its PID
        proc = subprocess.Popen(
            [sys.executable, "-c", "import os, time; time.sleep(0.5)"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0,
        )
        dead_pid = proc.pid
        # Immediately kill the subprocess so it becomes a dead PID
        proc.kill()
        proc.wait()

        # Write a lock file with the dead PID
        lock_path.write_text(str(dead_pid))

        # Acquire should succeed (stale lock cleaned) and lock file should be gone
        guard = SingleInstance(lock_path)
        try:
            assert guard.acquire() is True, "Expected acquire to succeed with dead PID"
            # Lock file should have been removed/replaced
            # (it exists with our PID after acquire)
            assert lock_path.exists()
        finally:
            guard.release()

    def test_own_pid_in_lock_acquires_fails(self, lock_path: Path) -> None:
        """Lock file containing the current process's own PID blocks acquisition."""
        # Write our own PID into the lock file
        own_pid = os.getpid()
        lock_path.write_text(str(own_pid))

        guard = SingleInstance(lock_path)
        try:
            # Should fail because the PID is alive (this process)
            assert guard.acquire() is False, "Expected acquire to fail when PID is alive"
        finally:
            guard.release()


class TestIsProcessAlive:
    """Tests for the _is_process_alive helper."""

    def test_alive_process(self) -> None:
        """_is_process_alive returns True for the current process."""
        assert _is_process_alive(os.getpid()) is True

    def test_nonexistent_process(self) -> None:
        """_is_process_alive returns False for a PID that doesn't exist."""
        assert _is_process_alive(999999) is False


class TestMsvcrtFallback:
    """Tests for the stdlib fallback used when portalocker is missing."""

    def test_fallback_enforces_exclusion(
        self, lock_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without portalocker the guard still blocks a second instance."""
        monkeypatch.setitem(sys.modules, "portalocker", None)
        first = SingleInstance(lock_path)
        second = SingleInstance(lock_path)
        try:
            assert first.acquire() is True
            assert second.acquire() is False
        finally:
            first.release()
            second.release()

    def test_fallback_release_reacquire(
        self, lock_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fallback lock released properly allows reacquire."""
        monkeypatch.setitem(sys.modules, "portalocker", None)
        guard = SingleInstance(lock_path)
        assert guard.acquire() is True
        guard.release()
        try:
            assert guard.acquire() is True
        finally:
            guard.release()
