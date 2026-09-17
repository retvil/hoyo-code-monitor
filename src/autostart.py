"""Windows autostart support for HoYo Code Monitor.

Registers the app in HKCU\\...\\Run so it starts on user login.
Local-only, no admin rights required.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "HoYoCodeMonitor"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _tray_command() -> str:
    """Build the command that starts the app in tray mode."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}" tray'
    # Prefer pythonw to avoid console window
    pythonw = exe.with_name("pythonw.exe")
    python = str(pythonw if pythonw.exists() else exe)
    cli_py = Path(__file__).resolve().parent / "cli.py"
    return f'"{python}" "{cli_py}" tray'


def _open_key(write: bool = False):
    import winreg

    access = winreg.KEY_SET_VALUE if write else winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def is_enabled() -> bool:
    """Check if autostart is enabled."""
    try:
        import winreg

        with _open_key() as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError as e:
        logger.warning("Autostart check failed: %s", e)
        return False


def enable() -> None:
    """Enable autostart on login."""
    import winreg

    with _open_key(write=True) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _tray_command())
    logger.info("Autostart enabled: %s", _tray_command())


def disable() -> None:
    """Disable autostart on login."""
    import winreg

    try:
        with _open_key(write=True) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass
    logger.info("Autostart disabled")
