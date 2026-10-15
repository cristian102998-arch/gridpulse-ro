# 0003 – Raw layer: one row per source and local day, idempotent

**Status:** accepted, 2026-10-15

**Context.** Sources revise recent data (Energy-Charts changed 14 October 2026 on the next day). Romania has 23- and 25-hour days, so "a day" must mean a local Bucharest day, not 24 UTC hours.

**Decision.** Every response is stored as received: a file in the raw zone (`raw/<source>/<dataset>/YYYY/MM/DD`) and a row in `raw.*` keyed by local day, with the payload's SHA-256. The upsert only writes when the hash changes, and the daily job re-fetches the last three days. Parsing happens in dbt staging, never at load time.

**Consequences.** Re-running any range is free and safe. Revisions are picked up automatically and visible in `fetched_at`. dbt tests check that complete days have 23, 24 or 25 hours.
