"""
PostgresVmBillingAdapter — production implementation of BillingDataPort.
Reads from the project_monthly_cost materialized view (fast aggregated data).

Rule 3: all DB calls use `await` — no sync I/O inside async functions.
Rule 4: session is injected (FastAPI Depends) — never opened manually here.
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectMonthlyCost


class PostgresVmBillingAdapter:
    """
    Wraps an AsyncSession. One instance per request (created by FastAPI DI).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_monthly_costs(
        self,
        project_id: str,
        limit_months: int = 36,
    ) -> list[float]:
        """
        Query the materialized view for the most recent `limit_months` months,
        return total_cost values ordered oldest → newest.
        """
        stmt = (
            select(ProjectMonthlyCost.total_cost)
            .where(ProjectMonthlyCost.project_id == project_id)
            .order_by(ProjectMonthlyCost.month.desc())  # newest first for LIMIT
            .limit(limit_months)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        # Reverse so the list is oldest-first (required by all algorithms)
        return list(reversed(rows))

    async def project_exists(self, project_id: str) -> bool:
        """Check if any rows for this project exist in the materialized view."""
        stmt = (
            select(func.count())
            .select_from(ProjectMonthlyCost)
            .where(ProjectMonthlyCost.project_id == project_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return (result.scalar() or 0) > 0
