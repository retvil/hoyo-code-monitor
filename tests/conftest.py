"""Shared pytest fixtures for HoYo Code Monitor tests."""

import gc
import os
import tempfile
import time

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
    if os.path.exists(db_path):
        for _ in range(10):
            try:
                os.unlink(db_path)
                break
            except PermissionError:
                time.sleep(0.25)
        else:
            os.unlink(db_path)


@pytest.fixture
def storage(temp_db: str) -> Storage:
    """Create a Storage instance with temporary database."""
    return Storage(temp_db)


@pytest.fixture(autouse=True)
def _csrf_test_mode(monkeypatch):
    """Disable CSRF enforcement during tests to preserve existing coverage."""
    monkeypatch.setenv("HCM_TESTING", "1")
