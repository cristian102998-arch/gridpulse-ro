-- Operational log: every CLI job writes one row, whoever runs it (Airflow, GitHub cron, laptop).
-- The Status page reads this instead of the Airflow UI, which is not public.

create schema if not exists ops;

create table if not exists ops.pipeline_runs (
    run_id      bigint generated always as identity primary key,
    job         text        not null,
    runner      text        not null,
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    status      text        not null default 'running' check (status in ('running', 'success', 'failed')),
    details     jsonb
);

create index if not exists pipeline_runs_job_started on ops.pipeline_runs (job, started_at desc);
