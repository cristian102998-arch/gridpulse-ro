import numpy as np
import pandas as pd

from gridpulse.ml.features import FEATURES, build_features


def _frame(hours=24 * 40, start="2025-10-01 00:00"):
    idx = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "load": np.arange(hours, dtype=float),
            "tso": np.nan,
            "temp_forecast": 10.0,
            "is_holiday": False,
            "is_weekend": False,
        },
        index=idx,
    )


def test_lags_are_exact_hours_back():
    f = build_features(_frame())
    row = f.iloc[700]
    assert row["lag_48"] == row["load"] - 48
    assert row["lag_168"] == row["load"] - 168
    assert row["lag_mean_4w"] == row["load"] - (168 + 336 + 504 + 672) / 4


def test_no_feature_peeks_inside_the_last_48_hours():
    # With load = hour number, any feature built from t-1..t-47 would sit within 47 of load.
    f = build_features(_frame())
    for col in ("lag_48", "lag_168", "lag_336", "lag_mean_4w"):
        gap = (f["load"] - f[col]).dropna()
        assert len(gap) > 0 and (gap >= 48).all(), col
    assert "lag_24" not in FEATURES


def test_local_hour_follows_dst():
    f = build_features(_frame(hours=72, start="2025-10-25 18:00"))
    # 2025-10-26 00:00 UTC is 03:00 EEST; 01:00 UTC is 03:00 EET (the repeated hour).
    assert f.loc["2025-10-26 00:00+00:00", "hour"] == 3
    assert f.loc["2025-10-26 01:00+00:00", "hour"] == 3
    assert f.loc["2025-10-26 02:00+00:00", "hour"] == 4


def test_gaps_become_hours_not_shifted_rows():
    df = _frame().drop(pd.Timestamp("2025-10-05 12:00", tz="UTC"))
    f = build_features(df)
    assert len(f) == 24 * 40
    assert f.loc["2025-10-07 12:00+00:00", "lag_48"] != f.loc["2025-10-07 12:00+00:00", "lag_48"]
