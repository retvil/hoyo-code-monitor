"""Unit tests for the single-instance file lock guard."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.single_instance import SingleInstance


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
