-- Day-ahead price for Romania. Since 1 Oct 2025 the market clears every 15 minutes;
-- the hourly price is the average of its quarter-hours, and the spread inside the hour is kept.

select
    date_trunc('hour', interval_start_utc) as hour_utc,
    date_trunc('hour', interval_start_utc) at time zone 'Europe/Bucharest' as hour_local,
    (date_trunc('hour', interval_start_utc) at time zone 'Europe/Bucharest')::date as local_day,
    round(avg(value), 2) as price_eur_mwh,
    min(value) as price_min_quarter_eur_mwh,
    max(value) as price_max_quarter_eur_mwh,
    count(*) as n_intervals
from {{ ref('stg_entsoe__points') }}
where dataset = 'price'
group by 1
