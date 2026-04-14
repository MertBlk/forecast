"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None   # first migration — no parent
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── vm_billing_records ───────────────────────────────────────────
    op.create_table(
        "vm_billing_records",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id",   sa.String(64),  nullable=False),
        sa.Column("customer_id",  sa.String(64),  nullable=False),
        sa.Column("vm_id",        sa.String(128), nullable=False),
        sa.Column("vm_type",      sa.String(64),  nullable=False),
        sa.Column("region",       sa.String(64),  nullable=False),
        sa.Column("billing_month",sa.Date(),       nullable=False),
        sa.Column("hours_used",   sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_price",   sa.Numeric(10, 6), nullable=False),
        sa.Column("cost_usd",     sa.Numeric(12, 4), nullable=False),
        sa.Column("raw_payload",  JSONB,           nullable=True),
    )

    # Indexes for the two most common query patterns
    op.create_index("ix_vbr_project_id",   "vm_billing_records", ["project_id"])
    op.create_index("ix_vbr_customer_id",  "vm_billing_records", ["customer_id"])

    # Unique constraint: one record per VM per month
    op.create_unique_constraint(
        "uq_vm_billing_month",
        "vm_billing_records",
        ["vm_id", "billing_month"],
    )

    # ── project_monthly_cost (materialized view) ─────────────────────
    # We create the underlying view here via raw SQL.
    # Alembic won't manage it with autogenerate (it only tracks tables),
    # so we use op.execute() to run the DDL directly.
    op.execute("""
        CREATE MATERIALIZED VIEW project_monthly_cost AS
        SELECT
            project_id,
            billing_month                              AS month,
            SUM(cost_usd)::float                       AS total_cost,
            SUM(hours_used)::float                     AS total_hours,
            COUNT(DISTINCT vm_id)                      AS vm_count,
            jsonb_object_agg(vm_type, vm_type_cost)    AS cost_by_vm_type
        FROM (
            -- subquery aggregates cost per (project, month, vm_type) first
            SELECT
                project_id,
                billing_month,
                vm_type,
                SUM(cost_usd) AS vm_type_cost,
                SUM(hours_used) AS vm_type_hours,
                COUNT(DISTINCT vm_id) AS vm_id
            FROM vm_billing_records
            GROUP BY project_id, billing_month, vm_type
        ) t
        GROUP BY project_id, billing_month
        WITH DATA;
    """)

    # Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
    op.execute("""
        CREATE UNIQUE INDEX ix_pmc_project_month
        ON project_monthly_cost (project_id, month);
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS project_monthly_cost;")
    op.drop_table("vm_billing_records")
