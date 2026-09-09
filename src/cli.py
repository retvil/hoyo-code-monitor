"""CLI for genshin-code-monitor."""

import asyncio
import json
import sys

import click

from src.autostart import disable as autostart_disable
from src.autostart import enable as autostart_enable
from src.autostart import is_enabled as autostart_is_enabled
from src.config import ConfigManager
from src.constants import MASK_VISIBLE_CHARS
from src.scheduler import create_scheduler_from_storage
from src.single_instance import SingleInstance
from src.sources import SourceFetcher
from src.storage import Storage
from src.system_tray import create_tray_icon

_instance_guard: SingleInstance | None = None


def _ensure_single_instance() -> None:
    """Exit if another instance is already running."""
    global _instance_guard
    _instance_guard = SingleInstance()
    if not _instance_guard.acquire():
        click.echo("Another instance is already running. Exiting.", err=True)
        sys.exit(1)


@click.group()
def cli():
    """Command group for genshin-code-monitor."""
    pass


@cli.group()
def config():
    """Configuration management."""
    pass


@config.command()
def show():
    """Show current configuration."""
    config_manager = ConfigManager()
    config = config_manager.get_all()
    masked = {}
    for key, value in config.items():
        if key in ("uid", "cookies") and isinstance(value, str) and value:
            masked[key] = (
                "*" * len(value) if len(value) <= 4 else value[:4] + "*" * (len(value) - 4)
            )
        else:
            masked[key] = value
    click.echo(json.dumps(masked, indent=2))


