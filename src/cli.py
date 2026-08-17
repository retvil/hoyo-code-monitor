"""CLI for genshin-code-monitor."""

import asyncio
import json
import sys

import click

from src.config import ConfigManager
from src.scheduler import create_scheduler_from_storage
from src.sources import SourceFetcher
from src.storage import Storage


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
        if key in ('uid', 'cookies') and isinstance(value, str) and value:
            masked[key] = '*' * len(value) if len(value) <= 4 else value[:4] + '*' * (len(value) - 4)
        else:
            masked[key] = value
    click.echo(json.dumps(masked, indent=2))


@config.command()
@click.argument('key')
@click.argument('value')
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

    # Store cookies per account
    storage.set_config(f"account_cookies_{name}", json.dumps(cookies_dict))
    click.echo(f"Set cookies for account '{name}'.")
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

    cookies_json = storage.get_config(f"account_cookies_{name}")
    if not cookies_json:
        click.echo("No cookies set for this account.")
        sys.exit(0)

    cookies = json.loads(cookies_json)
    masked = {}
    for key, value in cookies.items():
        if isinstance(value, str) and value:
            masked[key] = '*' * len(value) if len(value) <= 4 else value[:4] + '*' * (len(value) - 4)
        else:
            masked[key] = value
    click.echo(json.dumps(masked, indent=2))
    sys.exit(0)


@cli.group()
def sources():
    """Manage data sources."""
    pass


@sources.command()
def list():
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


@sources.command()
@click.argument("name")
@click.argument("url")
@click.option("--selector-type", "-t", default="css", help="Type of selector (css, json, xpath).")
@click.option("--selector", "-s", help="Selector value.")
def add(name, url, selector_type, selector):
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


@sources.command()
@click.argument("name")
def remove(name):
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
    by_source = stats.get('by_source', {})
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
            results = await fetcher.fetch_all_enabled()
            return results

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


if __name__ == "__main__":
    cli()
