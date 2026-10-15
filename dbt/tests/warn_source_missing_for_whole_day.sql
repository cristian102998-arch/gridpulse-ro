-- A source with no value at all for a complete past day is a gap in the feed, not a zero.
-- Found on real data: Energy-Charts has no nuclear values for the whole of September 2026.
-- Warn only: the gap is upstream; ENTSO-E reconciliation will tell outage from missing data.
{{ config(severity='warn') }}

select local_day, source_code
from {{ ref('fct_generation_hourly') }}
where local_day < (now() at time zone 'Europe/Bucharest')::date
group by local_day, source_code
having count(generation_mwh) = 0
