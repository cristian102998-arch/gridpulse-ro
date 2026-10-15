import json
from datetime import date

import pytest

from gridpulse.db import init_schema, upsert_energy_charts_day

pytestmark = pytest.mark.db


def _upsert(conn, payload: dict):
    with conn.transaction():
        return upsert_energy_charts_day(
            conn,
            country="ro",
            day=date(2025, 10, 26),
            payload_json=json.dumps(payload),
            n_intervals=len(payload["unix_seconds"]),
            is_complete=True,
        )


def test_upsert_is_idempotent(db_conn, dst_day_payload):
    init_schema(db_conn)
    init_schema(db_conn)  # running twice must be safe

    assert _upsert(db_conn, dst_day_payload) == "inserted"
    assert _upsert(db_conn, dst_day_payload) == "unchanged"

    revised = dict(dst_day_payload, deprecated=True)
    assert _upsert(db_conn, revised) == "updated"

    count, n = db_conn.execute(
        "select count(*), max(jsonb_array_length(payload->'unix_seconds'))"
        " from raw.energy_charts_public_power"
    ).fetchone()
    assert (count, n) == (1, 100)