@config.command()
@click.argument("key")
@click.argument("value")
def set(key, value):
    """Set a configuration key to a value."""
    config_manager = ConfigManager()
    try:
        config_manager.set(key, value)
        click.echo(f"Set {key} to {value}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.group()
def accounts():
    """Manage Hoyolab accounts."""
    pass


@accounts.command()
def list():
    """List all stored accounts."""
    storage = Storage()
    accounts = storage.list_accounts()
    if not accounts:
        click.echo("No accounts stored.")
        sys.exit(0)

    click.echo(f"{'Name':<20}  {'UID':<15}  {'Region':<12}  {'Game Biz':<15}  {'Lang':<10}")
    click.echo("-" * 80)

    for acc in accounts:
        name = acc.get("name", "")
        uid = acc.get("uid", "")
        region = acc.get("region", "")
        game_biz = acc.get("game_biz", "")
        lang = acc.get("lang", "")
        click.echo(f"{name:<20}  {uid:<15}  {region:<12}  {game_biz:<15}  {lang:<10}")

    sys.exit(0)


@accounts.command()
@click.argument("name")
@click.argument("uid")
@click.argument("region")
@click.option("--game-biz", default="hk4e_global", help="Game business identifier.")
@click.option("--lang", default="en-us", help="Language code.")
@click.option("--s-lang-key", default="en-us", help="Secondary language key.")
def add(name, uid, region, game_biz, lang, s_lang_key):
    """Add a new account <name> <uid> <region>."""
    storage = Storage()
    existing = storage.get_account(name)
    if existing:
        click.echo(f"Error: Account '{name}' already exists.", err=True)
        sys.exit(1)

    try:
        storage.add_account(
            name=name,
            uid=uid,
            region=region,
            game_biz=game_biz,
            lang=lang,
            s_lang_key=s_lang_key,
        )
    except Exception as e:
        click.echo(f"Error adding account: {e}", err=True)
        sys.exit(1)

    click.echo(f"Added account '{name}'.")
    sys.exit(0)


@accounts.command()
@click.argument("name")
def remove(name):
    """Remove an account <name>."""
    storage = Storage()
    try:
        storage.delete_account(name)
    except Exception as e:
        click.echo(f"Error removing account: {e}", err=True)
        sys.exit(1)

    click.echo(f"Removed account '{name}'.")
    sys.exit(0)


@accounts.command()
@click.argument("name")
@click.option("--uid", help="New UID.")
@click.option("--region", help="New region.")
@click.option("--game-biz", help="New game business identifier.")
@click.option("--lang", help="New language code.")
@click.option("--s-lang-key", help="New secondary language key.")
def update(name, uid, region, game_biz, lang, s_lang_key):
    """Update an account <name>."""
    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        click.echo(f"Error: Account '{name}' not found.", err=True)
        sys.exit(1)

    try:
        storage.update_account(
            name=name,
            uid=uid,
            region=region,
            game_biz=game_biz,
            lang=lang,
            s_lang_key=s_lang_key,
        )
    except Exception as e:
        click.echo(f"Error updating account: {e}", err=True)
        sys.exit(1)

    click.echo(f"Updated account '{name}'.")
    sys.exit(0)


@accounts.command()
@click.argument("name")
@click.option("--cookies", help="JSON string of cookies (ltuid, ltoken, cookie_token_v2).")
def set_cookies(name, cookies):
    """Set cookies for an account <name>."""
    import json

    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        click.echo(f"Error: Account '{name}' not found.", err=True)
        sys.exit(1)

    if not cookies:
        click.echo("Error: --cookies is required.", err=True)
        sys.exit(1)

    try:
        cookies_dict = json.loads(cookies)
    except json.JSONDecodeError as e:
        click.echo(f"Error parsing cookies JSON: {e}", err=True)
        sys.exit(1)

    # Store cookies per account (encrypted via Fernet)
    storage.store_account_cookies(name, cookies_dict)
    click.echo(f"Set cookies for account '{name}'.")
    sys.exit(0)


@accounts.command()
@click.argument("name")
@click.option("--timeout", type=int, default=300, help="Seconds to wait for login.")
def login(name, timeout):
    """Auto-capture cookies: opens browser, you log in to HoYoLAB, cookies are saved encrypted."""
    from src.cookies_login import capture_cookies_sync

    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        click.echo(f"Error: Account '{name}' not found. Create it first: accounts add <name> <uid> <region>", err=True)
        sys.exit(1)

    click.echo("Opening HoYoLAB in browser - log in, cookies will be saved automatically...")
    try:
        cookies = capture_cookies_sync(timeout_seconds=timeout)
    except TimeoutError:
        click.echo("Login timed out, no cookies saved.", err=True)
        sys.exit(1)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    storage.store_account_cookies(name, cookies)
    click.echo(f"Cookies saved for account '{name}' (keys: {', '.join(sorted(cookies))}).")
    sys.exit(0)


@accounts.command()
@click.argument("name")
def show_cookies(name):
    """Show cookies for an account <name> (masked)."""
    import json

    storage = Storage()
    existing = storage.get_account(name)
    if not existing:
        click.echo(f"Error: Account '{name}' not found.", err=True)
        sys.exit(1)

    cookies = storage.load_account_cookies(name)
    if not cookies:
        click.echo("No cookies set for this account.")
        sys.exit(0)

    masked = {}
    for key, value in cookies.items():
        if isinstance(value, str) and value:
            masked[key] = (
                "*" * len(value)
                if len(value) <= MASK_VISIBLE_CHARS
                else value[:MASK_VISIBLE_CHARS] + "*" * (len(value) - MASK_VISIBLE_CHARS)
            )
        else:
            masked[key] = value
    click.echo(json.dumps(masked, indent=2))
    sys.exit(0)


@cli.group()
def sources():
    """Manage data sources."""
    pass


@sources.command(name="list")
def list_sources():
    """List all stored sources."""
    storage = Storage()
    sources = storage.list_sources()
    if not sources:
        click.echo("No sources stored.")
        sys.exit(0)

    # Header
    click.echo(f"{'Name':<20}  {'URL':<50}  {'Selector Type':<15}  {'Selector':<20}  {'Enabled'}")
    click.echo("-" * 110)

    # Rows
    for src in sources:
        name = src.get("name", "")
        url = src.get("url", "")
        sel_type = src.get("selector_type", "")
        selector = src.get("selector", "")
        enabled = "Yes" if src.get("enabled") else "No"
        click.echo(f"{name:<20}  {url:<50}  {sel_type:<15}  {selector:<20}  {enabled}")

    sys.exit(0)


@sources.command(name="add")
@click.argument("name")
@click.argument("url")
@click.option("--selector-type", "-t", default="css", help="Type of selector (css, json, xpath).")
@click.option("--selector", "-s", help="Selector value.")
def add_source(name, url, selector_type, selector):
    """Add a new source <name> <url>."""
    storage = Storage()
    existing = storage.get_source(name)
    if existing:
        click.echo(f"Error: Source '{name}' already exists.", err=True)
        sys.exit(1)

    try:
        storage.add_source(
            name=name,
            url=url,
            selector_type=selector_type,
            selector=selector,
        )
    except Exception as e:
        click.echo(f"Error adding source: {e}", err=True)
        sys.exit(1)

    click.echo(f"Added source '{name}'.")
    sys.exit(0)


@sources.command(name="remove")
@click.argument("name")
def remove_source(name):
    """Remove a source <name>."""
    storage = Storage()
    try:
        storage.remove_source(name)
    except Exception as e:
        click.echo(f"Error removing source: {e}", err=True)
        sys.exit(1)

    click.echo(f"Removed source '{name}'.")
    sys.exit(0)


@sources.command()
@click.argument("name")
def enable(name):
    """Enable a source <name>."""
    storage = Storage()
    try:
        storage.enable_source(name)
    except Exception as e:
        click.echo(f"Error enabling source: {e}", err=True)
        sys.exit(1)

    click.echo(f"Enabled source '{name}'.")
    sys.exit(0)


@sources.command()
@click.argument("name")
def disable(name):
    """Disable a source <name>."""
    storage = Storage()
    try:
        storage.disable_source(name)
    except Exception as e:
        click.echo(f"Error disabling source: {e}", err=True)
        sys.exit(1)

    click.echo(f"Disabled source '{name}'.")
    sys.exit(0)


@cli.command()
def start():
    """Start monitoring."""
    _ensure_single_instance()
    try:
        scheduler = create_scheduler_from_storage()
        if scheduler.start():
            click.echo("Scheduler started.")
        else:
            click.echo("Scheduler already running.")
    except Exception as e:
        click.echo(f"Error starting scheduler: {e}", err=True)
        sys.exit(1)


@cli.command()
def stop():
    """Stop monitoring."""
    try:
        scheduler = create_scheduler_from_storage()
        if scheduler.stop():
            click.echo("Scheduler stopped.")
        else:
            click.echo("Scheduler not running or timeout.")
    except Exception as e:
        click.echo(f"Error stopping scheduler: {e}", err=True)
        sys.exit(1)


@cli.command()
def health():
    """Check system health."""
    storage = Storage()
    try:
        # Check database
        with storage._connection() as conn:
            conn.execute("SELECT 1").fetchone()

        # Check sources
        sources = storage.list_sources(enabled_only=True)

        # Check config
        config_manager = ConfigManager()
        config = config_manager.get_all()

        click.echo("Health check: OK")
        click.echo("  Database: OK")
        click.echo(f"  Active sources: {len(sources)}")
        click.echo(f"  Redemption enabled: {config.get('redemption_enabled', False)}")
        click.echo(f"  Scheduler interval: {config.get('poll_interval_seconds', 900)}s")

    except Exception as e:
        click.echo(f"Health check: FAILED - {e}", err=True)
        sys.exit(1)


@cli.group()
def notify():
    """Telegram notification settings."""
    pass


@notify.command("config")
@click.option("--bot-token", default=None, help="Telegram bot token from @BotFather.")
@click.option("--chat-id", default=None, help="Telegram chat id (from @userinfobot).")
def notify_config(bot_token, chat_id):
    """Show or set Telegram notification settings."""
    storage = Storage()
    if bot_token is not None:
        storage.set_config("telegram_bot_token", bot_token)
    if chat_id is not None:
        storage.set_config("telegram_chat_id", chat_id)
    token_set = bool(storage.get_config("telegram_bot_token", ""))
    chat = storage.get_config("telegram_chat_id", "") or "-"
    click.echo(f"Telegram notifications: {'configured' if token_set and chat != '-' else 'NOT configured'}")
    click.echo(f"  chat_id: {chat}")


@notify.command("test")
def notify_test():
    """Send a test message to Telegram."""
    import asyncio

    from src.notify import send_telegram

    storage = Storage()
    token = storage.get_config("telegram_bot_token", "") or ""
    chat_id = storage.get_config("telegram_chat_id", "") or ""
    if not token or not chat_id:
        click.echo("Not configured. Run: notify config --bot-token <t> --chat-id <id>", err=True)
        sys.exit(1)
    ok = asyncio.run(send_telegram(token, chat_id, "Genshin Code Monitor: test message ✅"))
    click.echo("Sent." if ok else "Failed to send.", err=not ok)
    if not ok:
        sys.exit(1)


@cli.command()
def status():
    """Show current status."""
    try:
        scheduler = create_scheduler_from_storage()
        if scheduler.is_running():
            next_run = scheduler.next_run_time()
            click.echo(f"Scheduler is running. Next run: {next_run}")
        else:
            click.echo("Scheduler is stopped.")
    except Exception as e:
        click.echo(f"Error getting status: {e}", err=True)
        sys.exit(1)


@cli.command()
def stats():
    """Show redemption statistics."""
    storage = Storage()
    stats = storage.get_stats()
    click.echo(f"Total codes: {stats.get('total_codes', 0)}")
    click.echo(f"Successful: {stats.get('successful', 0)}")
    click.echo(f"Failed: {stats.get('failed', 0)}")
    by_source = stats.get("by_source", {})
    if by_source:
        click.echo("By source:")
        for source, count in by_source.items():
            click.echo(f"  {source}: {count}")


@cli.command()
def run_once():
    """Run a single check cycle immediately."""

    config_manager = ConfigManager()
    config = config_manager.get_all()
    db_path = config.get("db_path", "data/monitor.db")

    storage = Storage(db_path)

    async def run_cycle():
        async with SourceFetcher(storage) as fetcher:
            return await fetcher.fetch_all_enabled()

    click.echo("Running single check cycle...")

    try:
        results = asyncio.run(run_cycle())
        total_codes = sum(len(codes) for codes in results.values())
        click.echo(f"Found {total_codes} code(s) from {len(results)} source(s):")
        for name, codes in results.items():
            click.echo(f"  {name}: {len(codes)} code(s)")
            for code in codes[:5]:
                click.echo(f"    {code}")
            if len(codes) > 5:
                click.echo(f"    ... and {len(codes) - 5} more")

        # Store new codes
        new_codes = 0
        for source_name, codes in results.items():
            for code in codes:
                code = code.strip()
                if not code:
                    continue
                try:
                    storage.add_code(code, source_name)
                    new_codes += 1
                except Exception:
                    pass  # Duplicate or other error

        click.echo(f"Stored {new_codes} new code(s).")

        # Check if redemption is enabled
        redemption_enabled = config.get("redemption_enabled", False)

        if redemption_enabled and new_codes > 0:
            click.echo("Redemption enabled but not implemented in run-once (use scheduler).")

        click.echo("Single check cycle completed.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.group()
def autostart():
    """Manage Windows autostart on login."""
    pass


@autostart.command("enable")
def autostart_enable_cli():
    """Enable autostart on Windows login."""
    try:
        autostart_enable()
    except Exception as e:
        click.echo(f"Error enabling autostart: {e}", err=True)
        sys.exit(1)
    click.echo("Autostart enabled (starts in tray on login).")


@autostart.command("disable")
def autostart_disable_cli():
    """Disable autostart on Windows login."""
    try:
        autostart_disable()
    except Exception as e:
        click.echo(f"Error disabling autostart: {e}", err=True)
        sys.exit(1)
    click.echo("Autostart disabled.")


@autostart.command("status")
def autostart_status_cli():
    """Show autostart status."""
    try:
        enabled = autostart_is_enabled()
    except Exception as e:
        click.echo(f"Error checking autostart: {e}", err=True)
        sys.exit(1)
    click.echo(f"Autostart: {'enabled' if enabled else 'disabled'}.")


@cli.command()
def tray():
    """Run in system tray with live menu and embedded settings server."""
    import threading
    import time
    import webbrowser

    from src.constants import WEB_HOST, WEB_PORT

    _ensure_single_instance()
    scheduler = create_scheduler_from_storage()
    config_manager = ConfigManager()
    web_url = f"http://{WEB_HOST}:{WEB_PORT}"

    # Embedded settings web server (local only)
    def _run_web_server() -> None:
        try:
            import uvicorn

            from src.web_ui import app

            uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="warning")
        except ImportError:
            logger_web_missing = __import__("logging").getLogger(__name__)
            logger_web_missing.warning("Web UI not available (fastapi/uvicorn not installed)")
        except OSError as e:
            print(f"Web server already running or port busy: {e}")

    web_thread = threading.Thread(target=_run_web_server, daemon=True, name="WebUI")
    web_thread.start()

    def on_start() -> None:
        if scheduler.start():
            click.echo("Monitoring enabled.")
        else:
            click.echo("Monitoring already running.")

    def on_stop() -> None:
        if scheduler.stop():
            click.echo("Monitoring disabled.")
        else:
            click.echo("Monitoring not running.")

    def on_show() -> None:
        click.echo(f"Opening settings: {web_url}")
        webbrowser.open(web_url)

    def on_quit() -> None:
        click.echo("Shutting down...")
        if scheduler.is_running():
            scheduler.stop()
        import os

        os._exit(0)

    def on_run_once() -> None:
        result = scheduler.run_once()
        click.echo(
            f"Check done: {result['codes_found']} found, {result['codes_redeemed']} redeemed."
        )

    def on_set_interval(seconds: int) -> None:
        config_manager.set("poll_interval_seconds", seconds)
        minutes = seconds // 60
        click.echo(f"Scan interval set to every {minutes} minutes.")

    def get_interval() -> int:
        try:
            return int(config_manager.get("poll_interval_seconds", 900))
        except (TypeError, ValueError):
            return 900

    tray_icon = create_tray_icon(
        on_start,
        on_stop,
        on_show,
        on_quit,
        on_run_once,
        on_set_interval,
        get_interval,
        scheduler.is_running,
    )

    if scheduler.start():
        click.echo("Auto-started monitoring.")

    click.echo("Genshin Code Monitor running in system tray.")
    click.echo(f"Settings: {web_url}")
    click.echo("Right-click the tray icon for menu. Press Ctrl+C to exit.")

    tray_icon.run()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nShutting down...")
        if scheduler.is_running():
            scheduler.stop()


if __name__ == "__main__":
    cli()
