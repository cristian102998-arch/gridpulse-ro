# 0001 – Airflow 3 on a free Oracle VM, GitHub Actions as failover

**Status:** accepted, 2026-10-15

**Context.** Airflow is the orchestrator most job ads ask for, and a demo that says "runs 24/7" has to actually run 24/7. Managed Airflow (Astronomer, MWAA) starts around $250 a month. A small VPS costs €8–9 a month and its availability was uncertain in autumn 2026.

**Decision.** Run Airflow 3 with the LocalExecutor (api-server, scheduler, dag-processor, a metadata Postgres; no Redis, Celery or triggerer) on an Oracle Always Free Ampere A1 VM (2 OCPU, 12 GB, arm64). The warehouse stays on Neon, so losing the VM loses no data. Every task calls the `gridpulse` CLI, and a GitHub Actions cron runs the same commands; it was the scheduler for the first days and stays as a documented failover.

**Consequences.** Images must be built for arm64 (GitHub's ARM runners are free for public repos). The Airflow UI is not public: it is reached through an SSH tunnel, and the app's Status page reads `ops.pipeline_runs` instead. Oracle may reclaim idle instances, so the VM is rebuildable from `deploy/docker-compose.yml` in minutes.
