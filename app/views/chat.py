import hashlib
import json
import os

import streamlit as st

from data import cached_examples, chat_usage, database_url, log_question, secret

st.title("Ask the data")
st.caption(
    "Questions in English or Romanian. Claude writes SQL against the warehouse on a read-only "
    "account; every query is checked before it runs. Questions are logged (without your IP) "
    "to improve the evaluation set."
)

DAILY_CAP = int(secret("AGENT_DAILY_CAP", "50"))
PER_HOUR = int(secret("AGENT_PER_CLIENT_HOURLY", "10"))


def client_hash() -> str:
    headers = st.context.headers
    ip = (headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    ip = ip or (st.context.ip_address or "unknown")
    salt = secret("AGENT_LOG_SALT", "gridpulse")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16]


def show(answer: str, sql: list | None, footer: str) -> None:
    st.markdown(answer)
    if sql:
        with st.expander("SQL"):
            for s in sql:
                st.code(s.get("sql") or "", language="sql")
                if s.get("error"):
                    st.caption(f"error: {s['error']}")
    st.caption(footer)


examples = cached_examples()
if not examples.empty:
    st.subheader("Examples (pre-computed, free)")
    cols = st.columns(2)
    for i, row in enumerate(examples.itertuples()):
        if cols[i % 2].button(row.question, key=f"ex{i}", width="stretch"):
            st.session_state["shown"] = row._asdict()

if shown := st.session_state.get("shown"):
    sql = shown["sql"] if isinstance(shown["sql"], list) else json.loads(shown["sql"] or "[]")
    with st.chat_message("assistant"):
        show(shown["answer"], sql, f"{shown['model']} · cached answer")

st.divider()

api_key_set = bool(secret("ANTHROPIC_API_KEY"))
if api_key_set and "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = secret("ANTHROPIC_API_KEY")

me = client_hash()
today, mine = chat_usage(me)
fallback = " Try the examples above." if not examples.empty else ""
if not api_key_set:
    st.info("Live questions are off on this deployment." + fallback)
elif today >= DAILY_CAP:
    st.warning(f"Today's limit of {DAILY_CAP} live questions is used up." + fallback)
elif mine >= PER_HOUR:
    st.warning(f"You have asked {PER_HOUR} questions in the last hour. Try again later.")
elif question := st.chat_input("e.g. How much wind power did Romania produce last week?"):
    from gridpulse.agent.core import ask

    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"), st.spinner("Querying the warehouse..."):
        result = ask(question[:500], database_url())
        show(
            result.answer,
            result.sql,
            f"{result.model}{' (escalated)' if result.escalated else ''} · "
            f"{result.seconds:.1f}s · ${result.usage.cost_usd:.4f}",
        )
    log_question(
        {
            "client_hash": me,
            "question": question[:500],
            "answer": result.answer,
            "model": result.model,
            "escalated": result.escalated,
            "ok": result.ok,
            "n_sql": len(result.sql),
            "cost_usd": result.usage.cost_usd,
            "seconds": result.seconds,
        }
    )
    st.caption(f"{DAILY_CAP - today - 1} live questions left today for everyone.")
