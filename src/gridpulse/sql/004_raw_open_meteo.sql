-- Open-Meteo hourly temperatures per city. Already tabular, so stored as rows, not JSON.
-- temp_actual for past hours is the model analysis; for future hours it is the latest forecast.

create table if not exists raw.open_meteo_temperature (
    city              text        not null,
    hour_utc          timestamptz not null,
    temp_actual       real,
    temp_forecast_d1  real,  -- from the model run 24 h before hour_utc
    temp_forecast_d2  real,  -- from the model run 48 h before hour_utc (used by the model)
    fetched_at        timestamptz not null default now(),
    primary key (city, hour_utc)
);

create table if not exists raw.open_meteo_cities (
    city        text primary key,
    lat         real not null,
    lon         real not null,
    population  integer not null
);
