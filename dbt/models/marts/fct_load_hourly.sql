-- Hourly load for Romania from every source we have, side by side.
-- load_actual_mwh prefers ENTSO-E (the TSO's own figure) and falls back to Energy-Charts.

with energy_charts as (
    select date_trunc('hour', interval_start_utc) as hour_utc, avg(value) as mwh
    from {{ ref('stg_energy_charts__public_power') }}
    where energy_charts_name = 'Load'
    group by 1
),

entsoe as (
    select
        date_trunc('hour', interval_start_utc) as hour_utc,
        avg(value) filter (where dataset = 'load-actual') as actual_mwh,
        avg(value) filter (where dataset = 'load-forecast') as forecast_mwh
    from {{ ref('stg_entsoe__points') }}
    where dataset in ('load-actual', 'load-forecast')
    group by 1
),

hours as (
    select hour_utc from energy_charts
    union
    select hour_utc from entsoe
)

select
    h.hour_utc,
    h.hour_utc at time zone 'Europe/Bucharest' as hour_local,
    (h.hour_utc at time zone 'Europe/Bucharest')::date as local_day,
    round(coalesce(e.actual_mwh, ec.mwh), 1) as load_actual_mwh,
    case
        when e.actual_mwh is not null then 'entsoe'
        when ec.mwh is not null then 'energy_charts'
    end as load_actual_source,
    round(e.forecast_mwh, 1) as load_forecast_tso_mwh,
    round(ec.mwh, 1) as load_energy_charts_mwh,
    round(e.actual_mwh, 1) as load_entsoe_mwh
from hours as h
left join energy_charts as ec on h.hour_utc = ec.hour_utc
left join entsoe as e on h.hour_utc = e.hour_utc
