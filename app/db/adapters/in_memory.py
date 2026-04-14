"""
InMemoryBillingAdapter — test double for BillingDataPort.

Zero DB connections needed. Inject pre-seeded data in unit/integration tests.
This is the adapter that makes `pytest` fast — no Docker, no migrations.
"""


class InMemoryBillingAdapter:
    """
    Stores costs as a dict: {project_id: [cost_month_0, cost_month_1, ...]}
    Values must be chronological (oldest first), same as the real adapter.
    """

    def __init__(self, data: dict[str, list[float]] | None = None) -> None:
        # Default to empty store; tests can pass pre-built data
        self._data: dict[str, list[float]] = data or {}

    async def get_monthly_costs(
        self,
        project_id: str,
        limit_months: int = 36,
    ) -> list[float]:
        costs = self._data.get(project_id, [])
        # Return only the most recent `limit_months`, oldest first
        return costs[-limit_months:]

    async def project_exists(self, project_id: str) -> bool:
        return project_id in self._data and len(self._data[project_id]) > 0

    # ── Helpers for test setup ───────────────────────────────────────
    def seed(self, project_id: str, costs: list[float]) -> None:
        """Add or replace data for a project. Use in test fixtures."""
        self._data[project_id] = costs
