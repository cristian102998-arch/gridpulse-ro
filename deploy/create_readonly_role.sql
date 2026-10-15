-- Read-only role for the public app (and later the SQL agent): marts + ops, nothing else.
-- Run once as the database owner:
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
