"""Ingestion jobs. Each one: fetch -> land raw file -> upsert into Postgres raw schema."""

import logging
import time
from collections import Counter
from datetime import date

import httpx
import psycopg

from gridpulse import raw_store
from gridpulse.config import Settings
from gridpulse.db import upsert_energy_charts_day, upsert_entsoe_day
from gridpulse.sources import energy_charts, entsoe
from gridpulse.timeutil import date_chunks, days_between, local_day_bounds

log = logging.getLogger(__name__)

CHUNK_DAYS = 31  # one API call per month of backfill
PAUSE_SECONDS = 3.0  # Energy-Charts answers 429 after ~20 quick calls


def ingest_energy_charts_public_power(
    settings: Settings, start: date, end: date, country: str = "ro"
) -> Counter:
    stats: Counter = Counter()
    with (
        httpx.Client(timeout=60, headers={"User-Agent": "gridpulse-ro"}) as client,
        psycopg.connect(settings.database_url) as conn,
    ):
        for i, (chunk_start, chunk_end) in enumerate(date_chunks(start, end, CHUNK_DAYS)):
            if i:
                time.sleep(PAUSE_SECONDS)
            try:
                resp = energy_charts.fetch_public_power(client, country, chunk_start, chunk_end)
            except energy_charts.NoDataError as e:
                log.warning("no data: %s", e)
                stats["no_data_chunks"] += 1
                continue
            for s in energy_charts.split_by_local_day(resp):
                if not chunk_start <= s.day <= chunk_end:
                    continue
                body = s.payload.model_dump_json()
                raw_store.write_raw(settings.raw_root, "energy_charts", "public_power", s.day, body)
                with conn.transaction():
                    result = upsert_energy_charts_day(
                        conn,
                        country=country,
                        day=s.day,
                        payload_json=body,
                        n_intervals=s.n_intervals,
                        is_complete=s.is_complete,
                    )
                stats[result] += 1
                if not s.is_complete:
                    stats["incomplete_days"] += 1
                    log.warning("%s: incomplete day, %d intervals", s.day, s.n_intervals)
    return stats


ENTSOE_PAUSE_SECONDS = 0.3  # ENTSO-E allows 400 requests/minute per token


def ingest_entsoe(settings: Settings, start: date, end: date, dataset: str) -> Counter:
    """One request per local day, so each raw row covers exactly that day (23/24/25 h)."""
    if not settings.entsoe_token:
        raise RuntimeError("ENTSOE_TOKEN is not set (see de-facut.md, step 1)")
    stats: Counter = Counter()
    with (
        httpx.Client(timeout=60, headers={"User-Agent": "gridpulse-ro"}) as client,
        psycopg.connect(settings.database_url) as conn,
    ):
        for i, day in enumerate(days_between(start, end)):
            if i:
                time.sleep(ENTSOE_PAUSE_SECONDS)
            day_start, day_end = local_day_bounds(day)
            try:
                xml = entsoe.fetch(client, settings.entsoe_token, dataset, day_start, day_end)
                points = entsoe.parse_document(xml)
            except entsoe.NoDataError as e:
                log.warning("%s %s: no data (%s)", dataset, day, e)
                stats["no_data_days"] += 1
                continue
            raw_store.write_raw(settings.raw_root, "entsoe", dataset, day, xml)
            rows = [
                {
                    "series": p.series,
                    "is_consumption": p.is_consumption,
                    "t": p.interval_start_utc.isoformat(),
                    "res": p.resolution_minutes,
                    "v": p.value,
                }
                for p in points
                if day_start <= p.interval_start_utc < day_end
            ]
            with conn.transaction():
                result = upsert_entsoe_day(
                    conn, dataset=dataset, area=entsoe.RO, day=day, xml=xml, points=rows
                )
            stats[result] += 1
    return stats
