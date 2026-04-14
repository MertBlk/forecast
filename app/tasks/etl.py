"""
ETL: PostgreSQL vm_billing_records → ClickHouse billing.vm_billing

Idempotency strategy:
  1. Ask ClickHouse for the max billing_month already synced.
  2. Only fetch PG rows with billing_month > that date.
  3. Insert in BATCH_SIZE chunks (Rule 6).
  4. Invalidate Redis cache for every affected project (Rule 5).

This means re-running the task is safe — it simply finds nothing new
and exits. No duplicate rows, no data loss.

Rule 3: Celery tasks are sync. Async code is run via asyncio.run().
Rule 6: inserts always batched at BATCH_SIZE.
Rule 8: exceptions logged and re-raised so Celery marks task FAILED.
"""
import asyncio
import logging
from datetime import date

from sqlalchemy import select, text

from app.db.adapters.clickhouse import BATCH_SIZE, ClickHouseAdapter
from app.db.models import VmBillingRecord
from app.db.session import AsyncSessionLocal
from app.services.cache import ForecastCache
from app.config import settings
from app.worker import celery_app

logger = logging.getLogger(__name__)


async def _run_etl() -> dict:
    """
    Core async ETL logic.
    Returns a summary dict: {rows_synced, projects_affected, batches}.
    """
    ch = ClickHouseAdapter()

    try:
        # ── 1. Find resume point ─────────────────────────────────────
        max_synced: date | None = await ch.get_max_synced_billing_month()
        logger.info("etl: max billing_month in ClickHouse = %s", max_synced)

        # ── 2. Stream rows from Postgres ─────────────────────────────
        # Rule 4: session opened with `async with AsyncSessionLocal()`
        async with AsyncSessionLocal() as session:
            stmt = select(VmBillingRecord)
            if max_synced:
                # Only fetch records newer than what's already in CH
                stmt = stmt.where(VmBillingRecord.billing_month > max_synced)
            stmt = stmt.order_by(VmBillingRecord.billing_month.asc())

            result = await session.execute(stmt)
            records = result.scalars().all()

        if not records:
            logger.info("etl: no new records to sync")
            return {"rows_synced": 0, "projects_affected": 0, "batches": 0}

        # ── 3. Convert ORM objects → plain dicts ─────────────────────
        rows = [
            {
                "billing_month": r.billing_month,
                "project_id":    r.project_id,
                "customer_id":   r.customer_id,
                "vm_id":         r.vm_id,
                "vm_type":       r.vm_type,
                "region":        r.region,
                "hours_used":    r.hours_used,
                "unit_price":    r.unit_price,
                "cost_usd":      r.cost_usd,
            }
            for r in records
        ]

        # ── 4. Batch-insert into ClickHouse (Rule 6) ─────────────────
        total_inserted = await ch.insert_billing_rows(rows)
        batches = (total_inserted + BATCH_SIZE - 1) // BATCH_SIZE

        # ── 5. Invalidate cache for every affected project (Rule 5) ──
        affected_projects = {r["project_id"] for r in rows}
        cache = ForecastCache(settings.redis_url)
        try:
            for project_id in affected_projects:
                deleted = await cache.invalidate_project(project_id)
                logger.info(
                    "etl: invalidated %d cache keys for project %s",
                    deleted,
                    project_id,
                )
        finally:
            await cache.close()

        logger.info(
            "etl complete: %d rows, %d projects, %d batches",
            total_inserted,
            len(affected_projects),
            batches,
        )
        return {
            "rows_synced":       total_inserted,
            "projects_affected": len(affected_projects),
            "batches":           batches,
        }

    finally:
        await ch.close()


@celery_app.task(
    name="app.tasks.etl.run_clickhouse_etl",
    bind=True,
    max_retries=3,
    default_retry_delay=600,   # retry after 10 min
)
def run_clickhouse_etl(self) -> dict:
    """
    Monthly Celery task: sync new billing records PG → ClickHouse.
    Scheduled by Beat on the 1st of each month at 02:00 UTC.
    Can also be triggered manually: `celery call app.tasks.etl.run_clickhouse_etl`
    """
    try:
        return asyncio.run(_run_etl())
    except Exception as exc:
        logger.error("run_clickhouse_etl failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)   # Rule 8: re-raise via Celery retry
