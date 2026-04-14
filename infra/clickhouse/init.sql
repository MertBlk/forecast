-- ClickHouse schema initialisation.
-- Mounted into the ClickHouse container and executed once on first startup.
-- MergeTree engine — columnar, optimised for GROUP BY / SUM at scale.

CREATE DATABASE IF NOT EXISTS billing;

-- ── vm_billing ───────────────────────────────────────────────────────
-- Analytic replica of PostgreSQL vm_billing_records.
-- Partitioned by month so old partitions can be dropped cheaply.
-- ORDER BY determines the sort order inside each part (affects query speed).
CREATE TABLE IF NOT EXISTS billing.vm_billing
(
    billing_month Date,
    project_id    LowCardinality(String),   -- LowCardinality = dictionary encoding (~10× compression for repeated strings)
    customer_id   LowCardinality(String),
    vm_id         String,
    vm_type       LowCardinality(String),
    region        LowCardinality(String),
    hours_used    Float32,
    unit_price    Float32,
    cost_usd      Float32
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(billing_month)        -- one partition per month (YYYYMM int)
ORDER BY (project_id, billing_month, vm_id) -- sort key: most common filter order
SETTINGS index_granularity = 8192;          -- default; tunes sparse index density


-- ── forecast_results ─────────────────────────────────────────────────
-- Stores every forecast ever generated for historical accuracy tracking.
-- Used by the "forecast accuracy history" analytic endpoint.
CREATE TABLE IF NOT EXISTS billing.forecast_results
(
    forecast_id   UUID,
    project_id    LowCardinality(String),
    created_at    DateTime,
    algorithm     LowCardinality(String),
    mape_score    Float32,
    forecast_month Date,
    predicted     Float32,
    lower_ci      Float32,
    upper_ci      Float32
)
ENGINE = MergeTree()
ORDER BY (project_id, created_at, forecast_month)
SETTINGS index_granularity = 8192;
