import streamlit as st

st.set_page_config(page_title="GridPulse RO", page_icon="⚡", layout="wide")

pages = [
    st.Page("views/bulletin.py", title="Bulletin", icon="📰", default=True),
    st.Page("views/mix.py", title="Generation mix", icon="🔌"),
    st.Page("views/forecast.py", title="Forecast", icon="📈"),
    st.Page("views/status.py", title="Status", icon="🩺"),
]
st.navigation(pages).run()

st.sidebar.caption(
    "Data: [Energy-Charts.info](https://www.energy-charts.info/) (Fraunhofer ISE), "
    "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)."
)
