# 0008 – An audit trigger on the raw tables and the issued forecasts

**Status:** accepted, 2026-11-23

**Context.** Two kinds of rows can change after they are written. The raw layer is upserted: when Energy-Charts or ENTSO-E revise a day we already loaded, the payload hash changes and the row is overwritten (ADR 0003). And `ml.load_forecasts` is upserted on `(hour_utc, model)`, so rerunning `forecast predict` replaces a day-ahead forecast that was already issued. In both cases the old value was gone, so "how often does the source revise data?" and "is the forecast on the chart the one we actually issued?" had no answer.

**Decision.** One generic PL/pgSQL row trigger, `ops.audit_row_change()`, fired AFTER UPDATE or DELETE on `raw.energy_charts_public_power`, `raw.entsoe_documents` and `ml.load_forecasts`. It writes one row to `ops.audit_log`: the table, the operation, the primary key (read from `pg_index`, so the function needs no per-table code), the columns that changed, and the old and new row as JSONB. Trigger arguments name the columns too large to copy (the raw payloads and XML); they are still listed in `changed_columns`, and the hash columns show what changed. An UPDATE that changes nothing is not logged.

It is a trigger rather than code in the Python upserts because anything that writes to these tables (a backfill, a manual fix in psql, a future job) is covered without remembering to log.

**Consequences.** Inserts are not logged: the row itself is the record, and logging them would double the raw layer. TRUNCATE does not fire row triggers, so a backup restore does not flood the log; `ops.audit_log` is itself in the backup. `raw.open_meteo_temperature` is left out on purpose: forecasts for future hours change on every fetch, so an audit there would mostly record expected updates. The log grows only with real revisions; if that ever becomes large, a retention job can delete rows older than a year.
