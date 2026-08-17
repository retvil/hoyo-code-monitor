# Genshin Code Monitor

A local Python application that monitors Genshin Impact code sources (websites, forums), automatically redeems valid codes via Hoyolab API using user-provided cookies, and logs redemption statistics.

## Features

- **Multi-source code scraping**: Monitors Genshin Impact Wiki, Reddit, and other forums for new codes
- **Automatic redemption**: Redeems codes via official Hoyolab API using user-provided cookies
- **Statistics tracking**: Logs which codes were redeemed, when, and what rewards they gave
- **CLI interface**: Full command-line interface for managing sources, config, and monitoring
- **Local-only**: All data stays on your machine; no external telemetry
- **Graceful shutdown**: Handles SIGINT/SIGTERM for clean shutdown
- **Rotating logs**: Size-based log rotation with sensitive data filtering

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd GIPromoCode

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

## Configuration

On first run, a default `config.toml` is created in the project directory:

```toml
interval = 1800          # Check interval in seconds (default: 30 minutes)
redemption_enabled = false  # Auto-redeem codes (requires cookies)
db_path = "data/monitor.db"
log_level = "INFO"
log_file = "logs/app.log"
max_log_size = 10485760  # 10 MB
backup_count = 5
```

### Enabling Auto-Redemption

1. Set `redemption_enabled = true` in config.toml
2. Provide your Hoyolab cookies (ltuid, ltoken, cookie_token_v2) via environment variables or config
3. The application will automatically attempt to redeem new codes

## Usage

```bash
# Start the monitor (daemon mode)
genshin-code-monitor start

# Stop the monitor
genshin-code-monitor stop

# Check status
genshin-code-monitor status

# Show redemption statistics
genshin-code-monitor stats

# Run a single check cycle immediately
genshin-code-monitor run-once

# Manage sources
genshin-code-monitor sources list
genshin-code-monitor sources add "wiki" "https://genshin-impact.fandom.com/wiki/Promotional_Code" --selector-type css --selector "table.wikitable"
genshin-code-monitor sources remove "wiki"
genshin-code-monitor sources enable "wiki"
genshin-code-monitor sources disable "wiki"

# Manage configuration
genshin-code-monitor config show
genshin-code-monitor config set interval 3600
genshin-code-monitor config set redemption_enabled true
```

## Project Structure

```
src/
├── cli.py              # CLI entry point
├── config.py           # Configuration management (TOML)
├── storage.py          # SQLite storage layer
├── scheduler.py        # APScheduler-based job scheduler
├── logging_setup.py    # Logging with rotation & sensitive data filtering
├── signals.py          # Graceful shutdown signal handling
├── scrapers/
│   ├── base.py         # Abstract base scraper
│   └── wiki.py         # Genshin Impact Wiki scraper
├── redeemer.py         # Hoyolab API redemption client
tests/                  # Unit tests (180+ tests)
```

## Requirements

- Python 3.11+
- Dependencies listed in `requirements.txt`:
  - aiohttp
  - beautifulsoup4
  - click
  - apscheduler
  - toml
  - colorlog (optional, for colored console output)

## Security Notes

- **Cookies are never stored in plaintext** - they are encrypted or prompted each session
- **No external telemetry** - all data stays local
- **Auto-redeem is opt-in** - disabled by default
- **Sensitive data filtering** - logs automatically mask cookies, tokens, and passwords

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_cli.py -v
pytest tests/test_storage.py -v
pytest tests/test_scraper_wiki.py -v
```

## License

MIT License - see LICENSE file for details.

## Disclaimer

This tool is for personal use only. Use at your own risk. The authors are not responsible for any account issues resulting from use of this tool. Always follow Genshin Impact's Terms of Service.