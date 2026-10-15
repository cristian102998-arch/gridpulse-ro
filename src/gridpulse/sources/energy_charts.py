"""Energy-Charts public_power client (Fraunhofer ISE, CC BY 4.0).

API docs: https://api.energy-charts.info/
A date-only `start`/`end` is read by the API as a local (Europe/Bucharest for country=ro) day,
end inclusive. Requests for days with no data yet (e.g. the future) return HTTP 400.
"""

import logging
from dataclasses import dataclass
from datetime import date

import httpx
from pydantic import BaseModel, model_validator
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from gridpulse.timeutil import expected_intervals, local_day_of

log = logging.getLogger(__name__)

BASE_URL = "https://api.energy-charts.info"
ATTRIBUTION = "Data: Energy-Charts.info (Fraunhofer ISE), CC BY 4.0"


class NoDataError(Exception):
    """The API has no data for the requested range (HTTP 400/404)."""


class ProductionType(BaseModel):
    name: str
    data: list[float | None]


class PublicPowerResponse(BaseModel):
    unix_seconds: list[int]
    production_types: list[ProductionType]
    deprecated: bool = False

    @model_validator(mode="after")
    def _check_shape(self) -> "PublicPowerResponse":
        n = len(self.unix_seconds)
        for p in self.production_types:
            if len(p.data) != n:
                raise ValueError(f"{p.name}: {len(p.data)} values for {n} timestamps")
        if self.unix_seconds != sorted(set(self.unix_seconds)):
            raise ValueError("timestamps are not strictly increasing")
        return self


@dataclass(frozen=True)
class DaySlice:
    day: date
    payload: PublicPowerResponse
    resolution_minutes: int

    @property
    def n_intervals(self) -> int:
        return len(self.payload.unix_seconds)

    @property
    def is_complete(self) -> bool:
        return self.n_intervals == expected_intervals(self.day, self.resolution_minutes)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=30),
    reraise=True,
)
def fetch_public_power(
    client: httpx.Client, country: str, start: date, end: date
) -> PublicPowerResponse:
    resp = client.get(
        f"{BASE_URL}/public_power",
        params={"country": country, "start": start.isoformat(), "end": end.isoformat()},
    )
    if resp.status_code in (400, 404):
        raise NoDataError(f"{country} {start}..{end}: HTTP {resp.status_code} {resp.text[:100]}")
    resp.raise_for_status()
    return PublicPowerResponse.model_validate(resp.json())


def resolution_minutes(unix_seconds: list[int]) -> int:
    steps = {b - a for a, b in zip(unix_seconds, unix_seconds[1:], strict=False)}
    if len(steps) != 1:
        raise ValueError(f"irregular spacing between timestamps: {sorted(steps)[:5]}")
    return steps.pop() // 60


def split_by_local_day(resp: PublicPowerResponse) -> list[DaySlice]:
    """Cut a multi-day response into one slice per local Bucharest day."""
    if not resp.unix_seconds:
        return []
    res = resolution_minutes(resp.unix_seconds)
    by_day: dict[date, list[int]] = {}
    for i, ts in enumerate(resp.unix_seconds):
        by_day.setdefault(local_day_of(ts), []).append(i)
    slices = []
    for day, idx in by_day.items():
        part = PublicPowerResponse(
            unix_seconds=[resp.unix_seconds[i] for i in idx],
            production_types=[
                ProductionType(name=p.name, data=[p.data[i] for i in idx])
                for p in resp.production_types
            ],
            deprecated=resp.deprecated,
        )
        slices.append(DaySlice(day=day, payload=part, resolution_minutes=res))
    return slices
