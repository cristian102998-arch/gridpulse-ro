"""Ingestion jobs. Each one: fetch -> land raw file -> upsert into Postgres raw schema."""

import logging
from collections import Counter
from datetime import date

import httpx
import psycopg

from gridpulse import raw_store
from gridpulse.config import Settings
from gridpulse.db import upsert_energy_charts_day
from gridpulse.sources import energy_charts
from gridpulse.timeutil import date_chunks

log = logging.getLogger(__name__)

CHUNK_DAYS = 31  # one API call per month of backfill


def ingest_energy_charts_public_power(
    settings: Settings, start: date, end: date, country: str = "ro"
) -> Counter:
    stats: Counter = Counter()
    with (
        httpx.Client(timeout=60, headers={"User-Agent": "gridpulse-ro"}) as client,
        psycopg.connect(settings.database_url) as conn,
    ):
        for chunk_start, chunk_end in date_chunks(start, end, CHUNK_DAYS):
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
