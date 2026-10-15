# 0002 – Neon Postgres as the production warehouse

**Status:** accepted, 2026-10-15

**Context.** The marts are small (hundreds of MB), queried a few times a day, and must survive the VM being reclaimed. Snowflake's trial ends after 30 days, which would kill a portfolio demo.

**Decision.** Postgres 18 locally and in CI, Neon Free (scale-to-zero, pgvector included) in production. dbt runs against both through the same profile, configured from `DATABASE_URL`.

**Consequences.** Neon Free allows 100 compute-hours a month. To stay under it, the app opens short connections and caches query results, and uptime checks hit Caddy's `/healthz`, never the database: a check every few minutes would keep Neon awake around the clock (~180 CU-hours).
