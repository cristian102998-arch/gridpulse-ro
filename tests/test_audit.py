import json
from datetime import UTC, date, datetime

import pytest

from gridpulse.db import init_schema, sha256, upsert_energy_charts_day

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


def _audit_rows(conn, table: str):
    return conn.execute(
        "select operation, row_key, changed_columns, old_row, new_row"
        " from ops.audit_log where table_name = %s order by id",
        (table,),
    ).fetchall()


def test_source_revision_is_logged_without_the_payload(db_conn, dst_day_payload):
    init_schema(db_conn)
    init_schema(db_conn)  # the trigger file must be safe to rerun

    _upsert(db_conn, dst_day_payload)
    _upsert(db_conn, dst_day_payload)  # unchanged: the upsert skips it, so no audit row
    assert _audit_rows(db_conn, "raw.energy_charts_public_power") == []

    revised = dict(dst_day_payload, deprecated=True)
    assert _upsert(db_conn, revised) == "updated"

    [(op, key, changed, old, new)] = _audit_rows(db_conn, "raw.energy_charts_public_power")
    assert op == "UPDATE"
    assert key == {"country": "ro", "day": "2025-10-26"}
    assert {"payload", "payload_sha256"} <= set(changed)
    assert "payload" not in old and "payload" not in new  # too large to copy
    assert old["payload_sha256"] == sha256(json.dumps(dst_day_payload))
    assert new["payload_sha256"] == sha256(json.dumps(revised))


def test_overwritten_forecast_keeps_the_first_prediction(db_conn):
    init_schema(db_conn)
    hour = datetime(2026, 11, 1, 10, tzinfo=UTC)
    upsert = """
        insert into ml.load_forecasts (hour_utc, model, model_version, prediction_mwh, issued_at)
        values (%s, 'lgbm', 'v1', %s, now())
        on conflict (hour_utc, model) do update set prediction_mwh = excluded.prediction_mwh
    """
    with db_conn.transaction():
        db_conn.execute(upsert, (hour, 6100.0))
        db_conn.execute(upsert, (hour, 6100.0))  # same value: nothing changed, nothing logged
        db_conn.execute(upsert, (hour, 6350.0))

    [(op, key, changed, old, new)] = _audit_rows(db_conn, "ml.load_forecasts")
    assert op == "UPDATE"
    assert key["model"] == "lgbm"
    assert changed == ["prediction_mwh"]
    assert old["prediction_mwh"] == 6100.0
    assert new["prediction_mwh"] == 6350.0


def test_delete_is_logged_with_the_old_row(db_conn, dst_day_payload):
    init_schema(db_conn)
    _upsert(db_conn, dst_day_payload)
    with db_conn.transaction():
        db_conn.execute("delete from raw.energy_charts_public_power where country = 'ro'")

    [(op, key, changed, old, new)] = _audit_rows(db_conn, "raw.energy_charts_public_power")
    assert op == "DELETE"
    assert key == {"country": "ro", "day": "2025-10-26"}
    assert changed is None and new is None
    assert old["n_intervals"] == len(dst_day_payload["unix_seconds"])


def test_truncate_does_not_flood_the_log(db_conn, dst_day_payload):
    # backup restore truncates every table before loading it
    init_schema(db_conn)
    _upsert(db_conn, dst_day_payload)
    with db_conn.transaction():
        db_conn.execute("truncate raw.energy_charts_public_power")
    assert _audit_rows(db_conn, "raw.energy_charts_public_power") == []
