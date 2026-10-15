from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from data import freshness, recent_runs

st.title("Pipeline status")
st.caption(
    "Every job writes a row to ops.pipeline_runs, "
    "whether Airflow, GitHub Actions or a laptop ran it."
)

fr = freshness()
cols = st.columns(len(fr))
for col, row in zip(cols, fr.itertuples(), strict=True):
    if row.latest_day is None:
        col.metric(row.dataset, "no data yet")
        continue
    lag = (datetime.now(ZoneInfo("Europe/Bucharest")).date() - row.latest_day).days
    col.metric(
        row.dataset,
        f"{row.latest_day:%d %b}",
        f"{lag} day(s) behind",
        delta_color="off",
        delta_arrow="off",
    )

runs = recent_runs()
if runs.empty:
    st.info("No runs logged yet.")
else:
    ok = (runs["status"] == "success").mean()
    st.metric(
        "Recent success rate",
        f"{ok:.0%}",
        f"last {len(runs)} runs",
        delta_color="off",
        delta_arrow="off",
    )
    st.dataframe(runs, hide_index=True, width="stretch")
