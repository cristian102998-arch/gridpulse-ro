from datetime import timedelta

import altair as alt
import streamlit as st

from data import forecast_accuracy, latest_day, load_vs_forecasts

st.title("Load forecast")
st.caption(
    "Baseline first: the load one week earlier (seasonal naive). The LightGBM model and the "
    "Transelectrica (TSO) forecast are judged against it."
)

last = latest_day()
start, end = st.date_input("Days", value=(last - timedelta(days=6), last), max_value=last)
df = load_vs_forecasts(start, end)
long = df.melt("hour_local", var_name="series", value_name="mwh").dropna()
names = {"actual": "Actual", "naive_168h": "Naive (last week)", "tso": "TSO forecast"}
long["series"] = long["series"].map(names)
st.altair_chart(
    alt.Chart(long)
    .mark_line()
    .encode(
        x=alt.X("hour_local:T", title=None),
        y=alt.Y("mwh:Q", title="MWh per hour", scale=alt.Scale(zero=False)),
        color=alt.Color("series:N", title=None),
        strokeDash=alt.condition(
            alt.datum.series == "Actual", alt.value([1, 0]), alt.value([5, 3])
        ),
    )
    .properties(height=380),
    use_container_width=True,
)

acc = forecast_accuracy()
st.subheader("Monthly error (MAPE, lower is better)")
acc_long = acc.melt("month", var_name="series", value_name="mape").dropna()
acc_long["series"] = acc_long["series"].map(names)
st.altair_chart(
    alt.Chart(acc_long)
    .mark_line(point=True)
    .encode(
        x=alt.X("month:T", title=None),
        y=alt.Y("mape:Q", title="MAPE (%)"),
        color=alt.Color("series:N", title=None),
    )
    .properties(height=260),
    use_container_width=True,
)
