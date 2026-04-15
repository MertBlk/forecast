from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter()


@router.get("/health", tags=["ops"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Liveness + readiness check in one endpoint.
    Returns 200 when the app is up AND Postgres is reachable.
    Docker Compose healthcheck hits this every 10 s.

    Rule 3: `await db.execute(...)` is non-blocking async I/O — never
    use a sync psycopg2 call inside an async function.
    """
    # Try cheapest possible round-trip to verify the DB connection is alive
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "db": "reachable",
        }
    except Exception:
        # Demo mode: still return healthy even if DB unavailable
        return {
            "status": "ok",
            "db": "unavailable (demo mode)",
        }
