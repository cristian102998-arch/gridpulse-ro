"""Features for the day-ahead load forecast.

The forecast for local day D is made on the morning of D-1. Every feature must be known then:
- load lags of 48 h and more (lag 24 h would use D-1 evening hours that have not happened yet);
- calendar facts (hour, weekday, holidays);
- the temperature forecast issued 48 h before each hour (see sources/open_meteo.py).
"""

import numpy as np
import pandas as pd
import psycopg

FEATURES = [
    "hour",
    "dow",
    "month",
    "doy_sin",
    "doy_cos",
    "is_holiday",
    "is_weekend",
    "lag_48",
    "lag_168",
    "lag_336",
    "lag_mean_4w",
    "temp_forecast",
    "heating_degrees",
    "cooling_degrees",
]
LAGS = (48, 168, 336, 504, 672)

QUERY = """
select w.hour_utc, l.load_actual_mwh::float as load, l.load_forecast_tso_mwh::float as tso,
       w.temp_forecast_c::float as temp_forecast, d.is_holiday, d.is_weekend
from marts.fct_weather_hourly as w
left join marts.fct_load_hourly as l using (hour_utc)
join marts.dim_date as d on d.date_day = w.local_day
order by w.hour_utc
"""


def load_frame(conn: psycopg.Connection) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(QUERY)
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    df["hour_utc"] = pd.to_datetime(df["hour_utc"], utc=True)
    return df.set_index("hour_utc")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add feature columns. The index must be hourly UTC; gaps are filled so shifts are hours."""
    full = pd.date_range(df.index.min(), df.index.max(), freq="h", tz="UTC")
    out = df.reindex(full)
    local = out.index.tz_convert("Europe/Bucharest")
    out["hour"] = local.hour
    out["dow"] = local.dayofweek
    out["month"] = local.month
    doy = local.dayofyear.to_numpy()
    out["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    out["is_holiday"] = out["is_holiday"].astype("float")
    out["is_weekend"] = out["is_weekend"].astype("float")
    for lag in LAGS:
        out[f"lag_{lag}"] = out["load"].shift(lag)
    out["lag_mean_4w"] = out[[f"lag_{k}" for k in (168, 336, 504, 672)]].mean(axis=1)
    out["heating_degrees"] = (16 - out["temp_forecast"]).clip(lower=0)
    out["cooling_degrees"] = (out["temp_forecast"] - 22).clip(lower=0)
    out["local_day"] = local.date
    return out
