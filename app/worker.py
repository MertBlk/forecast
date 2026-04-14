"""
Celery application factory.

Broker:  Redis (same instance used for caching)
Backend: Redis (stores task results)

WARNING (from spec): Celery Beat must run as exactly ONE instance.
  Never scale the beat service — it will fire duplicate tasks.
  Only the worker service can be scaled horizontally.
"""
from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "forecast",
    broker=settings.redis_url,
    backend=settings.redis_url,
    # Autodiscover tasks in app/tasks/*.py
    include=["app.tasks.refresh", "app.tasks.etl"],
)

celery_app.conf.update(
    # Serialise task arguments and results as JSON (not pickle — safer)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # ── Beat schedules ───────────────────────────────────────────────
    beat_schedule={
        # Nightly: refresh the materialized view so forecasts use fresh data
        "nightly-refresh": {
            "task":     "app.tasks.refresh.refresh_materialized_view",
            "schedule": crontab(hour=3, minute=0),  # 03:00 UTC every night
        },
        # Monthly ETL: sync PG → ClickHouse
        "monthly-etl": {
            "task":     "app.tasks.etl.run_clickhouse_etl",
            "schedule": crontab(hour=2, minute=0, day_of_month=1),  # 1st of month 02:00
        },
    },
)
