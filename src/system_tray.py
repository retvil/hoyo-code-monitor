"""System tray integration for Genshin Code Monitor.

Provides a system tray icon with menu for controlling the application.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    import pystray
    from PIL import Image, ImageDraw

    PYSTRAY_AVAILABLE = True
except Exception as e:  # headless, missing display
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    PYSTRAY_AVAILABLE = False
    _pystray_error = e

logger = logging.getLogger(__name__)


class SystemTray:
    """System tray icon with menu for Genshin Code Monitor."""

    INTERVALS: tuple[tuple[str, int], ...] = (
        ("Every 5 minutes", 300),
        ("Every 15 minutes", 900),
        ("Every 30 minutes", 1800),
        ("Every 60 minutes", 3600),
    )

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        on_run_once: Callable[[], None],
        on_set_interval: Callable[[int], None] | None = None,
        get_interval: Callable[[], int] | None = None,
        is_monitoring: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize the system tray.

        Args:
            on_start: Callback to start the scheduler.
            on_stop: Callback to stop the scheduler.
            on_show: Callback to show the web UI.
            on_quit: Callback to quit the application.
            on_run_once: Callback to run a single check cycle.
            on_set_interval: Callback to set scan interval in seconds.
            get_interval: Callback returning current scan interval in seconds.
            is_monitoring: Callback returning True if monitoring is running.
        """
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_show = on_show
        self.on_quit = on_quit
        self.on_run_once = on_run_once
        self.on_set_interval = on_set_interval
        self.get_interval = get_interval
        self.is_monitoring = is_monitoring

        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def _create_icon_image(self) -> Image.Image:
        """Create a simple icon image for the system tray."""
        if not PYSTRAY_AVAILABLE or Image is None:
            raise RuntimeError("PIL not available")  # noqa: TRY003 -- validation message needs interpolation, custom exception already specific
        # Create a 64x64 image with a simple design
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw a simple Genshin-like symbol (a star-like shape)
        # Background circle
        draw.ellipse([4, 4, 60, 60], fill=(41, 128, 185, 255), outline=(52, 152, 219, 255), width=2)

        # Draw a diamond shape in the center
        diamond_points = [
            (32, 16),  # top
            (48, 32),  # right
            (32, 48),  # bottom
            (16, 32),  # left
        ]
        draw.polygon(diamond_points, fill=(255, 255, 255, 255))

        return img

    def _monitoring(self) -> bool:
        """Current monitoring state (callback or internal flag)."""
        if self.is_monitoring is not None:
            try:
                return bool(self.is_monitoring())
            except Exception:
                pass
        return self._running

    def _current_interval(self) -> int | None:
        """Current scan interval in seconds, if available."""
        if self.get_interval is None:
            return None
        try:
            return int(self.get_interval())
        except Exception:
            return None

    def _create_menu(self) -> pystray.Menu:
        """Create the system tray menu."""
        items: list = [
            pystray.MenuItem("Open settings", self._on_show, default=True),
            pystray.MenuItem("Run check now", self._on_run_once),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Enable monitoring", self._on_start, enabled=lambda item: not self._monitoring()
            ),
            pystray.MenuItem(
                "Disable monitoring", self._on_stop, enabled=lambda item: self._monitoring()
            ),
        ]
        if self.on_set_interval is not None:
            current = self._current_interval()
            sub_items = []
            for label, seconds in self.INTERVALS:

                def _make_action(s: int):
                    def _action(icon: pystray.Icon, item: pystray.MenuItem) -> None:
                        self._on_set_interval(icon, item, s)

                    return _action

                def _make_checked(s: int):
                    def _checked(item: pystray.MenuItem) -> bool:
                        return current == s

                    return _checked

                sub_items.append(
                    pystray.MenuItem(label, _make_action(seconds), checked=_make_checked(seconds))
                )
            items.append(pystray.MenuItem("Scan interval", pystray.Menu(*sub_items)))
        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        ]
        return pystray.Menu(*items)

    def _on_show(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle show dashboard action."""
        logger.info("Show dashboard requested")
        self.on_show()

    def _on_run_once(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle run once action."""
        logger.info("Run once requested")
        self.on_run_once()

    def _on_start(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle start monitoring action."""
        logger.info("Start monitoring requested")
        self.on_start()
        self._running = True
        self._update_menu()

    def _on_stop(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle stop monitoring action."""
        logger.info("Stop monitoring requested")
        self.on_stop()
        self._running = False
        self._update_menu()

    def _on_set_interval(self, icon: pystray.Icon, item: pystray.MenuItem, seconds: int) -> None:
        """Handle scan interval change."""
        logger.info("Set scan interval requested: %ds", seconds)
        if self.on_set_interval is not None:
            self.on_set_interval(seconds)
        self._update_menu()

    def _on_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle quit action."""
        logger.info("Quit requested")
        self.on_quit()
        self.stop()

    def _update_menu(self) -> None:
        """Update the menu to reflect current state."""
        if self._icon:
            self._icon.menu = self._create_menu()

    def run(self) -> None:
        """Run the system tray icon in a separate thread."""
        if not PYSTRAY_AVAILABLE:
            logger.warning("System tray not available: %s", _pystray_error)
            return
        if self._thread and self._thread.is_alive():
            logger.warning("System tray already running")
            return

        try:
            self._icon = pystray.Icon(
                "genshin-code-monitor",
                self._create_icon_image(),
                "Genshin Code Monitor",
                self._create_menu(),
            )
        except Exception as e:
            logger.warning("Failed to create tray icon: %s", e)
            return

        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="SystemTray")
        self._thread.start()
        logger.info("System tray started")

    def stop(self) -> None:
        """Stop the system tray icon."""
        if self._icon:
            self._icon.stop()
            self._icon = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("System tray stopped")

    def set_running(self, running: bool) -> None:
        """Update the running state."""
        self._running = running
        self._update_menu()


def create_tray_icon(
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
    on_show: Callable[[], None],
    on_quit: Callable[[], None],
    on_run_once: Callable[[], None],
    on_set_interval: Callable[[int], None] | None = None,
    get_interval: Callable[[], int] | None = None,
    is_monitoring: Callable[[], bool] | None = None,
) -> SystemTray:
    """Factory function to create a SystemTray instance."""
    return SystemTray(
        on_start,
        on_stop,
        on_show,
        on_quit,
        on_run_once,
        on_set_interval,
        get_interval,
        is_monitoring,
    )
