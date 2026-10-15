"""ENTSO-E Transparency Platform client (RESTful API, XML responses).

Docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
All API times are UTC, formatted yyyyMMddHHmm. Romania's EIC code is 10YRO-TEL------P.
"""

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

BASE_URL = "https://web-api.tp.entsoe.eu/api"
RO = "10YRO-TEL------P"


@dataclass(frozen=True)
class Dataset:
    name: str
    params: dict[str, str]
    domain_params: tuple[str, ...]


DATASETS = {
    "load-actual": Dataset(
        "load-actual", {"documentType": "A65", "processType": "A16"}, ("outBiddingZone_Domain",)
    ),
    "load-forecast": Dataset(
        "load-forecast", {"documentType": "A65", "processType": "A01"}, ("outBiddingZone_Domain",)
    ),
    "generation": Dataset(
        "generation", {"documentType": "A75", "processType": "A16"}, ("in_Domain",)
    ),
    "price": Dataset(
        "price",
        {"documentType": "A44", "contract_MarketAgreement.type": "A01"},
        ("in_Domain", "out_Domain"),
    ),
}

RESOLUTIONS = {"PT15M": 15, "PT30M": 30, "PT60M": 60}


class NoDataError(Exception):
    """ENTSO-E answered with an Acknowledgement document (usually reason 999: no matching data)."""


class EntsoeError(Exception):
    pass


@dataclass(frozen=True)
class Point:
    series: str  # "total" for load/price, the psrType (B01..B20) for generation
    is_consumption: bool  # True for generation-type series that draw power (pumping, charging)
    interval_start_utc: datetime
    resolution_minutes: int
    value: float


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _tag(c) == name), None)


def _find_all(el: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in el.iter() if _tag(e) == name]


def _text(el: ET.Element | None, path: str) -> str | None:
    for name in path.split("/"):
        if el is None:
            return None
        el = _child(el, name)
    return el.text if el is not None else None


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)


def parse_document(xml: str) -> list[Point]:
    """Turn any GL_MarketDocument / Publication_MarketDocument into flat points.

    Handles both curve types: A01 (every position present) and A03 (a missing position
    repeats the previous value, used by ENTSO-E for prices and some generation series).
    """
    root = ET.fromstring(xml)
    if _tag(root) == "Acknowledgement_MarketDocument":
        reason = _text(root, "Reason/text") or _text(root, "Reason/code")
        raise NoDataError(reason or "acknowledgement without reason")

    points: list[Point] = []
    for ts in _find_all(root, "TimeSeries"):
        psr = _text(ts, "MktPSRType/psrType") or "total"
        # In A75 documents, series that consume (pumping, charging) carry outBiddingZone.
        has_out_zone = _child(ts, "outBiddingZone_Domain.mRID") is not None
        is_consumption = psr != "total" and has_out_zone
        for period in (p for p in ts if _tag(p) == "Period"):
            start = _parse_time(_text(period, "timeInterval/start"))
            end = _parse_time(_text(period, "timeInterval/end"))
            res = RESOLUTIONS[_text(period, "resolution")]
            step = timedelta(minutes=res)
            n_positions = int((end - start) / step)
            by_pos: dict[int, float] = {}
            for pt in (p for p in period if _tag(p) == "Point"):
                raw = _text(pt, "quantity") or _text(pt, "price.amount")
                by_pos[int(_text(pt, "position"))] = float(raw)
            last = None
            for pos in range(1, n_positions + 1):
                value = by_pos.get(pos, last)  # A03: carry the previous value forward
                if value is None:
                    continue
                last = value
                points.append(Point(psr, is_consumption, start + (pos - 1) * step, res, value))
    return points


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=5, max=120),
    reraise=True,
)
def fetch(
    client: httpx.Client, token: str, dataset: str, start: datetime, end: datetime, area: str = RO
) -> str:
    """Return the raw XML for [start, end). Raises NoDataError when ENTSO-E has nothing."""
    ds = DATASETS[dataset]
    params = {
        "securityToken": token,
        **ds.params,
        **{p: area for p in ds.domain_params},
        "periodStart": _fmt(start),
        "periodEnd": _fmt(end),
    }
    resp = client.get(BASE_URL, params=params)
    if resp.status_code == 400 and "Acknowledgement_MarketDocument" in resp.text:
        parse_document(resp.text)  # raises NoDataError with ENTSO-E's reason
    if resp.status_code == 401:
        raise EntsoeError("ENTSO-E rejected the token (HTTP 401)")
    resp.raise_for_status()
    return resp.text
