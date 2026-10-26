from datetime import date

import numpy as np
import pandas as pd
import pytest

from gridpulse.ml.features import FEATURES, build_features
from gridpulse.ml.forecast import check_lag_48


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


def test_autumn_dst_target_day_tolerates_one_missing_lag_48():
    # Run on the morning of 2026-10-24: load is known up to the end of 10-23 (local),
    # weather up to 10-25. "Tomorrow" is the 25-hour day 10-25.
    df = _frame(hours=24 * 30, start="2026-09-28 21:00")
    df.loc[df.index >= "2026-10-23 21:00+00:00", "load"] = np.nan
    f = build_features(df)
    target = f[f["local_day"] == date(2026, 10, 25)]
    assert len(target) == 25
    assert target["lag_48"].isna().sum() == 1  # last hour reaches into 10-24 00:00 local
    check_lag_48(target, date(2026, 10, 25))  # must not raise

    # A whole missing day still means ingest did not run.
    df.loc[df.index >= "2026-10-22 21:00+00:00", "load"] = np.nan
    target = build_features(df).pipe(lambda x: x[x["local_day"] == date(2026, 10, 25)])
    with pytest.raises(RuntimeError, match="ingest first"):
        check_lag_48(target, date(2026, 10, 25))
