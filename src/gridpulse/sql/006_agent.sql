-- Public chat: one row per question asked through the app (for caps, cost tracking and new
-- eval questions), and pre-computed answers to the example questions.

create table if not exists ops.agent_log (
    id            bigint generated always as identity primary key,
    asked_at      timestamptz not null default now(),
    client_hash   text,          -- sha256 of the visitor IP + a server salt, never the IP
    question      text not null,
    answer        text,
    model         text,
    escalated     boolean,
    ok            boolean,
    n_sql         integer,
    cost_usd      real,
    seconds       real
);
create index if not exists agent_log_asked_at on ops.agent_log (asked_at);

create table if not exists ops.agent_cache (
    question    text primary key,
    answer      text not null,
    sql         jsonb,
    model       text not null,
    cost_usd    real,
    created_at  timestamptz not null default now()
);
