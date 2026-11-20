# src/web_ui.py — kept for backward compatibility (cli.py imports from here).
# The implementation now lives in src.web:
#   - src.web.app        -> app object, lifespan, middlewares, router mounts
#   - src.web.csrf       -> CSRF token/seed/verify helpers
#   - src.web.routers.*  -> route handlers grouped by domain
from src.web.app import _get_scheduler, _set_scheduler, app, lifespan, main, scheduler

__all__ = ["_get_scheduler", "_set_scheduler", "app", "lifespan", "main", "scheduler"]
