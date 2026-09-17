"""Writable app data directory resolution for source and frozen (PyInstaller) modes.

Frozen exe: %LOCALAPPDATA%\\HoYoCodeMonitor (install dir may be read-only,
e.g. Program Files). Source mode: current working directory (repo root) —
behavior unchanged for dev and tests. Override with HCM_DATA_DIR env var.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "HoYoCodeMonitor"


def app_data_dir() -> Path:
    """Return the writable base directory for db/config/logs/key/lock.

    Returns:
        Writable directory path (created on demand).
    """
    env = os.environ.get("HCM_DATA_DIR")
    if env:
        d = Path(env)
    elif getattr(sys, "frozen", False):
        local = os.environ.get("LOCALAPPDATA")
        d = (Path(local) / APP_DIR_NAME) if local else Path(sys.executable).resolve().parent
    else:
        d = Path.cwd()
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_db_path() -> str:
    """Default SQLite database path inside the app data dir."""
    return str(app_data_dir() / "monitor.db")


def default_config_path() -> str:
    """Default config.toml path inside the app data dir."""
    return str(app_data_dir() / "config.toml")


def default_log_path() -> str:
    """Default log file path inside the app data dir."""
    return str(app_data_dir() / "logs" / "app.log")
