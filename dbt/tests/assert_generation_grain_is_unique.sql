-- One row per hour and source.
select hour_utc, source_code, count(*) as n
from {{ ref('fct_generation_hourly') }}
group by hour_utc, source_code
having count(*) > 1
