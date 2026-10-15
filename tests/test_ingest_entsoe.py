from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from gridpulse.config import Settings
from gridpulse.db import init_schema
from gridpulse.ingest import ingest_entsoe
from gridpulse.sources import entsoe

pytestmark = pytest.mark.db

XML = (Path(__file__).parent / "fixtures" / "entsoe" / "load_actual.xml").read_text(
    encoding="utf-8"
)


@respx.mock
def test_entsoe_day_lands_once(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("gridpulse.ingest.ENTSOE_PAUSE_SECONDS", 0)
    init_schema(db_conn)
    db_conn.commit()
    route = respx.get(entsoe.BASE_URL).mock(return_value=httpx.Response(200, text=XML))
    settings = Settings(
        database_url=db_conn.info.dsn,
        raw_root=str(tmp_path),
        runner="test",
        entsoe_token="tok",
    )
    day = date(2025, 10, 26)

    assert ingest_entsoe(settings, day, day, dataset="load-actual") == {"inserted": 1}
    assert ingest_entsoe(settings, day, day, dataset="load-actual") == {"unchanged": 1}

    # The request covers the whole local day in UTC: 00:00 EEST (UTC+3) to 00:00 EET (UTC+2),
    # i.e. 25 hours on this date.
    params = route.calls.last.request.url.params
    assert (params["periodStart"], params["periodEnd"]) == ("202510252100", "202510262200")
    n_points, first = db_conn.execute(
        "select n_points, points->0->>'t' from raw.entsoe_documents"
    ).fetchone()
    assert (n_points, first) == (12, "2025-10-25T22:00:00+00:00")
    assert (tmp_path / "entsoe" / "load-actual" / "2025" / "10" / "26.json").exists()


def test_entsoe_needs_a_token(tmp_path):
    settings = Settings("postgresql://x", str(tmp_path), "test", entsoe_token=None)
    with pytest.raises(RuntimeError, match="ENTSOE_TOKEN"):
        ingest_entsoe(settings, date(2025, 1, 1), date(2025, 1, 1), dataset="price")
