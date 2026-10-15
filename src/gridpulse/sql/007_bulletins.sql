-- The morning bulletin per day: the prose (LLM or template) and the facts it was written from.

create table if not exists ml.bulletins (
    local_day   date primary key,
    source      text not null,  -- the model name, or 'template' when the guardrail fell back
    content     jsonb not null,
    facts       jsonb not null,
    cost_usd    real,
    created_at  timestamptz not null default now()
);
