# Query performance: the app's three main queries

**Measured:** 2026-11-23, local Postgres 18.4, `marts.fct_generation_hourly` at 314,224 rows (2023-01-01 to 2026-10-15).
**How:** `uv run python scripts/explain_app_queries.py --plan`, which runs each query from `app/data.py` with `EXPLAIN (ANALYZE, BUFFERS)` and the date window its page opens on. It reports the median of 9 runs after one warm-up, so these are cached (warm) timings.

## The problem

The marts are dbt tables rebuilt on every run, and dbt creates them without indexes. Every page of the app filters them by `local_day`, so Postgres read the whole table each time:

- `latest_day()` runs on every page to find the last complete day. It needs one value and read all 314,224 rows to get it: a parallel Seq Scan over 2,944 pages.
- The Mix page wants 7 days (1,610 rows). The plan showed `Rows Removed by Filter: 156307` per worker: it read the whole table and threw away 99.5% of it.

## The change

One B-tree index on `local_day` in each of the two tables the pages read, declared in the dbt model so it is recreated on every build:

```sql
{{ config(indexes=[{'columns': ['local_day']}]) }}
```

## Before and after

| Query (page) | Before | After | Plan before → after | Pages read |
|---|---|---|---|---|
| `latest_day` (every page) | 97.94 ms | 0.02 ms | Parallel Seq Scan → Index Only Scan | 2,944 → 4 |
| `generation_hourly` (Mix, 7 days) | 36.65 ms | 2.64 ms | Seq Scan → Bitmap Index Scan | 2,960 → 1,225 |
| `load_vs_forecasts` (Forecast, 8 days) | 1.86 ms | 0.17 ms | Seq Scan → Bitmap Index Scan | 281 → 5 |

`latest_day` gains the most: `max(local_day)` with an index is a walk to the end of the B-tree, so Postgres stops after the first row instead of aggregating 314k.

## What the numbers still show

The Mix query now finds its 1,610 rows through the index but still touches 1,225 pages: the rows of one week are spread across the table instead of sitting together, because dbt writes them in no particular order. Writing the model `order by local_day` (or a periodic `CLUSTER`) would put a week on a few dozen pages. Not done yet: at 2.6 ms it is not the bottleneck.

Timings on Neon will differ (network latency dominates there), but the plans and the pages read are the same, and they are what the index changes.

## Re-checking

Run the script again after the tables grow or a query changes. A plan that goes back to `Seq Scan` on an `fct_` table, or pages read growing with table size rather than with the window, is the sign to look again.
