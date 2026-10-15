-- ENTSO-E points, one row per interval and series, in UTC. Empty until the API token arrives.

select
    d.dataset,
    d.area,
    d.day as local_day,
    p ->> 'series' as series,
    (p ->> 'is_consumption')::boolean as is_consumption,
    (p ->> 't')::timestamptz as interval_start_utc,
    (p ->> 'res')::int as resolution_minutes,
    (p ->> 'v')::numeric as value
from {{ source('raw', 'entsoe_documents') }} as d
cross join lateral jsonb_array_elements(d.points) as p
