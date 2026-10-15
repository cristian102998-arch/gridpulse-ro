"""The morning bulletin: SQL computes every number, Claude Haiku turns them into short prose.

Guardrail: every number in the generated text must match one of the facts (or a date or
clock time). Otherwise the bulletin is regenerated once, then replaced by a fixed template.
"""

import json
import logging
import os
import re
from datetime import date, datetime

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from gridpulse.agent.evaluate import number_candidates

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"

SYSTEM = """You write the morning bulletin of Romania's power system for energy analysts.
You get a JSON object of facts computed from the data. Write only from those facts:
every number you write must appear in the facts (you may round it, or convert MWh to GWh).
Short, plain sentences. No adjectives like "remarkable". Mention a holiday or a clock change
if the facts say so. Romanian with diacritics for the _ro fields, English for the _en fields."""


class Bulletin(BaseModel):
    headline_ro: str = Field(description="One line, at most 90 characters.")
    headline_en: str = Field(description="The same headline in English.")
    bullets_ro: list[str] = Field(description="3 to 5 short sentences in Romanian.")
    bullets_en: list[str] = Field(description="The same sentences in English.")


def gather_facts(conn: psycopg.Connection, day: date) -> dict:
    def one(sql: str, *params):
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(zip([c.name for c in cur.description], row, strict=True)) if row else None

    kpi = one("select * from marts.mart_daily_kpis where local_day = %s", day)
    if kpi is None:
        raise LookupError(f"no daily KPIs for {day} yet")
    prev = (
        one(
            "select load_mwh, renewable_share_pct from marts.mart_daily_kpis where local_day = %s",
            day.fromordinal(day.toordinal() - 1),
        )
        or {}
    )
    week_ago = (
        one(
            "select load_mwh from marts.mart_daily_kpis where local_day = %s",
            day.fromordinal(day.toordinal() - 7),
        )
        or {}
    )
    mix = conn.execute(
        """
        select s.source_label, round(sum(f.generation_mwh) / 1000, 1) as gwh
        from marts.fct_generation_hourly f join marts.dim_source s using (source_code)
        where f.local_day = %s and s.category = 'generation'
        group by 1 having sum(f.generation_mwh) is not null order by 2 desc limit 4
        """,
        (day,),
    ).fetchall()
    anomalies = conn.execute(
        """
        select to_char(hour_local, 'HH24:MI') as hour, round(residual_mwh) as residual_mwh
        from marts.fct_load_anomalies where local_day = %s and is_anomaly
        order by abs(robust_z) desc limit 3
        """,
        (day,),
    ).fetchall()
    forecast = (
        one(
            "select mape_lgbm_pct, mape_naive_168h_pct from marts.mart_forecast_accuracy_daily "
            "where local_day = %s",
            day,
        )
        or {}
    )

    def num(v):
        return float(v) if v is not None else None

    return {
        "day": day.isoformat(),
        "weekday": day.strftime("%A"),
        "holiday": kpi["holiday_name"],
        "day_hours": kpi["day_hours"],
        "consumption_mwh": num(kpi["load_mwh"]),
        "consumption_previous_day_mwh": num(prev.get("load_mwh")),
        "consumption_same_day_last_week_mwh": num(week_ago.get("load_mwh")),
        "peak_load_mw": num(kpi["peak_load_mw"]),
        "peak_load_time": kpi["peak_load_hour"].strftime("%H:%M"),
        "renewable_share_pct": num(kpi["renewable_share_pct"]),
        "renewable_share_previous_day_pct": num(prev.get("renewable_share_pct")),
        "generation_minus_consumption_mwh": num(kpi["generation_minus_load_mwh"]),
        "top_sources_gwh": [{"source": s, "gwh": float(g)} for s, g in mix],
        "price_avg_eur_mwh": num(kpi["price_avg_eur_mwh"]),
        "price_max_eur_mwh": num(kpi["price_max_eur_mwh"]),
        "forecast_error_lightgbm_pct": num(forecast.get("mape_lgbm_pct")),
        "forecast_error_naive_pct": num(forecast.get("mape_naive_168h_pct")),
        "unusual_hours": [{"time": h, "load_minus_forecast_mwh": float(r)} for h, r in anomalies],
    }


