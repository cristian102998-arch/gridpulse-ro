-- Every load forecast we have for each hour, next to the actual load.
-- naive_168h: the load one week earlier. It is known days in advance, so it never leaks.
-- lgbm: the live day-ahead forecast when it exists, otherwise the out-of-sample prediction from
--       the latest walk-forward backtest (the model never saw that month when predicting it).

with latest_backtest as (
    select max(run_id) as run_id from {{ source('ml', 'backtest_metrics') }}
),

lgbm as (
    select hour_utc, prediction_mwh as mwh, 'live' as kind
    from {{ source('ml', 'load_forecasts') }}
    where model = 'lgbm'
    union all
    select p.hour_utc, p.prediction, 'backtest'
    from {{ source('ml', 'backtest_predictions') }} as p
    inner join latest_backtest as b using (run_id)
    where p.model = 'lgbm'
        and p.hour_utc not in (
            select hour_utc from {{ source('ml', 'load_forecasts') }} where model = 'lgbm'
        )
)

select
    w.hour_utc,
    w.hour_local,
    w.local_day,
    cur.load_actual_mwh,
    prev.load_actual_mwh as forecast_naive_168h_mwh,
    cur.load_forecast_tso_mwh as forecast_tso_mwh,
    round(lgbm.mwh::numeric, 1) as forecast_lgbm_mwh,
    lgbm.kind as forecast_lgbm_kind
from {{ ref('fct_weather_hourly') }} as w
left join {{ ref('fct_load_hourly') }} as cur on w.hour_utc = cur.hour_utc
left join {{ ref('fct_load_hourly') }} as prev
    on prev.hour_utc = w.hour_utc - interval '168 hours'
left join lgbm on w.hour_utc = lgbm.hour_utc
where cur.load_actual_mwh is not null or lgbm.mwh is not null
