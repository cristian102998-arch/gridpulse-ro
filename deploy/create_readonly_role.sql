-- Read-only role for the public app (and later the SQL agent): marts, ops and two ml tables.
-- Run once as the database owner, after `gridpulse db init` and `dbt build`:
--   psql "$DATABASE_URL" -v app_password="'...'" -f deploy/create_readonly_role.sql

do $$
begin
    if not exists (select from pg_roles where rolname = 'gridpulse_app') then
        create role gridpulse_app login;
    end if;
end $$;

alter role gridpulse_app password :app_password;
alter role gridpulse_app set statement_timeout = '10s';
alter role gridpulse_app set default_transaction_read_only = on;

create schema if not exists marts;
create schema if not exists ops;
grant usage on schema marts, ops to gridpulse_app;
grant select on all tables in schema marts, ops to gridpulse_app;

-- dbt recreates tables on every run, so grant on future tables too.
alter default privileges in schema marts grant select on tables to gridpulse_app;
alter default privileges in schema ops grant select on tables to gridpulse_app;

-- The app's model-quality table and daily bulletin page. The agent stays on marts (sql_guard).
grant usage on schema ml to gridpulse_app;
grant select on ml.backtest_metrics, ml.bulletins to gridpulse_app;

-- The one write the public app makes: logging chat questions (for the daily caps).
-- Its connection opens these transactions explicitly as READ WRITE.
grant insert on ops.agent_log to gridpulse_app;
grant usage on sequence ops.agent_log_id_seq to gridpulse_app;

-- Document search (RAG), where pgvector is installed (Neon). Run after `gridpulse rag ingest`.
do $$
begin
    if exists (select from pg_namespace where nspname = 'rag') then
        grant usage on schema rag to gridpulse_app;
        grant select on all tables in schema rag to gridpulse_app;
        alter default privileges in schema rag grant select on tables to gridpulse_app;
    end if;
end $$;
