"""
BillingDataPort — abstract interface (Protocol) for the forecast engine.

Why Protocol instead of ABC?
  Protocol uses structural subtyping ("duck typing").
  Any class that implements the right methods satisfies the interface
  without inheriting from it — easier to swap adapters in tests.
"""
from typing import Protocol


class BillingDataPort(Protocol):
    """
    Any class that implements these two methods can be used as a
    data source for the forecast engine.
    """

    async def get_monthly_costs(
        self,
        project_id: str,
        limit_months: int = 36,
    ) -> list[float]:
        """
        Return chronological monthly total costs (oldest first) for a project.
        Returns an empty list if the project has no records.

        Args:
            project_id:   the project to query
            limit_months: how many months of history to return (max 36)
        """
        ...

    async def project_exists(self, project_id: str) -> bool:
        """Return True if the project has at least one billing record."""
        ...
