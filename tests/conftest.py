"""
Shared pytest configuration.
Provides app-level fixtures reused across unit and integration test suites.
"""
import pytest
from app.db.adapters.in_memory import InMemoryBillingAdapter


@pytest.fixture
def sample_costs_12() -> list[float]:
    """12 months of realistic billing data, oldest first."""
    return [
        1200.0, 1250.0, 1100.0, 1300.0, 1350.0, 1400.0,
        1380.0, 1420.0, 1500.0, 1480.0, 1550.0, 1600.0,
    ]


@pytest.fixture
def sample_costs_24(sample_costs_12) -> list[float]:
    """24 months — required for seasonal algorithm."""
    return [800.0 + i * 20 for i in range(12)] + sample_costs_12


@pytest.fixture
def in_memory_adapter(sample_costs_12) -> InMemoryBillingAdapter:
    """InMemoryAdapter pre-seeded with a single project."""
    a = InMemoryBillingAdapter()
    a.seed("proj-test", sample_costs_12)
    return a
