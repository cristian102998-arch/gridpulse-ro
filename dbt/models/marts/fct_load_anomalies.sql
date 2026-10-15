-- Hours where actual load was unusually far from the LightGBM forecast.
-- Robust z-score: (residual - median) / (1.4826 * MAD). Median and MAD come from the same
-- local hour of the previous 28 days only: midday errors (rooftop solar) and night errors
-- behave differently, and a single extreme hour cannot hide itself by inflating the spread.
-- |z| >= 3.5 is the usual robust-outlier threshold (Iglewicz & Hoaglin).

with residuals as (
    select
        hour_utc, hour_local, local_day,
        extract(hour from hour_local)::int as local_hour,
        load_actual_mwh, forecast_lgbm_mwh,
        load_actual_mwh - forecast_lgbm_mwh as residual_mwh
    from {{ ref('fct_load_forecast_baseline') }}
    where load_actual_mwh is not null and forecast_lgbm_mwh is not null
),

stats as (
    select
        r.hour_utc,
        m.median_mwh,
        m.n_days,
        (
            select percentile_cont(0.5) within group (order by abs(h.residual_mwh - m.median_mwh))
            from residuals as h
            where h.local_hour = r.local_hour
                and h.local_day >= r.local_day - 28 and h.local_day < r.local_day
        ) as mad_mwh
    from residuals as r
    cross join lateral (
        select percentile_cont(0.5) within group (order by h.residual_mwh) as median_mwh,
               count(*) as n_days
        from residuals as h
        where h.local_hour = r.local_hour
            and h.local_day >= r.local_day - 28 and h.local_day < r.local_day
    ) as m
)

select
    r.hour_utc,
    r.hour_local,
    r.local_day,
    r.load_actual_mwh,
    r.forecast_lgbm_mwh,
    round(r.residual_mwh, 1) as residual_mwh,
    round(((r.residual_mwh - s.median_mwh) / nullif(1.4826 * s.mad_mwh, 0))::numeric, 2)
        as robust_z,
    coalesce(
        abs((r.residual_mwh - s.median_mwh) / nullif(1.4826 * s.mad_mwh, 0)) >= 3.5, false
    ) as is_anomaly
from residuals as r
inner join stats as s using (hour_utc)
where s.n_days >= 14  -- need two weeks of the same hour before judging
