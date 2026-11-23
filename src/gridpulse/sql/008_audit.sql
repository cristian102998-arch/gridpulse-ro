-- Audit log: when a row we already had is changed or deleted, keep what it was.
--   raw.*             a source revised a day we had loaded (the upsert updates only when the
--                     payload hash changes, so every row here is a real revision)
--   ml.load_forecasts a forecast already issued for an hour was overwritten (e.g. a rerun)
-- Inserts are not logged: the row itself is the record. TRUNCATE (used by backup restore)
-- does not fire row triggers, so a restore does not flood the log.

create table if not exists ops.audit_log (
    id               bigint generated always as identity primary key,
    changed_at       timestamptz not null default now(),
    table_name       text        not null,
    operation        text        not null check (operation in ('UPDATE', 'DELETE')),
    row_key          jsonb       not null,  -- the primary key of the changed row
    changed_columns  text[],                -- UPDATE only; includes columns left out below
    old_row          jsonb       not null,
    new_row          jsonb,                 -- null for DELETE
    db_user          text        not null default current_user
);

create index if not exists audit_log_table_changed on ops.audit_log (table_name, changed_at desc);

comment on table ops.audit_log is
    'One row per UPDATE or DELETE on an audited table, written by ops.audit_row_change().';

-- Generic row trigger. Trigger arguments name columns too large to copy (the raw payloads);
-- they are left out of old_row/new_row but still reported in changed_columns.
create or replace function ops.audit_row_change() returns trigger
language plpgsql as $$
declare
    skip      text[] := coalesce(tg_argv, '{}');
    old_json  jsonb  := to_jsonb(old);
    new_json  jsonb;
    key_cols  text[];
    changed   text[];
begin
    select array_agg(a.attname::text order by k.ord)
      into key_cols
      from pg_index as i
      cross join lateral unnest(i.indkey) with ordinality as k(attnum, ord)
      join pg_attribute as a on a.attrelid = i.indrelid and a.attnum = k.attnum
     where i.indrelid = tg_relid and i.indisprimary;

    if tg_op = 'UPDATE' then
        new_json := to_jsonb(new);
        select array_agg(n.key order by n.key)
          into changed
          from jsonb_each(new_json) as n
         where n.value is distinct from old_json -> n.key;
        if changed is null then
            return null;  -- an UPDATE that set every column to what it was: nothing to log
        end if;
    end if;

    insert into ops.audit_log (table_name, operation, row_key, changed_columns, old_row, new_row)
    values (
        tg_table_schema || '.' || tg_table_name,
        tg_op,
        (select jsonb_object_agg(c, old_json -> c) from unnest(key_cols) as c),
        changed,
        old_json - skip,
        new_json - skip
    );
    return null;  -- AFTER trigger: the return value is ignored
end
$$;

create or replace trigger audit_energy_charts_public_power
    after update or delete on raw.energy_charts_public_power
    for each row execute function ops.audit_row_change('payload');

create or replace trigger audit_entsoe_documents
    after update or delete on raw.entsoe_documents
    for each row execute function ops.audit_row_change('xml', 'points');

create or replace trigger audit_load_forecasts
    after update or delete on ml.load_forecasts
    for each row execute function ops.audit_row_change();
