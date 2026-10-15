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
