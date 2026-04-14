import uuid
from datetime import date

from sqlalchemy import (
    Column,
    Date,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.session import Base


class VmBillingRecord(Base):
    """
    System-of-record table — raw billing data, never deleted.
    Maps directly to the vm_billing_records table in the spec.
    """
    __tablename__ = "vm_billing_records"

    id = Column(
        UUID(as_uuid=True),          # store as Python uuid.UUID, not a string
        primary_key=True,
        default=uuid.uuid4,          # DB-side default is also fine; Python default works too
    )
    project_id  = Column(String(64), nullable=False, index=True)
    customer_id = Column(String(64), nullable=False, index=True)
    vm_id       = Column(String(128), nullable=False)
    vm_type     = Column(String(64),  nullable=False)
    region      = Column(String(64),  nullable=False)

    # Always stored as the 1st of the month (e.g. 2024-03-01)
    billing_month = Column(Date, nullable=False)

    hours_used  = Column(Numeric(10, 2), nullable=False)
    unit_price  = Column(Numeric(10, 6), nullable=False)
    cost_usd    = Column(Numeric(12, 4), nullable=False)  # = hours_used * unit_price

    # Raw vendor payload — keeps original data for auditing / reprocessing
    raw_payload = Column(JSONB, nullable=True)

    # Prevent duplicate records for the same VM in the same month
    __table_args__ = (
        UniqueConstraint("vm_id", "billing_month", name="uq_vm_billing_month"),
    )


class ProjectMonthlyCost(Base):
    """
    Materialized-view mirror for SQLAlchemy awareness.
    The actual view is created by SQL (not Alembic) — this model lets us
    query it with the ORM. We mark it as a view so Alembic doesn't try
    to CREATE TABLE for it.
    """
    __tablename__ = "project_monthly_cost"

    # Composite primary key mirrors the view's grain
    project_id   = Column(String(64), primary_key=True)
    month        = Column(Date,       primary_key=True)

    total_cost   = Column(Float,   nullable=False)
    total_hours  = Column(Float,   nullable=False)
    vm_count     = Column(Integer, nullable=False)

    # {"standard": 1200.50, "highmem": 340.00}
    cost_by_vm_type = Column(JSONB, nullable=True)
