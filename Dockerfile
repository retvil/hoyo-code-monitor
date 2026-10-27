# Dockerfile for HoYo Code Monitor
# Multi-stage build for smaller final image

# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install system runtime libs. The app uses Playwright's OWN chromium
# (downloaded into the user's ms-playwright cache), not the distro's
# `chromium`/`chromium-driver`, so those are intentionally NOT installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /app/logs /app/config && \
    chown -R appuser:appuser /app

# Copy application code (before USER so chown works, then ownership is set)
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser config.toml ./
COPY --chown=appuser:appuser pyproject.toml ./

# Install the system shared libraries Playwright's chromium needs at launch
# (libnss3, libatk, libgbm, ...). This must run as root; the slim base image
# does not ship these by default.
RUN python -m playwright install-deps chromium

# Switch to non-root user
USER appuser

# Pre-install Playwright's chromium so runtime logins don't need a network
# download. Runs as appuser so the browser lands in /home/appuser/.cache/
# ms-playwright, exactly where src.cookies_login.browsers_dir() looks.
RUN python -m playwright install chromium

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_PATH=/app/config/config.toml \
    DB_PATH=/app/data/monitor.db \
    LOG_FILE=/app/logs/app.log

# Expose port for health check (if web UI added later)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sqlite3; conn = sqlite3.connect('/app/data/monitor.db'); conn.execute('SELECT 1'); conn.close()" || exit 1

# Default command
CMD ["hoyo-code-monitor", "start"]