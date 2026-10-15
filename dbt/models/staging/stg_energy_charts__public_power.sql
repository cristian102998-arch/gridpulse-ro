-- One row per 15-minute interval and production type, in UTC.
-- The raw JSON keeps timestamps and values in parallel arrays; we zip them by position.

with raw as (
    select country, day, payload
    from {{ source('raw', 'energy_charts_public_power') }}
),

timestamps as (
    select r.country, r.day, t.ord, to_timestamp(t.unix_seconds::bigint) as interval_start_utc
    from raw as r
    cross join lateral jsonb_array_elements_text(r.payload -> 'unix_seconds')
        with ordinality as t (unix_seconds, ord)
),

series as (
    select r.country, r.day, p.value ->> 'name' as energy_charts_name, p.value -> 'data' as data
    from raw as r
    cross join lateral jsonb_array_elements(r.payload -> 'production_types') as p (value)
)

select
    t.country,
    t.day as local_day,
    t.interval_start_utc,
    s.energy_charts_name,
    (s.data ->> (t.ord::int - 1))::numeric as value
from timestamps as t
inner join series as s
    on t.country = s.country and t.day = s.day
