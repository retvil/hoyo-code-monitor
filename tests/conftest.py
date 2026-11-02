"""Shared pytest fixtures for HoYo Code Monitor tests."""

import gc
import tempfile
import time
from pathlib import Path

import pytest

from src.storage import Storage


@pytest.fixture
def temp_db() -> str:
    """Create a temporary database file for testing.

    Includes gc.collect() + retry to handle Windows file-locking races
    when sqlite3 connections are closed asynchronously.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    gc.collect()
    if Path(db_path).exists():
        for _ in range(10):
            try:
                Path(db_path).unlink()
                break
            except PermissionError:
                time.sleep(0.25)
        else:
            Path(db_path).unlink()


@pytest.fixture
def storage(temp_db: str) -> Storage:
    """Create a Storage instance with temporary database."""
    return Storage(temp_db)


@pytest.fixture(autouse=True)
def _csrf_test_mode(monkeypatch):
    """Disable CSRF enforcement during tests to preserve existing coverage."""
    monkeypatch.setenv("HCM_TESTING", "1")
