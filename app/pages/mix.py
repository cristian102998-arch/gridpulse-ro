from datetime import timedelta

import altair as alt
import streamlit as st

from data import generation_hourly, latest_day

st.title("Romania's power generation mix")

last = latest_day()
start, end = st.date_input(
    "Days (local time, Europe/Bucharest)",
    value=(last - timedelta(days=6), last),
    max_value=last,
)

df = generation_hourly(start, end)
if df.empty:
    st.info("No data for these days yet.")
    st.stop()

gen = df[df["source_label"] != "Battery (net)"]
total = gen["mwh"].sum()
renewable = gen.loc[gen["is_renewable"] == True, "mwh"].sum()  # noqa: E712 (nullable column)
by_source = gen.groupby("source_label")["mwh"].sum().sort_values(ascending=False)

c1, c2, c3 = st.columns(3)
c1.metric("Generation", f"{total / 1000:,.0f} GWh")
c2.metric("Renewable share", f"{renewable / total:.0%}")
c3.metric("Largest source", by_source.index[0], f"{by_source.iloc[0] / total:.0%} of total")

order = df.drop_duplicates("source_label").sort_values("display_order")["source_label"].tolist()
chart = (
    alt.Chart(df)
    .mark_area()
    .encode(
        x=alt.X("hour_local:T", title=None),
        y=alt.Y("mwh:Q", stack=True, title="MWh per hour"),
        color=alt.Color("source_label:N", sort=order, title="Source"),
        order=alt.Order("display_order:Q"),
        tooltip=["hour_local:T", "source_label:N", alt.Tooltip("mwh:Q", format=",.0f")],
    )
    .properties(height=420)
)
st.altair_chart(chart, use_container_width=True)
st.caption("Hourly averages of 15-minute values. Battery is net: negative while charging.")
