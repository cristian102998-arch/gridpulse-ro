import streamlit as st

from data import bulletin_text, daily_kpis

st.title("Daily bulletin")
st.caption("What happened in Romania's power system on the last complete day.")

df = daily_kpis(8)
if df.empty:
    st.info("No complete day yet.")
    st.stop()

day, prev = df.iloc[0], df.iloc[1] if len(df) > 1 else None
label = f"{day.local_day:%A, %d %B %Y}"
if day.is_holiday:
    label += f" · public holiday ({day.holiday_name})"
if day.day_hours != 24:
    label += f" · {day.day_hours}-hour day (clock change)"
st.subheader(label)

text = bulletin_text(day.local_day)
if text:
    lang = st.radio(
        "Language", ["English", "Română"], horizontal=True, label_visibility="collapsed"
    )
    ro = lang == "Română"
    st.markdown(f"**{text['headline_ro'] if ro else text['headline_en']}**")
    for b in text["bullets_ro"] if ro else text["bullets_en"]:
        st.markdown(f"- {b}")
    written_by = (
        "Claude Haiku, checked against the data"
        if text["source"] != "template"
        else ("template (the AI draft failed the number check)")
    )
    st.caption(f"Written by {written_by}. Every number comes from SQL.")


def delta(col, fmt="{:+,.0f}"):
    if prev is None or prev[col] is None or day[col] is None:
        return None
    return fmt.format(float(day[col]) - float(prev[col]))


c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Consumption",
    f"{day.load_mwh / 1000:,.1f} GWh",
    delta("load_mwh"),
    delta_color="off",
    delta_arrow="off",
)
c2.metric(
    "Peak load",
    f"{day.peak_load_mw:,.0f} MW",
    f"at {day.peak_load_hour:%H:%M}",
    delta_color="off",
    delta_arrow="off",
)
c3.metric(
    "Renewable share", f"{day.renewable_share_pct:.0f}%", delta("renewable_share_pct", "{:+.1f} pp")
)
balance = day.generation_minus_load_mwh
c4.metric(
    "Net position",
    f"{abs(balance) / 1000:,.1f} GWh",
    "exporter" if balance > 0 else "importer",
    delta_color="normal" if balance > 0 else "inverse",
)

c5, c6 = st.columns(2)
if day.price_avg_eur_mwh is not None:
    c5.metric(
        "Day-ahead price (avg)",
        f"{day.price_avg_eur_mwh:,.2f} €/MWh",
        f"peak {day.price_max_eur_mwh:,.0f} € at {day.price_peak_hour:%H:%M}",
        delta_color="off",
        delta_arrow="off",
    )
else:
    c5.metric(
        "Day-ahead price",
        "pending",
        "ENTSO-E feed not connected yet",
        delta_color="off",
        delta_arrow="off",
    )
if day.tso_forecast_mape_pct is not None:
    c6.metric("TSO forecast error (MAPE)", f"{day.tso_forecast_mape_pct:.1f}%")
else:
    c6.metric(
        "TSO forecast error",
        "pending",
        "ENTSO-E feed not connected yet",
        delta_color="off",
        delta_arrow="off",
    )

st.divider()
st.caption("Last 7 days")
st.dataframe(
    df[
        [
            "local_day",
            "load_mwh",
            "peak_load_mw",
            "renewable_share_pct",
            "generation_minus_load_mwh",
        ]
    ]
    .head(7)
    .rename(
        columns={
            "local_day": "Day",
            "load_mwh": "Consumption (MWh)",
            "peak_load_mw": "Peak (MW)",
            "renewable_share_pct": "Renewables (%)",
            "generation_minus_load_mwh": "Generation − load (MWh)",
        }
    ),
    hide_index=True,
)
