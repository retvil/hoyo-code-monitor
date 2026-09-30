"""Jinja2 templates singleton (shared across web UI modules)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.templating import Jinja2Templates


def _templates_dir() -> str:
    """Resolve templates directory (frozen-aware for PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and base:
        return str(Path(base) / "templates")
    return str(Path(__file__).resolve().parent.parent / "templates")


templates = Jinja2Templates(directory=_templates_dir())
