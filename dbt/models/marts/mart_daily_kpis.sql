-- One row per complete local day: the numbers behind the morning bulletin.

with load_day as (
    select
        local_day,
        sum(load_actual_mwh) as load_mwh,
        max(load_actual_mwh) as peak_load_mw,
        (array_agg(hour_local order by load_actual_mwh desc nulls last))[1] as peak_load_hour,
        avg(abs(load_actual_mwh - load_forecast_tso_mwh) / nullif(load_actual_mwh, 0))
            filter (where load_forecast_tso_mwh is not null) as tso_forecast_mape
    from {{ ref('fct_load_hourly') }}
    group by local_day
),

generation_day as (
    select
        f.local_day,
        sum(f.generation_mwh) filter (where s.category = 'generation') as generation_mwh,
        sum(f.generation_mwh) filter (where s.is_renewable) as renewable_mwh
    from {{ ref('fct_generation_hourly') }} as f
    inner join {{ ref('dim_source') }} as s using (source_code)
    group by f.local_day
),

price_day as (
    select
        local_day,
        avg(price_eur_mwh) as price_avg_eur_mwh,
        max(price_eur_mwh) as price_max_eur_mwh,
        min(price_eur_mwh) as price_min_eur_mwh,
        (array_agg(hour_local order by price_eur_mwh desc))[1] as price_peak_hour
    from {{ ref('fct_price_hourly') }}
    group by local_day
)

select
    d.date_day as local_day,
    d.is_holiday,
    d.holiday_name,
    d.is_weekend,
    d.day_hours,
    round(l.load_mwh) as load_mwh,
    round(l.peak_load_mw) as peak_load_mw,
    l.peak_load_hour,
    round(l.tso_forecast_mape * 100, 2) as tso_forecast_mape_pct,
    round(g.generation_mwh) as generation_mwh,
    round(g.renewable_mwh / nullif(g.generation_mwh, 0) * 100, 1) as renewable_share_pct,
    round(g.generation_mwh - l.load_mwh) as generation_minus_load_mwh,
    round(p.price_avg_eur_mwh, 2) as price_avg_eur_mwh,
    round(p.price_max_eur_mwh, 2) as price_max_eur_mwh,
    round(p.price_min_eur_mwh, 2) as price_min_eur_mwh,
    p.price_peak_hour
from {{ ref('dim_date') }} as d
inner join load_day as l on d.date_day = l.local_day
left join generation_day as g on d.date_day = g.local_day
left join price_day as p on d.date_day = p.local_day
where d.date_day < (now() at time zone 'Europe/Bucharest')::date
