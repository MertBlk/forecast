# Golden Rules Audit — Phase 4

Audited: 2026-04-13

## Rule 1 — NEVER forecast with < 4 months → 422
| Location | Status | Evidence |
|---|---|---|
| `app/api/v1/forecast.py:161` | ✅ | `if len(costs) < 4: raise HTTPException(422, INSUFFICIENT_DATA)` |
| `app/core/algorithms/auto_select.py:69` | ✅ | Second guard: `_candidates_for` raises `ValueError` if `n_months < 4` |
| `tests/integration/test_forecast_api.py` | ✅ | `test_forecast_422_insufficient_data` verifies the 422 path |

## Rule 2 — NEVER shuffle time series data
| Location | Status | Evidence |
|---|---|---|
| `app/core/algorithms/auto_select.py` | ✅ | `_walk_forward_mape` uses chronological index splits (`values[:split]`) |
| Codebase-wide grep for `shuffle`, `random.sample`, `train_test_split` | ✅ | Zero matches in `app/` |
| `tests/unit/test_auto_select.py` | ✅ | `test_never_shuffles_data` verifies ordered splits |

## Rule 3 — NEVER use sync I/O inside async functions
| Location | Status | Evidence |
|---|---|---|
| `app/db/adapters/clickhouse.py` | ✅ | Every blocking call wrapped in `await loop.run_in_executor(None, ...)` |
| `app/services/cache.py` | ✅ | Uses `redis.asyncio` — all calls are `await`ed |
| `app/db/adapters/postgres.py` | ✅ | Uses SQLAlchemy async engine; `await session.execute(...)` |
| `app/tasks/refresh.py` + `etl.py` | ✅ | Celery tasks are sync; async code isolated in `async def` helpers called via `asyncio.run()` |

## Rule 4 — ALWAYS open DB sessions with `async with AsyncSessionLocal()`
| Location | Status | Evidence |
|---|---|---|
| `app/db/session.py:34` | ✅ | `get_db()` uses `async with AsyncSessionLocal() as session` |
| `app/tasks/refresh.py:34` | ✅ | `_refresh_view_async()` uses `async with AsyncSessionLocal()` |
| `app/tasks/etl.py:47` | ✅ | `_run_etl()` uses `async with AsyncSessionLocal()` |

## Rule 5 — ALWAYS call `cache.invalidate_project()` after every ETL run
| Location | Status | Evidence |
|---|---|---|
| `app/tasks/etl.py:72–80` | ✅ | Iterates `affected_projects`, calls `cache.invalidate_project()` for each |
| Log message | ✅ | `logger.info("etl: invalidated %d cache keys for project %s", ...)` |

## Rule 6 — ALWAYS insert to ClickHouse in batches (10K rows)
| Location | Status | Evidence |
|---|---|---|
| `app/db/adapters/clickhouse.py` | ✅ | `BATCH_SIZE = 10_000`; loop: `for i in range(0, len(rows), BATCH_SIZE)` |
| `app/tasks/etl.py` | ✅ | Calls `ch.insert_billing_rows(rows)` which enforces batching internally |

## Rule 7 — NEVER hardcode secrets
| Location | Status | Evidence |
|---|---|---|
| `app/config.py` | ✅ | All secrets read from env vars via `pydantic-settings` |
| `docker-compose.yml` | ✅ | `${POSTGRES_PASSWORD:?...}` — aborts if missing; no inline value |
| `.gitignore` | ✅ | `.env` is gitignored |
| Grep for `password = "` in `app/` | ✅ | Zero matches (only `clickhouse_password: str = ""` — empty default, not a secret) |

## Rule 8 — NEVER swallow exceptions with bare `except/pass`
| Location | Status | Evidence |
|---|---|---|
| Grep for `except Exception: pass` | ✅ | **Fixed in Phase 4** — was `pass` in `forecast.py:202`, now logs with `logger.warning` |
| `app/api/v1/analytics.py` | ✅ | All `except Exception as exc` blocks log + raise `HTTPException` |
| `app/tasks/refresh.py` | ✅ | `except Exception as exc` → `logger.error` + `self.retry(exc=exc)` |
| `app/tasks/etl.py` | ✅ | Same pattern |
| `app/core/algorithms/auto_select.py:121` | ✅ | Records error message in `errors` dict; raises `ValueError` if all fail |

## Summary
All 8 rules pass. One violation found and fixed during audit:
- **Rule 8** — `forecast.py:202` had `except Exception: pass` → replaced with `logger.warning`
