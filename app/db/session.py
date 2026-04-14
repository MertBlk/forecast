from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# create_async_engine is the async counterpart to create_engine.
# pool_pre_ping=True sends a cheap SELECT 1 before reusing a connection
# from the pool — prevents "connection closed" errors after Postgres restarts.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=(settings.app_env == "development"),  # log SQL only in dev
)

# async_sessionmaker produces AsyncSession objects.
# expire_on_commit=False means ORM objects stay accessible after commit
# without triggering a lazy-load (which would fail in async context).
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""
    pass


# ── Dependency for FastAPI route injection ──────────────────────────
# Rule 4: always open sessions with `async with AsyncSessionLocal() as session`
# This generator does exactly that and is used via FastAPI's Depends().
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session          # session is open while the request is handled
        # AsyncSessionLocal.__aexit__ commits or rolls back automatically
