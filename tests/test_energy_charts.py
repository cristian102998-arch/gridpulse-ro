from datetime import date

import httpx
import pytest
import respx
from pydantic import ValidationError

from gridpulse.sources import energy_charts as ec
from gridpulse.timeutil import local_day_bounds

URL = f"{ec.BASE_URL}/public_power"


def test_parse_real_dst_day(dst_day_payload):
    resp = ec.PublicPowerResponse.model_validate(dst_day_payload)
    slices = ec.split_by_local_day(resp)
    assert [s.day for s in slices] == [date(2025, 10, 26)]
    s = slices[0]
    assert s.resolution_minutes == 15
    assert s.n_intervals == 100
    assert s.is_complete


def test_split_multi_day_response():
    # 14-15 Oct 2026 are normal 24 h days: 2 x 96 quarter-hours starting at local midnight.
    start, _ = local_day_bounds(date(2026, 10, 14))
    ts = [int(start.timestamp()) + 900 * i for i in range(192)]
    resp = ec.PublicPowerResponse(
        unix_seconds=ts, production_types=[ec.ProductionType(name="Solar", data=[1.0] * 192)]
    )
    slices = ec.split_by_local_day(resp)
    assert [s.day for s in slices] == [date(2026, 10, 14), date(2026, 10, 15)]
    assert all(s.n_intervals == 96 and s.is_complete for s in slices)


def test_partial_day_is_flagged():
    start, _ = local_day_bounds(date(2026, 10, 14))
    resp = ec.PublicPowerResponse(
        unix_seconds=[int(start.timestamp()) + 900 * i for i in range(40)], production_types=[]
    )
    (s,) = ec.split_by_local_day(resp)
    assert s.n_intervals == 40
    assert not s.is_complete


def test_rejects_mismatched_lengths():
    with pytest.raises(ValidationError):
        ec.PublicPowerResponse.model_validate(
            {"unix_seconds": [0, 900], "production_types": [{"name": "Solar", "data": [1.0]}]}
        )


def test_rejects_irregular_spacing():
    resp = ec.PublicPowerResponse(unix_seconds=[0, 900, 3600], production_types=[])
    with pytest.raises(ValueError, match="irregular"):
        ec.split_by_local_day(resp)


@respx.mock
def test_fetch_retries_on_server_error(dst_day_payload, monkeypatch):
    monkeypatch.setattr(ec.fetch_public_power.retry, "sleep", lambda _: None)
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=dst_day_payload)]
    )
    with httpx.Client() as client:
        resp = ec.fetch_public_power(client, "ro", date(2025, 10, 26), date(2025, 10, 26))
    assert route.call_count == 2
    assert len(resp.unix_seconds) == 100
    assert route.calls.last.request.url.params["start"] == "2025-10-26"


@respx.mock
def test_fetch_no_data_is_not_retried():
    route = respx.get(URL).mock(return_value=httpx.Response(400, text="no data"))
    with httpx.Client() as client, pytest.raises(ec.NoDataError):
        ec.fetch_public_power(client, "ro", date(2030, 1, 1), date(2030, 1, 1))
    assert route.call_count == 1
