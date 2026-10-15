"""LightGBM day-ahead load forecast: walk-forward backtest and the daily prediction."""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import lightgbm as lgb
import pandas as pd
import psycopg

from gridpulse.ml.features import FEATURES, build_features, load_frame
from gridpulse.ml.stats import block_bootstrap_ci, diebold_mariano

log = logging.getLogger(__name__)

PARAMS = {
    "objective": "l2",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 50,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.8,
    "verbose": -1,
    "seed": 42,
}
NUM_ROUNDS = 600
MODEL_VERSION = "lgbm-v2"  # v2: near_holiday feature


def fit(train: pd.DataFrame) -> lgb.Booster:
    train = train.dropna(subset=["load", "lag_48", "lag_168"])
    data = lgb.Dataset(train[FEATURES], label=train["load"])
    return lgb.train(PARAMS, data, num_boost_round=NUM_ROUNDS)


@dataclass(frozen=True)
class ModelScore:
    model: str
    n_days: int
    mape: float
    ci_low: float
    ci_high: float
    vs_model: str | None = None
    dm_stat: float | None = None
    dm_p_value: float | None = None


def walk_forward(feat: pd.DataFrame, test_months: list[pd.Period]) -> pd.DataFrame:
    """Refit at the start of every test month on all earlier data (expanding window)."""
    preds = []
    month = feat.index.tz_convert("Europe/Bucharest").tz_localize(None).to_period("M")
    for m in test_months:
        train = feat[month < m]
        test = feat[(month == m) & feat["load"].notna()]
        if test.empty:
            continue
        model = fit(train)
        out = test[["local_day", "load", "tso", "lag_168"]].copy()
        out["lgbm"] = model.predict(test[FEATURES])
        preds.append(out)
        log.info("backtest %s: trained on %d hours, predicted %d", m, len(train), len(test))
    return pd.concat(preds).rename(columns={"lag_168": "naive_168h"})


def score(preds: pd.DataFrame, models=("lgbm", "naive_168h", "tso")) -> list[ModelScore]:
    """Daily MAPE per model with a 7-day block bootstrap CI; DM test of LightGBM vs each other."""
    ape = {
        m: (preds[m] - preds["load"]).abs() / preds["load"]
        for m in models
        if preds[m].notna().mean() > 0.95
    }
    daily = pd.DataFrame({m: s.groupby(preds["local_day"]).mean() for m, s in ape.items()})
    daily = daily.dropna()
    scores = []
    for m in daily.columns:
        lo, hi = block_bootstrap_ci(daily[m].to_numpy())
        s = ModelScore(m, len(daily), daily[m].mean() * 100, lo * 100, hi * 100)
        if m != "lgbm" and "lgbm" in daily:
            dm = diebold_mariano(daily["lgbm"].to_numpy(), daily[m].to_numpy())
            s = ModelScore(
                **{
                    **s.__dict__,
                    "vs_model": "lgbm",
                    "dm_stat": dm.statistic,
                    "dm_p_value": dm.p_value,
                }
            )
        scores.append(s)
    return scores


def run_backtest(conn: psycopg.Connection, months: int = 12) -> tuple[str, list[ModelScore]]:
    feat = build_features(load_frame(conn))
    observed = feat[feat["load"].notna()]
    last_full = (
        observed.index.max().tz_convert("Europe/Bucharest").tz_localize(None).to_period("M") - 1
    )
    test_months = [last_full - i for i in range(months - 1, -1, -1)]
    preds = walk_forward(feat, test_months)
    scores = score(preds)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    save_backtest(conn, run_id, preds, scores, test_months)
    return run_id, scores


def save_backtest(conn, run_id, preds, scores, test_months) -> None:
    with conn.transaction():
        with conn.cursor().copy(
            "copy ml.backtest_predictions (run_id, hour_utc, model, prediction) from stdin"
        ) as copy:
            for model in ("lgbm", "naive_168h", "tso"):
                for ts, value in preds[model].dropna().items():
                    copy.write_row((run_id, ts.to_pydatetime(), model, float(value)))
        for s in scores:
            conn.execute(
                """
                insert into ml.backtest_metrics
                    (run_id, model, model_version, test_start, test_end, n_days, mape_pct,
                     mape_ci_low_pct, mape_ci_high_pct, dm_vs_model, dm_stat, dm_p_value)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    s.model,
                    MODEL_VERSION if s.model == "lgbm" else None,
                    test_months[0].start_time.date(),
                    test_months[-1].end_time.date(),
                    s.n_days,
                    s.mape,
                    s.ci_low,
                    s.ci_high,
                    s.vs_model,
                    s.dm_stat,
                    s.dm_p_value,
                ),
            )


def predict_day(conn: psycopg.Connection, day: date) -> int:
    """Train on everything known and forecast the 23-25 hours of local day `day`."""
    feat = build_features(load_frame(conn))
    target = feat[feat["local_day"] == day]
    if target.empty or target["temp_forecast"].isna().any():
        raise RuntimeError(f"no weather forecast for {day} yet; ingest open-meteo first")
    if target["lag_48"].isna().any():
        raise RuntimeError(f"load for {day} minus 2 days is missing; ingest first")
    # Issued on the morning of D-1: train only on hours that had happened by then.
    cutoff = target.index.min() - pd.Timedelta(hours=24)
    model = fit(feat[feat.index < cutoff])
    values = model.predict(target[FEATURES])
    issued_at = datetime.now(UTC)
    with conn.transaction():
        for ts, v in zip(target.index, values, strict=True):
            conn.execute(
                """
                insert into ml.load_forecasts (hour_utc, model, model_version, prediction_mwh,
                                               issued_at)
                values (%s, 'lgbm', %s, %s, %s)
                on conflict (hour_utc, model) do update set
                    prediction_mwh = excluded.prediction_mwh,
                    model_version = excluded.model_version,
                    issued_at = excluded.issued_at
                """,
                (ts.to_pydatetime(), MODEL_VERSION, float(v), issued_at),
            )
    return len(values)


def as_table(scores: list[ModelScore]) -> str:
    lines = [f"{'model':<12}{'MAPE %':>8}{'95% CI':>18}{'DM vs lgbm':>12}{'p':>10}"]
    for s in sorted(scores, key=lambda s: s.mape):
        ci = f"[{s.ci_low:.2f}, {s.ci_high:.2f}]"
        dm = f"{s.dm_stat:.2f}" if s.dm_stat is not None else "-"
        p = f"{s.dm_p_value:.4f}" if s.dm_p_value is not None else "-"
        lines.append(f"{s.model:<12}{s.mape:>8.2f}{ci:>18}{dm:>12}{p:>10}")
    return "\n".join(lines) + f"\n(n = {scores[0].n_days} days)" if scores else ""
