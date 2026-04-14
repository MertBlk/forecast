"""
Celery tasks for data refresh.

refresh_materialized_view — nightly, refreshes project_monthly_cost view
run_clickhouse_etl         — monthly, PG → ClickHouse sync (Phase 3 stub)

Rule 3: Celery tasks are sync by default. To call async code from a task,
        use asyncio.run() — it creates a fresh event loop for the task.
        Never use `async def` on a Celery task directly (Celery doesn't support it
        without extra plugins and it complicates the worker process model).

Rule 8: exceptions are caught, logged, and re-raised so Celery marks the
        task as FAILED (visible in Flower / beat logs) rather than silently passing.
"""
import asyncio
import logging

from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.worker import celery_app

logger = logging.getLogger(__name__)


async def _refresh_view_async() -> None:
    """
    REFRESH MATERIALIZED VIEW CONCURRENTLY does not block reads.
    The CONCURRENTLY keyword requires a unique index on the view —
    we created one in the Alembic migration (ix_pmc_project_month).

    Rule 4: session opened with `async with AsyncSessionLocal()`.
    """
    async with AsyncSessionLocal() as session:
        logger.info("refreshing materialized view project_monthly_cost")
        await session.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY project_monthly_cost")
        )
        await session.commit()
        logger.info("materialized view refresh complete")


@celery_app.task(
    name="app.tasks.refresh.refresh_materialized_view",
    bind=True,           # `self` gives access to retry() and request metadata
    max_retries=3,
    default_retry_delay=300,   # retry after 5 min on failure
)
def refresh_materialized_view(self) -> str:
    """
    Nightly task: refresh the project_monthly_cost materialized view.
    Called by Celery Beat every night at 03:00 UTC.
    """
    try:
        # asyncio.run() creates a new event loop for this sync Celery task
        asyncio.run(_refresh_view_async())
        return "ok"
    except Exception as exc:
        logger.error("refresh_materialized_view failed: %s", exc, exc_info=True)
        # Rule 8: re-raise via Celery retry so the task is marked FAILED
        raise self.retry(exc=exc)


# ETL task lives in app.tasks.etl — see that module.
