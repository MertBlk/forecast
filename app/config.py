from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All config is read from environment variables (or .env file).
    pydantic-settings validates types automatically — if POSTGRES_PORT is
    missing or not an int, the app crashes at startup, not mid-request.
    Rule 7: zero hardcoded secrets anywhere in source code.
    """

    # ── PostgreSQL ──────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "forecast"
    postgres_user: str = "forecast_user"
    postgres_password: str  # no default → required in production

    # ── Redis ───────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── ClickHouse (Phase 3 — kept here so config is centralised) ───
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "billing"
    clickhouse_user: str = "default"
    clickhouse_password: str = ""

    # ── App behaviour ───────────────────────────────────────────────
    app_env: str = "development"
    cache_ttl_seconds: int = 3600
    forecast_max_horizon: int = 12

    # ── Derived property — build the async SQLAlchemy URL ───────────
    @property
    def database_url(self) -> str:
        # asyncpg:// instead of postgresql:// tells SQLAlchemy to use
        # the async driver (asyncpg) rather than the sync psycopg2 one.
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        # Alembic runs synchronously, so it needs the plain psycopg2 URL.
        # We swap the driver prefix; everything else stays identical.
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",          # load from .env when present (dev only)
        env_file_encoding="utf-8",
        case_sensitive=False,     # POSTGRES_HOST == postgres_host
    )


# Single shared instance — import this everywhere instead of Settings()
settings = Settings()
