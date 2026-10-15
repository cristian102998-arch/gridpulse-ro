"""Open-Meteo temperature forecasts as they were issued, via the Previous Runs API.

`temperature_2m_previous_day2` is the forecast for hour t from the model run 48 h before t.
That run is always out by the morning of D-1, when a day-ahead load forecast for day D is made,
so training on it cannot leak the future (lag-24 forecasts would, for the evening hours).
The same column exists for tomorrow, so training and serving use identical inputs.
Docs: https://open-meteo.com/en/docs/previous-runs-api (free, no key, CC BY 4.0).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

BASE_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com, CC BY 4.0"
VARIABLES = ("temperature_2m", "temperature_2m_previous_day1", "temperature_2m_previous_day2")


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    population: int  # 2021 census, used as weight


CITIES = (
    City("Bucuresti", 44.43, 26.10, 1_716_983),
    City("Cluj-Napoca", 46.77, 23.60, 286_598),
    City("Iasi", 47.16, 27.59, 271_692),
    City("Constanta", 44.18, 28.63, 263_688),
    City("Timisoara", 45.75, 21.23, 250_849),
    City("Brasov", 45.66, 25.61, 237_589),
    City("Craiova", 44.32, 23.80, 234_140),
    City("Galati", 45.44, 28.05, 217_851),
)


@dataclass(frozen=True)
class TemperatureRow:
    city: str
    hour_utc: datetime
    temp_actual: float | None
    temp_forecast_d1: float | None
    temp_forecast_d2: float | None


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
def fetch_temperatures(client: httpx.Client, start: date, end: date) -> list[TemperatureRow]:
    """Hourly rows for every city, UTC, inclusive of both dates."""
    resp = client.get(
        BASE_URL,
        params={
            "latitude": ",".join(str(c.lat) for c in CITIES),
            "longitude": ",".join(str(c.lon) for c in CITIES),
            "hourly": ",".join(VARIABLES),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "GMT",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    locations = body if isinstance(body, list) else [body]
    if len(locations) != len(CITIES):
        raise ValueError(f"expected {len(CITIES)} locations, got {len(locations)}")
    rows = []
    for city, loc in zip(CITIES, locations, strict=True):
        h = loc["hourly"]
        for i, t in enumerate(h["time"]):
            rows.append(
                TemperatureRow(
                    city=city.name,
                    hour_utc=datetime.fromisoformat(t).replace(tzinfo=UTC),
                    temp_actual=h["temperature_2m"][i],
                    temp_forecast_d1=h["temperature_2m_previous_day1"][i],
                    temp_forecast_d2=h["temperature_2m_previous_day2"][i],
                )
            )
    return rows
