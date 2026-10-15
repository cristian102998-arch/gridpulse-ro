-- Hourly generation per source. The average MW over an hour equals the MWh produced in it.
-- Hours are grouped in UTC, so the extra hour of a 25-hour day stays a separate hour.

with quarter_hours as (
    select
        stg.local_day,
        date_trunc('hour', stg.interval_start_utc) as hour_utc,
        src.source_code,
        stg.value
    from {{ ref('stg_energy_charts__public_power') }} as stg
    inner join {{ ref('dim_source') }} as src
        on stg.energy_charts_name = src.energy_charts_name
    where src.category in ('generation', 'storage')
)

select
    hour_utc,
    hour_utc at time zone 'Europe/Bucharest' as hour_local,
    local_day,
    source_code,
    round(avg(value), 1) as generation_mwh,
    count(value) as n_quarters
from quarter_hours
group by hour_utc, local_day, source_code