def _fact_numbers(facts: dict) -> list[float]:
    out: list[float] = []

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, int | float):
            out.extend([float(v), abs(float(v))])
        elif isinstance(v, str):
            out.extend(number_candidates(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(facts)
    # Differences the model may reasonably state.
    pairs = [
        ("consumption_mwh", "consumption_previous_day_mwh"),
        ("consumption_mwh", "consumption_same_day_last_week_mwh"),
        ("renewable_share_pct", "renewable_share_previous_day_pct"),
    ]
    for a, b in pairs:
        if facts.get(a) is not None and facts.get(b):
            out.append(abs(facts[a] - facts[b]))
            out.append(abs(facts[a] - facts[b]) / facts[b] * 100)
    return out


def unsupported_numbers(text: str, facts: dict) -> list[float]:
    """Numbers in `text` that match no fact (dates and clock times are allowed)."""
    known = _fact_numbers(facts)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)  # clock times
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", cleaned)  # ISO dates
    day = datetime.fromisoformat(facts["day"])
    allowed = {float(day.day), float(day.year), float(day.month), 24.0, 23.0, 25.0, 1.0, 7.0}
    bad = []
    for raw in re.findall(r"-?\d[\d.,]*\d|-?\d", cleaned):
        readings = number_candidates(raw)
        ok = any(
            r in allowed
            # same unit: allow rounding
            or any(abs(r - k) <= max(0.01 * abs(k), 0.51) for k in known)
            # MWh <-> GWh: relative match only, so small numbers cannot hide near zero
            or any(k and abs(r * f - k) <= 0.01 * abs(k) for k in known for f in (1000, 0.001))
            for r in readings
        )
        if not ok:
            bad.append(min(readings) if readings else raw)
    return bad


def template(facts: dict) -> Bulletin:
    gwh = facts["consumption_mwh"] / 1000
    share = facts["renewable_share_pct"]
    peak = facts["peak_load_mw"]
    t = facts["peak_load_time"]
    return Bulletin(
        headline_ro=f"Consum {gwh:.1f} GWh, regenerabile {share:.0f}%",
        headline_en=f"Consumption {gwh:.1f} GWh, renewables {share:.0f}%",
        bullets_ro=[
            f"Consumul a fost de {gwh:.1f} GWh, cu vârful de {peak:.0f} MW la ora {t}.",
            f"Regenerabilele au acoperit {share:.1f}% din producție.",
        ],
        bullets_en=[
            f"Consumption was {gwh:.1f} GWh, peaking at {peak:.0f} MW at {t}.",
            f"Renewables supplied {share:.1f}% of generation.",
        ],
    )


def generate(conn: psycopg.Connection, day: date, client=None) -> dict:
    facts = gather_facts(conn, day)
    cost = 0.0
    bulletin, source = None, "template"
    attempts = 2
    if client is None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            client = anthropic.Anthropic()
        else:
            log.warning("ANTHROPIC_API_KEY not set: writing the template bulletin")
            attempts = 0
    for _attempt in range(attempts):
        response = client.messages.parse(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
            output_format=Bulletin,
        )
        u = response.usage
        cost += (u.input_tokens * 0.10 + u.output_tokens * 0.50) / 1_000_000
        if response.stop_reason == "refusal" or response.parsed_output is None:
            continue
        candidate = response.parsed_output
        text = " ".join(
            [
                candidate.headline_ro,
                candidate.headline_en,
                *candidate.bullets_ro,
                *candidate.bullets_en,
            ]
        )
        bad = unsupported_numbers(text, facts)
        if not bad:
            bulletin, source = candidate, MODEL
            break
        log.warning("bulletin %s: numbers not in the facts %s, retrying", day, bad)
    bulletin = bulletin or template(facts)
    with conn.transaction():
        conn.execute(
            """
            insert into ml.bulletins (local_day, source, content, facts, cost_usd)
            values (%s, %s, %s, %s, %s)
            on conflict (local_day) do update set source = excluded.source,
                content = excluded.content, facts = excluded.facts,
                cost_usd = excluded.cost_usd, created_at = now()
            """,
            (day, source, Jsonb(bulletin.model_dump()), Jsonb(facts), cost),
        )
    return {"source": source, "cost_usd": cost, **bulletin.model_dump()}
