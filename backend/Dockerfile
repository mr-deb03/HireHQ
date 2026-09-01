# syntax=docker/dockerfile:1.7
# ------------------------------------------------------------------ builder
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Build-only toolchain, kept out of the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# Dependencies resolve into their own layer, so application edits do not
# invalidate the (slow) dependency install.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install \
        "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9" \
        "pydantic-settings>=2.6" "email-validator>=2.2" \
        "sqlalchemy[asyncio]>=2.0.36" "alembic>=1.14" "asyncpg>=0.30" \
        "aiosqlite>=0.20" "greenlet>=3.1" "redis>=5.2" "arq>=0.26" \
        "bcrypt>=4.2" "pyjwt>=2.10" "python-multipart>=0.0.12" \
        "httpx>=0.27" "aioboto3>=13.2" "pypdf>=5.1" "python-docx>=1.1.2" \
        "jinja2>=3.1.4" "aiosmtplib>=3.0" "structlog>=24.4" "anthropic>=0.40"

# ------------------------------------------------------------------ runtime
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 hirehq

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=hirehq:hirehq . .

# Storage is a mount point in production (S3 is the real backend); this exists so the
# local-storage fallback has somewhere writable if it is ever used.
RUN mkdir -p /app/storage && chown -R hirehq:hirehq /app/storage

# Never run the application as root.
USER hirehq

# Managed hosts (Railway, Render, Fly, Cloud Run) assign a port at runtime and inject it
# as $PORT. Defaulting to 8000 keeps docker-compose and local runs unchanged.
# One worker by default. Each one loads the full application (SQLAlchemy, the provider
# SDKs, the parsers), so several will exhaust a small instance's memory during startup -
# which a host reports as an opaque "deploy timed out". A single worker handles a lot of
# concurrent I/O because everything here is async; raise this deliberately once you know
# the instance has the memory for it.
ENV PORT=8000 \
    WEB_CONCURRENCY=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/health/live" || exit 1

# `exec` so uvicorn replaces the shell and receives SIGTERM directly - otherwise the
# platform's stop signal never reaches it and every deploy ends in a hard kill.
#
# --proxy-headers so client IPs and scheme are read from the reverse proxy rather than
# the proxy's own address, which matters for rate limiting and audit logs.
#
# One worker means one process, with no --workers flag and so no supervisor at all. That
# is deliberate beyond saving memory: uvicorn's multi-worker supervisor *restarts* a
# child that dies, so a worker crashing on import - a bad DATABASE_URL, a missing
# JWT_SECRET - becomes an endless fork/die loop that logs only "Child process [N] died"
# and buries the traceback that explains it. The platform sees a port that never opens
# and reports "Timed Out", which says nothing about the actual fault. Single process:
# the container exits with the real error on the last line, where it can be read.
CMD echo "hirehq: uvicorn on port ${PORT:-8000}, workers=${WEB_CONCURRENCY:-1}" && \
    if [ "${WEB_CONCURRENCY:-1}" -gt 1 ] 2>/dev/null; then \
        exec uvicorn app.main:app \
            --host 0.0.0.0 --port "${PORT:-8000}" \
            --proxy-headers --forwarded-allow-ips '*' \
            --workers "${WEB_CONCURRENCY}"; \
    else \
        exec uvicorn app.main:app \
            --host 0.0.0.0 --port "${PORT:-8000}" \
            --proxy-headers --forwarded-allow-ips '*'; \
    fi
