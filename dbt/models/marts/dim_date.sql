-- One row per local day, with Romanian public holidays and the day's length (23/24/25 h).

with days as (
    select d::date as date_day
    from generate_series('2023-01-01'::date, '2030-12-31'::date, interval '1 day') as d
)

select
    days.date_day,
    extract(year from days.date_day)::int as year,
    extract(month from days.date_day)::int as month,
    extract(isodow from days.date_day)::int as iso_day_of_week,
    extract(isodow from days.date_day) in (6, 7) as is_weekend,
    h.holiday_date is not null as is_holiday,
    h.holiday_name,
    extract(isodow from days.date_day) not in (6, 7) and h.holiday_date is null as is_working_day,
    (
        extract(epoch from (
            ((days.date_day + 1)::timestamp at time zone 'Europe/Bucharest')
            - (days.date_day::timestamp at time zone 'Europe/Bucharest')
        )) / 3600
    )::int as day_hours
from days
left join {{ ref('ro_public_holidays') }} as h
    on days.date_day = h.holiday_date
