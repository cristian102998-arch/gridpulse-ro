from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from gridpulse.sources import entsoe

FIX = Path(__file__).parent / "fixtures" / "entsoe"


def _xml(name: str) -> str:
    return (FIX / f"{name}.xml").read_text(encoding="utf-8")


def test_parse_load_quarter_hours():
    points = entsoe.parse_document(_xml("load_actual"))
    assert len(points) == 12
    assert points[0].interval_start_utc == datetime(2025, 10, 25, 22, 0, tzinfo=UTC)
    assert points[0].resolution_minutes == 15
    assert {p.series for p in points} == {"total"}
    assert points[-1].value == 5110


def test_parse_generation_separates_consumption():
    points = entsoe.parse_document(_xml("generation"))
    produced = [p.value for p in points if not p.is_consumption]
    pumped = [p.value for p in points if p.is_consumption]
    assert produced == [120, 130, 140, 150]
    assert pumped == [0, 0, 40, 40]
    assert {p.series for p in points} == {"B10"}


def test_parse_price_fills_a03_gaps():
    points = entsoe.parse_document(_xml("price"))
    assert [p.value for p in points] == [95.5, 95.5, 95.5, 101.2]


def test_acknowledgement_means_no_data():
    with pytest.raises(entsoe.NoDataError, match="No matching data"):
        entsoe.parse_document(_xml("acknowledgement"))


@respx.mock
def test_fetch_builds_query_in_utc():
    route = respx.get(entsoe.BASE_URL).mock(return_value=httpx.Response(200, text="<x/>"))
    start = datetime(2025, 10, 25, 22, 0, tzinfo=UTC)
    end = datetime(2025, 10, 26, 23, 0, tzinfo=UTC)
    with httpx.Client() as client:
        entsoe.fetch(client, "tok", "price", start, end)
    params = route.calls.last.request.url.params
    assert params["documentType"] == "A44"
    assert params["in_Domain"] == params["out_Domain"] == entsoe.RO
    assert (params["periodStart"], params["periodEnd"]) == ("202510252200", "202510262300")


@respx.mock
def test_fetch_no_data_on_400_acknowledgement():
    respx.get(entsoe.BASE_URL).mock(return_value=httpx.Response(400, text=_xml("acknowledgement")))
    with httpx.Client() as client, pytest.raises(entsoe.NoDataError):
        entsoe.fetch(
            client,
            "tok",
            "price",
            datetime(2030, 1, 1, tzinfo=UTC),
            datetime(2030, 1, 2, tzinfo=UTC),
        )
