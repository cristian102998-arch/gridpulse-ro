from datetime import date

import pytest

from gridpulse.backup import TABLES, restore_backup, run_backup
from gridpulse.db import init_schema, logged_run

pytestmark = pytest.mark.db


def test_backup_then_restore_round_trip(db_conn, db_url, dst_day_payload, tmp_path):
    import json

    from gridpulse.db import upsert_energy_charts_day

    init_schema(db_conn)
    db_conn.commit()
    with db_conn.transaction():
        upsert_energy_charts_day(
            db_conn,
            country="ro",
            day=date(2025, 10, 26),
            payload_json=json.dumps(dst_day_payload),
            n_intervals=100,
            is_complete=True,
        )
    with logged_run(db_url, "test job", "test"):
        pass

    day = date(2026, 10, 15)
    counts = run_backup(db_conn, str(tmp_path), day)
    assert counts["raw.energy_charts_public_power"] == 1
    assert counts["ops.pipeline_runs"] == 1
    assert (tmp_path / "backups" / "2026-10-15" / "manifest.json").exists()

    # Wipe the data, then restore it.
    for table in reversed(TABLES):
        db_conn.execute(f"truncate {table}")
    db_conn.commit()
    restored = restore_backup(db_conn, str(tmp_path), day)
    assert restored == counts
    n = db_conn.execute(
        "select jsonb_array_length(payload->'unix_seconds') from raw.energy_charts_public_power"
    ).fetchone()[0]
    assert n == 100

    # The identity sequence moved past the restored run_id, so new runs do not collide.
    with logged_run(db_url, "after restore", "test"):
        pass
    db_conn.commit()
    assert (
        db_conn.execute("select count(distinct run_id) from ops.pipeline_runs").fetchone()[0] == 2
    )


def test_prune_keeps_recent_backups_only(tmp_path):
    from gridpulse.backup import prune_backups

    for name in ("2026-09-01", "2026-09-30", "2026-10-01", "2026-10-14", "not-a-date"):
        (tmp_path / "backups" / name).mkdir(parents=True)
    deleted = prune_backups(str(tmp_path), date(2026, 10, 15), keep_days=14)
    assert deleted == ["2026-09-01", "2026-09-30"]  # 10-01 is exactly 14 days old: kept
    left = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert left == ["2026-10-01", "2026-10-14", "not-a-date"]
