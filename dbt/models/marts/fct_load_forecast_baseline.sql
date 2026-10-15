-- Seasonal naive baseline: the load at the same UTC hour one week earlier (lag 168 h).
-- It is known days in advance, so it never leaks the future (see ADR 0004).
-- Any real model has to beat this, and the TSO forecast, to be worth anything.

select
    cur.hour_utc,
    cur.hour_local,
    cur.local_day,
    cur.load_actual_mwh,
    prev.load_actual_mwh as forecast_naive_168h_mwh,
    cur.load_forecast_tso_mwh as forecast_tso_mwh
from {{ ref('fct_load_hourly') }} as cur
left join {{ ref('fct_load_hourly') }} as prev
    on prev.hour_utc = cur.hour_utc - interval '168 hours'
where cur.load_actual_mwh is not null
