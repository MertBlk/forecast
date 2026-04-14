"""
Unit tests for InMemoryBillingAdapter.
Verifies the adapter correctly implements BillingDataPort behaviour
so we can trust it as a test double in integration tests.
"""
import pytest

from app.db.adapters.in_memory import InMemoryBillingAdapter


@pytest.fixture
def adapter():
    a = InMemoryBillingAdapter()
    a.seed("proj-a", [100.0, 200.0, 300.0, 400.0, 500.0])
    a.seed("proj-b", [])   # empty project
    return a


class TestInMemoryAdapter:

    @pytest.mark.asyncio
    async def test_get_monthly_costs_returns_oldest_first(self, adapter):
        costs = await adapter.get_monthly_costs("proj-a")
        assert costs == [100.0, 200.0, 300.0, 400.0, 500.0]

    @pytest.mark.asyncio
    async def test_limit_months_slices_from_end(self, adapter):
        # limit=3 → most recent 3 values, still oldest-first
        costs = await adapter.get_monthly_costs("proj-a", limit_months=3)
        assert costs == [300.0, 400.0, 500.0]

    @pytest.mark.asyncio
    async def test_unknown_project_returns_empty(self, adapter):
        costs = await adapter.get_monthly_costs("does-not-exist")
        assert costs == []

    @pytest.mark.asyncio
    async def test_project_exists_true(self, adapter):
        assert await adapter.project_exists("proj-a") is True

    @pytest.mark.asyncio
    async def test_project_exists_false_for_missing(self, adapter):
        assert await adapter.project_exists("ghost") is False

    @pytest.mark.asyncio
    async def test_project_exists_false_for_empty_list(self, adapter):
        # proj-b was seeded with [] — should not be considered "existing"
        assert await adapter.project_exists("proj-b") is False

    @pytest.mark.asyncio
    async def test_seed_overwrites_existing(self, adapter):
        adapter.seed("proj-a", [999.0])
        costs = await adapter.get_monthly_costs("proj-a")
        assert costs == [999.0]
