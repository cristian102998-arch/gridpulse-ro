-- Daily MAPE (%) of each forecast against actual load. Statistical tests live in Python (S2).

select
    local_day,
    count(*) as n_hours,
    round(avg(abs(load_actual_mwh - forecast_naive_168h_mwh) / load_actual_mwh) * 100, 2)
        as mape_naive_168h_pct,
    round(
        avg(abs(load_actual_mwh - forecast_tso_mwh) / load_actual_mwh)
            filter (where forecast_tso_mwh is not null) * 100,
        2
    ) as mape_tso_pct
from {{ ref('fct_load_forecast_baseline') }}
where forecast_naive_168h_mwh is not null
    and local_day < (now() at time zone 'Europe/Bucharest')::date
group by local_day
