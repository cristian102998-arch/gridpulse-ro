-- Forecast outputs written by Python (gridpulse forecast ...), read by dbt and the app.

create schema if not exists ml;

create table if not exists ml.load_forecasts (
    hour_utc        timestamptz not null,
    model           text        not null,
    model_version   text        not null,
    prediction_mwh  real        not null,
    issued_at       timestamptz not null,
    primary key (hour_utc, model)
);

create table if not exists ml.backtest_predictions (
    run_id      text        not null,
    hour_utc    timestamptz not null,
    model       text        not null,
    prediction  real        not null,
    primary key (run_id, hour_utc, model)
);

create table if not exists ml.backtest_metrics (
    run_id            text    not null,
    model             text    not null,
    model_version     text,
    test_start        date    not null,
    test_end          date    not null,
    n_days            integer not null,
    mape_pct          real    not null,
    mape_ci_low_pct   real    not null,
    mape_ci_high_pct  real    not null,
    dm_vs_model       text,
    dm_stat           real,
    dm_p_value        real,
    created_at        timestamptz not null default now(),
    primary key (run_id, model)
);
