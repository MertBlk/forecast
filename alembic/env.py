"""
Alembic runs synchronously (it has no async mode by default).
We use the sync URL (psycopg2) here — the async URL (asyncpg) is
only used by the running FastAPI application.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import Base so Alembic can detect our ORM models for autogenerate
from app.db.models import Base          # noqa: F401 — registers models on Base.metadata
from app.config import settings

# Alembic Config object — gives access to values in alembic.ini
config = context.config

# Wire up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that autogenerate inspects to diff against the DB
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    'Offline' mode: generate SQL script without connecting to the DB.
    Useful for DBAs who want to review SQL before applying it.
    """
    context.configure(
        url=settings.database_url_sync,   # inject URL from settings, not alembic.ini
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    'Online' mode: connect to DB and apply migrations directly.
    This is what `alembic upgrade head` uses.
    """
    # Override the blank sqlalchemy.url from alembic.ini with our real URL
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.database_url_sync

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,    # don't pool connections during migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Include JSONB and other PG-specific types in autogenerate
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
