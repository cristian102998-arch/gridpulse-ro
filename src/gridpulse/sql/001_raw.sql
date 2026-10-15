-- Raw layer: API responses stored as-is, one row per source/country/local day.
-- Idempotent: safe to run on every `gridpulse db init`.

create schema if not exists raw;

create table if not exists raw.energy_charts_public_power (
    country         text        not null,
    day             date        not null,  -- local day, Europe/Bucharest
    payload         jsonb       not null,  -- Energy-Charts response, sliced to this day
    n_intervals     integer     not null,
    is_complete     boolean     not null,  -- n_intervals matches the day length (23/24/25 h)
    payload_sha256  text        not null,
    fetched_at      timestamptz not null default now(),
    primary key (country, day)
);

comment on table raw.energy_charts_public_power is
    'Energy-Charts public_power (Fraunhofer ISE, CC BY 4.0). Updated only when payload changes.';
