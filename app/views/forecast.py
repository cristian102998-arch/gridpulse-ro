from datetime import timedelta

import altair as alt
import streamlit as st

from data import backtest_summary, forecast_accuracy, latest_day, load_vs_forecasts

st.title("Load forecast")
st.caption(
    "Day-ahead forecast of national load, made with what is known on the morning of the day "
    "before. Baseline: the load one week earlier. Past days show out-of-sample backtest "
    "predictions; tomorrow shows the live forecast."
)

bt = backtest_summary()
if not bt.empty:
    names_bt = {"lgbm": "LightGBM", "naive_168h": "Naive (last week)", "tso": "TSO forecast"}
    first = bt.iloc[0]
    st.subheader(
        f"Walk-forward backtest, {first.test_start:%b %Y} – {first.test_end:%b %Y} "
        f"({first.n_days} days)"
    )
    cols = st.columns(len(bt))
    for col, r in zip(cols, bt.itertuples(), strict=True):
        note = f"95% CI {r.ci_low:.2f}–{r.ci_high:.2f}%"
        if r.p_value is not None:
            p = f"p={r.p_value:.4f}" if r.p_value >= 0.0001 else "p<0.0001"
            note += f" · vs LightGBM: DM {p}"
        col.metric(
            names_bt.get(r.model, r.model),
            f"{r.mape:.2f}% MAPE",
            note,
            delta_color="off",
            delta_arrow="off",
        )
    st.caption(
        "MAPE = mean absolute percentage error. The CI resamples whole weeks (block bootstrap); "
        "the Diebold-Mariano test asks whether LightGBM's lower error could be luck."
    )
    st.divider()

last = latest_day()
tomorrow = last + timedelta(days=2)
start, end = st.date_input("Days", value=(last - timedelta(days=5), tomorrow), max_value=tomorrow)
df = load_vs_forecasts(start, end)
long = df.melt("hour_local", var_name="series", value_name="mwh").dropna()
names = {
    "actual": "Actual",
    "naive_168h": "Naive (last week)",
    "tso": "TSO forecast",
    "lgbm": "LightGBM",
}
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
    width="stretch",
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
    width="stretch",
)
