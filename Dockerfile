# Dockerfile for HoYo Code Monitor
# Multi-stage build for smaller final image

# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install the project itself (so the `hoyo-code-monitor` / `-web` /
# `-scheduler` console scripts from pyproject.toml [project.scripts]
# land on PATH) plus any extra runtime deps not covered by pyproject
# (requirements.txt is a legacy mirror kept for CI's `pip install -r`
# step; installing it here too is harmless and idempotent).
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install .

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install system runtime libs. The app uses Playwright's OWN chromium
# (downloaded into the user's ms-playwright cache), not the distro's
# `chromium`/`chromium-driver`, so those are intentionally NOT installed.
# `playwright install-deps` (line 51) needs apt's C toolchain: libatomic1
# provides the shared libatomic.so.1 that the Playwright node driver links
# against; without it, `python -m playwright install-deps chromium` fails with
# "libatomic.so.1: cannot open shared object file" (exit code 127).
# Note: libatomic-dev is NOT needed (and is not packaged for slim); the
# runtime lib alone is enough for the node binary to resolve the .so.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    libatomic1 \
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

# Health check — probe the live web server's /health endpoint (the
# real, non-vacuous "is the app actually running" signal) instead of
# touching the DB file, which on first boot gets created empty by the
# connection itself and would pass vacuously even before the app
# initializes any schema.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status==200 else 1)" || exit 1

# Default command
CMD ["hoyo-code-monitor", "start"]