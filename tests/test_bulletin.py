from contextlib import contextmanager
from types import SimpleNamespace as NS

from gridpulse import bulletin
from gridpulse.bulletin import Bulletin, unsupported_numbers

FACTS = {
    "day": "2026-10-14",
    "weekday": "Wednesday",
    "holiday": None,
    "day_hours": 24,
    "consumption_mwh": 137324.0,
    "consumption_previous_day_mwh": 146383.0,
    "consumption_same_day_last_week_mwh": 140112.0,
    "peak_load_mw": 7058.0,
    "peak_load_time": "19:00",
    "renewable_share_pct": 67.6,
    "renewable_share_previous_day_pct": 64.6,
    "generation_minus_consumption_mwh": 11825.0,
    "top_sources_gwh": [{"source": "Wind", "gwh": 45.2}, {"source": "Gas", "gwh": 29.1}],
    "price_avg_eur_mwh": None,
    "price_max_eur_mwh": None,
    "forecast_error_lightgbm_pct": 3.1,
    "forecast_error_naive_pct": 6.9,
    "unusual_hours": [],
}


def test_numbers_from_the_facts_pass_rounded_or_converted():
    text = (
        "Pe 14 octombrie 2026 consumul a fost de 137,3 GWh, cu 9.059 MWh mai puțin decât ieri. "
        "Vârful a fost 7.058 MW la 19:00. Regenerabilele au acoperit 68% din producție; "
        "vântul a dat 45,2 GWh. România a exportat net 11,8 GWh. Prognoza a greșit cu 3,1%."
    )
    assert unsupported_numbers(text, FACTS) == []


def test_invented_numbers_are_caught():
    text = "Consumption was 152.4 GWh and the average price was 98 EUR/MWh."
    bad = unsupported_numbers(text, FACTS)
    assert 152.4 in bad and 98.0 in bad


def _parsed(b: Bulletin):
    return NS(
        parsed_output=b, stop_reason="end_turn", usage=NS(input_tokens=1500, output_tokens=400)
    )


GOOD = Bulletin(
    headline_ro="Consum 137,3 GWh, regenerabile 68%",
    headline_en="Consumption 137.3 GWh, renewables 68%",
    bullets_ro=["Vârful a fost 7.058 MW la 19:00."],
    bullets_en=["Peak load was 7,058 MW at 19:00."],
)
INVENTED = GOOD.model_copy(update={"bullets_en": ["Prices averaged 123 EUR/MWh."]})


class FakeConn:
    def __init__(self):
        self.rows = []

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params):
        self.rows.append(params)


def _run(monkeypatch, outputs):
    monkeypatch.setattr(bulletin, "gather_facts", lambda conn, day: FACTS)
    calls = []

    def parse(**kw):
        calls.append(kw)
        return _parsed(outputs[len(calls) - 1])

    conn = FakeConn()
    result = bulletin.generate(conn, None, client=NS(messages=NS(parse=parse)))
    return result, calls, conn


def test_good_bulletin_is_stored(monkeypatch):
    result, calls, conn = _run(monkeypatch, [GOOD])
    assert result["source"] == "claude-haiku-5-5"
    assert calls[0]["model"] == "claude-haiku-5-5"
    assert calls[0]["output_format"] is Bulletin
    assert len(conn.rows) == 1


def test_invented_number_triggers_retry_then_template(monkeypatch):
    result, calls, _ = _run(monkeypatch, [INVENTED, INVENTED])
    assert len(calls) == 2
    assert result["source"] == "template"
    assert "137.3 GWh" in result["headline_en"]


def test_retry_can_recover(monkeypatch):
    result, calls, _ = _run(monkeypatch, [INVENTED, GOOD])
    assert len(calls) == 2 and result["source"] == "claude-haiku-5-5"
