"""
ClickHouseAdapter — wraps clickhouse-connect for async FastAPI use.

Why run_in_executor?
  clickhouse-connect's Client is synchronous (no native async API).
  Calling it directly inside an `async def` would block the event loop —
  Rule 3 violation. run_in_executor() offloads the blocking call to a
  thread-pool worker, freeing the event loop for other requests.

Rule 6: all inserts are batched (BATCH_SIZE rows per INSERT).
Rule 3: every public method is async and uses run_in_executor internally.
Rule 8: exceptions are logged and re-raised — never swallowed.
"""
import asyncio
import logging
from datetime import date, datetime
from functools import partial
from typing import Any
from uuid import UUID

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from app.config import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000   # Rule 6: always insert in chunks of 10K


def _make_client() -> Client:
    """Create a synchronous ClickHouse client (called inside executor)."""
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_db,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )


class ClickHouseAdapter:
    """
    One shared instance — created in app lifespan, stored on app.state.
    All public methods are async; they delegate sync work to a thread pool.
    """

    def __init__(self) -> None:
        # Client is created lazily on first use so startup doesn't block
        self._client: Client | None = None
        self._lock = asyncio.Lock()   # prevents two threads from creating the client simultaneously

    async def _get_client(self) -> Client:
        """Lazy-init: create the client once, reuse forever."""
        if self._client is not None:
            return self._client
        async with self._lock:
            # Double-check after acquiring lock
            if self._client is None:
                loop = asyncio.get_running_loop()
                self._client = await loop.run_in_executor(None, _make_client)
        return self._client

    # ── Writes ───────────────────────────────────────────────────────

    async def insert_billing_rows(self, rows: list[dict]) -> int:
        """
        Insert billing records into billing.vm_billing in BATCH_SIZE chunks.
        Rule 6: never insert row-by-row.

        Args:
            rows: list of dicts with keys matching vm_billing columns.

        Returns:
            Total rows inserted.
        """
        if not rows:
            return 0

        client = await self._get_client()
        loop   = asyncio.get_running_loop()

        columns = [
            "billing_month", "project_id", "customer_id", "vm_id",
            "vm_type", "region", "hours_used", "unit_price", "cost_usd",
        ]

        total = 0
        # Split into chunks of BATCH_SIZE — Rule 6
        for i in range(0, len(rows), BATCH_SIZE):
            chunk = rows[i : i + BATCH_SIZE]
            # Build a list-of-lists matching column order
            data = [
                [
                    row["billing_month"],   # date object
                    row["project_id"],
                    row["customer_id"],
                    row["vm_id"],
                    row["vm_type"],
                    row["region"],
                    float(row["hours_used"]),
                    float(row["unit_price"]),
                    float(row["cost_usd"]),
                ]
                for row in chunk
            ]

            # run_in_executor: offload blocking insert to thread pool (Rule 3)
            await loop.run_in_executor(
                None,
                partial(
                    client.insert,
                    "billing.vm_billing",
                    data,
                    column_names=columns,
                ),
            )
            total += len(chunk)
            logger.info("clickhouse: inserted %d/%d billing rows", total, len(rows))

        return total

    async def insert_forecast_result(self, forecast: dict) -> None:
        """
        Persist a forecast result to billing.forecast_results.
        Called from the forecast endpoint after every generated forecast.
        """
        client = await self._get_client()
        loop   = asyncio.get_running_loop()

        columns = [
            "forecast_id", "project_id", "created_at", "algorithm",
            "mape_score", "forecast_month", "predicted", "lower_ci", "upper_ci",
        ]
        data = [[
            str(forecast["forecast_id"]),
            forecast["project_id"],
            forecast["created_at"],
            forecast["algorithm"],
            float(forecast.get("mape_score") or 0.0),
            forecast["forecast_month"],   # date object for the first predicted month
            float(forecast["predicted"]),
            float(forecast["lower_ci"]),
            float(forecast["upper_ci"]),
        ]]

        await loop.run_in_executor(
            None,
            partial(client.insert, "billing.forecast_results", data, column_names=columns),
        )

    # ── Reads (analytic queries) ─────────────────────────────────────

    async def get_cross_project_summary(
        self,
        start_month: date,
        end_month: date,
    ) -> list[dict]:
        """
        Aggregate total cost per project for a date range.
        Uses ClickHouse — 5–50× faster than Postgres for this kind of query.
        """
        client = await self._get_client()
        loop   = asyncio.get_running_loop()

        query = """
            SELECT
                project_id,
                sum(cost_usd)   AS total_cost,
                sum(hours_used) AS total_hours,
                count()         AS record_count
            FROM billing.vm_billing
            WHERE billing_month >= {start:Date}
              AND billing_month <= {end:Date}
            GROUP BY project_id
            ORDER BY total_cost DESC
        """
        # run_in_executor offloads the blocking query call (Rule 3)
        result = await loop.run_in_executor(
            None,
            partial(
                client.query,
                query,
                parameters={"start": start_month, "end": end_month},
            ),
        )
        # result.named_results() → list of dicts
        return result.named_results()

    async def get_vm_type_trend(
        self,
        project_id: str,
        months: int = 12,
    ) -> list[dict]:
        """
        Monthly cost broken down by vm_type for a project.
        Used by dashboard/BI — cross-month GROUP BY is where CH shines.
        """
        client = await self._get_client()
        loop   = asyncio.get_running_loop()

        query = """
            SELECT
                billing_month,
                vm_type,
                sum(cost_usd)   AS cost,
                sum(hours_used) AS hours
            FROM billing.vm_billing
            WHERE project_id = {project_id:String}
              AND billing_month >= toDate(now()) - INTERVAL {months:UInt32} MONTH
            GROUP BY billing_month, vm_type
            ORDER BY billing_month ASC, cost DESC
        """
        result = await loop.run_in_executor(
            None,
            partial(
                client.query,
                query,
                parameters={"project_id": project_id, "months": months},
            ),
        )
        return result.named_results()

    async def get_forecast_accuracy_history(
        self,
        project_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Return recent forecasts with their MAPE scores for accuracy tracking.
        """
        client = await self._get_client()
        loop   = asyncio.get_running_loop()

        query = """
            SELECT
                forecast_id,
                created_at,
                algorithm,
                mape_score,
                forecast_month,
                predicted,
                lower_ci,
                upper_ci
            FROM billing.forecast_results
            WHERE project_id = {project_id:String}
            ORDER BY created_at DESC
            LIMIT {limit:UInt32}
        """
        result = await loop.run_in_executor(
            None,
            partial(
                client.query,
                query,
                parameters={"project_id": project_id, "limit": limit},
            ),
        )
        return result.named_results()

    async def get_max_synced_billing_month(self) -> date | None:
        """
        Return the latest billing_month already in ClickHouse.
        The ETL task uses this to know where to resume (idempotency).
        Returns None if the table is empty.
        """
        client = await self._get_client()
        loop   = asyncio.get_running_loop()

        result = await loop.run_in_executor(
            None,
            partial(client.query, "SELECT max(billing_month) FROM billing.vm_billing"),
        )
        val = result.first_row[0] if result.first_row else None
        # ClickHouse returns date(1970,1,1) for max() on an empty table
        if val and val.year == 1970:
            return None
        return val

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._client is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._client.close)
            self._client = None
