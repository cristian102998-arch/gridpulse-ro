"""Read-only queries for the app. Short-lived connections + caching keep Neon's free compute low."""

import os

import pandas as pd
import psycopg
import streamlit as st


def _database_url() -> str:
    try:
        return st.secrets["DATABASE_URL"]
    except (FileNotFoundError, KeyError):
        return os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/gridpulse")


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    with psycopg.connect(_database_url(), connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


@st.cache_data(ttl=600)
def latest_day():
    """Last complete local day. Today is still in progress, so it is left out."""
    df = query(
        """
        select max(local_day) as d from marts.fct_generation_hourly
        where local_day < (now() at time zone 'Europe/Bucharest')::date
        """
    )
    return df["d"].iloc[0]


@st.cache_data(ttl=600)
def generation_hourly(start, end) -> pd.DataFrame:
    return query(
        """
        select f.hour_local, s.source_label, s.is_renewable, s.display_order,
               f.generation_mwh::float as mwh
        from marts.fct_generation_hourly as f
        join marts.dim_source as s using (source_code)
        where f.local_day between %(start)s and %(end)s
        order by f.hour_utc, s.display_order
        """,
        {"start": start, "end": end},
    )


@st.cache_data(ttl=600)
def daily_kpis(days: int = 30) -> pd.DataFrame:
    return query(
        "select * from marts.mart_daily_kpis order by local_day desc limit %(n)s", {"n": days}
    )


@st.cache_data(ttl=600)
def load_vs_forecasts(start, end) -> pd.DataFrame:
    return query(
        """
        select hour_local, load_actual_mwh::float as actual,
               forecast_naive_168h_mwh::float as naive_168h, forecast_tso_mwh::float as tso,
               forecast_lgbm_mwh::float as lgbm
        from marts.fct_load_forecast_baseline
        where local_day between %(start)s and %(end)s
        order by hour_utc
        """,
        {"start": start, "end": end},
    )


@st.cache_data(ttl=600)
def forecast_accuracy() -> pd.DataFrame:
    return query(
        """
        select date_trunc('month', local_day)::date as month,
               avg(mape_naive_168h_pct)::float as naive_168h, avg(mape_tso_pct)::float as tso,
               avg(mape_lgbm_pct)::float as lgbm
        from marts.mart_forecast_accuracy_daily group by 1 order by 1
        """
    )


@st.cache_data(ttl=120)
def recent_runs(limit: int = 20) -> pd.DataFrame:
    return query(
        """
        select job, runner, status, started_at,
               to_char(finished_at - started_at, 'MI:SS') as duration, details::text as details
        from ops.pipeline_runs order by run_id desc limit %(n)s
        """,
        {"n": limit},
    )


@st.cache_data(ttl=120)
def freshness() -> pd.DataFrame:
    return query(
        """
        select 'Energy-Charts generation' as dataset, max(local_day) as latest_day
        from marts.fct_generation_hourly where n_quarters = 4
        union all
        select 'Load (best source)', max(local_day) from marts.fct_load_hourly
        union all
        select 'Day-ahead price (ENTSO-E)', max(local_day) from marts.fct_price_hourly
        """
    )


@st.cache_data(ttl=600)
def backtest_summary() -> pd.DataFrame:
    return query(
        """
        select model, n_days, test_start, test_end, mape_pct::float as mape,
               mape_ci_low_pct::float as ci_low, mape_ci_high_pct::float as ci_high,
               dm_stat::float as dm_stat, dm_p_value::float as p_value
        from ml.backtest_metrics
        where run_id = (select max(run_id) from ml.backtest_metrics)
        order by mape_pct
        """
    )


def secret(name: str, default: str | None = None) -> str | None:
    """Streamlit secrets first (Community Cloud), then environment variables (VM)."""
    try:
        return st.secrets[name]
    except (FileNotFoundError, KeyError):
        return os.environ.get(name, default)


def database_url() -> str:
    return _database_url()


@st.cache_data(ttl=3600)
def cached_examples() -> pd.DataFrame:
    return query("select question, answer, sql, model, cost_usd from ops.agent_cache order by 1")


def chat_usage(client_hash: str) -> tuple[int, int]:
    """Questions asked today (all visitors) and in the last hour by this visitor."""
    df = query(
        """
        select count(*) filter (where asked_at >= date_trunc('day', now())) as today,
               count(*) filter (where asked_at >= now() - interval '1 hour'
                                  and client_hash = %(c)s) as mine
        from ops.agent_log where asked_at >= now() - interval '1 day'
        """,
        {"c": client_hash},
    )
    return int(df["today"].iloc[0]), int(df["mine"].iloc[0])


def log_question(row: dict) -> None:
    with psycopg.connect(_database_url(), connect_timeout=15) as conn:
        conn.read_only = False  # BEGIN READ WRITE: the role defaults to read-only
        conn.execute(
            """
            insert into ops.agent_log (client_hash, question, answer, model, escalated, ok,
                                       n_sql, cost_usd, seconds)
            values (%(client_hash)s, %(question)s, %(answer)s, %(model)s, %(escalated)s,
                    %(ok)s, %(n_sql)s, %(cost_usd)s, %(seconds)s)
            """,
            row,
        )


@st.cache_data(ttl=600)
def bulletin_text(day) -> dict | None:
    df = query("select source, content from ml.bulletins where local_day = %(d)s", {"d": day})
    return None if df.empty else {"source": df["source"].iloc[0], **df["content"].iloc[0]}
