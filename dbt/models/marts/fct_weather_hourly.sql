-- National temperature: population-weighted average of 8 large cities.
-- temp_forecast_c is what the load model sees: the forecast issued 48 h earlier, falling back to
-- the 24 h one, then to the analysis, only where Open-Meteo has gaps (~0.5% of 2023-2024 hours).

with weighted as (
    select
        t.hour_utc,
        sum(t.temp_actual * c.population) / sum(c.population)
            filter (where t.temp_actual is not null) as temp_actual_c,
        sum(t.temp_forecast_d2 * c.population) / nullif(sum(c.population)
            filter (where t.temp_forecast_d2 is not null), 0) as temp_forecast_d2_c,
        sum(t.temp_forecast_d1 * c.population) / nullif(sum(c.population)
            filter (where t.temp_forecast_d1 is not null), 0) as temp_forecast_d1_c,
        count(*) filter (where t.temp_forecast_d2 is null) as n_cities_missing_d2
    from {{ source('raw', 'open_meteo_temperature') }} as t
    inner join {{ source('raw', 'open_meteo_cities') }} as c using (city)
    group by t.hour_utc
)

select
    hour_utc,
    hour_utc at time zone 'Europe/Bucharest' as hour_local,
    (hour_utc at time zone 'Europe/Bucharest')::date as local_day,
    round(temp_actual_c::numeric, 2) as temp_actual_c,
    round(coalesce(
        case when n_cities_missing_d2 = 0 then temp_forecast_d2_c end,
        temp_forecast_d1_c,
        temp_actual_c
    )::numeric, 2) as temp_forecast_c,
    case
        when n_cities_missing_d2 = 0 then 'forecast_48h'
        when temp_forecast_d1_c is not null then 'forecast_24h'
        else 'analysis'
    end as temp_forecast_source
from weighted
