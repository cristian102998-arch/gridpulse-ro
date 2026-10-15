-- Reconciliation: ENTSO-E and Energy-Charts daily load should agree within 2%.
-- Energy-Charts most likely republishes ENTSO-E for Romania, so this mainly catches
-- pipeline bugs (lost hours, double counting, DST) rather than two independent truths.
{{ config(severity='warn') }}

select
    local_day,
    sum(load_entsoe_mwh) as entsoe_mwh,
    sum(load_energy_charts_mwh) as energy_charts_mwh
from {{ ref('fct_load_hourly') }}
where load_entsoe_mwh is not null and load_energy_charts_mwh is not null
group by local_day
having abs(sum(load_entsoe_mwh) - sum(load_energy_charts_mwh))
    > 0.02 * sum(load_entsoe_mwh)
