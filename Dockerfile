# ── Stage 1: dependency builder ──────────────────────────────────────
# Install wheels into an isolated prefix so the final image copies
# only compiled packages — no pip, no build tools, no cache.
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps needed to compile psycopg2 (C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only the dependency manifest — Docker cache skips pip install
# on subsequent builds if pyproject.toml hasn't changed.
COPY pyproject.toml .

# Install into /install so we can COPY just that directory to the runtime stage
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --prefix=/install .


# ── Stage 2: runtime ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Runtime needs libpq (shared library) but not gcc
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — containers should never run as root in production
RUN adduser --disabled-password --gecos "" --uid 1001 appuser

WORKDIR /app

# Copy only the installed packages from the builder — no pip or build tools
COPY --from=builder /install /usr/local

# Copy application source (no tests, no .env, no infra/)
COPY app/     ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Switch to non-root before the final CMD
USER appuser

# Expose the port uvicorn will listen on
EXPOSE 8000

# PYTHONDONTWRITEBYTECODE: skip .pyc files (not useful in containers)
# PYTHONUNBUFFERED:        force stdout/stderr to flush immediately (log streaming)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Healthcheck built into the image — Docker Compose can also override this
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Run Alembic migrations then start the API server.
# Migrations are idempotent — running them on every startup is safe
# and guarantees the schema is always up-to-date.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
