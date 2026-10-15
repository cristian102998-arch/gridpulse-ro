-- ENTSO-E responses, one row per dataset/area/local day.
-- The XML is kept as received; `points` is the parsed form dbt reads (Postgres XML parsing is painful).

create table if not exists raw.entsoe_documents (
    dataset         text        not null,  -- load-actual | load-forecast | generation | price
    area            text        not null,  -- EIC code, 10YRO-TEL------P for Romania
    day             date        not null,  -- local day, Europe/Bucharest
    xml             text        not null,
    points          jsonb       not null,  -- [{series, is_consumption, t, res, v}, ...]
    n_points        integer     not null,
    payload_sha256  text        not null,
    fetched_at      timestamptz not null default now(),
    primary key (dataset, area, day)
);
