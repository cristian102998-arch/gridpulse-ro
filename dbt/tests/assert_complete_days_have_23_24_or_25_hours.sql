-- A finished local day has 23 hours (end of March), 25 (end of October) or 24 (any other day).
-- Today is still in progress, so it is skipped.
select local_day, count(distinct hour_utc) as n_hours
from {{ ref('fct_generation_hourly') }}
where local_day < (now() at time zone 'Europe/Bucharest')::date
group by local_day
having count(distinct hour_utc) not in (23, 24, 25)
    or count(distinct hour_utc) <> extract(
        epoch from (
            ((local_day + 1)::timestamp at time zone 'Europe/Bucharest')
            - (local_day::timestamp at time zone 'Europe/Bucharest')
        )
    ) / 3600
