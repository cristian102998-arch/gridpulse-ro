"""Nightly logical backup of the tables that cannot be rebuilt.

Everything in `staging` and `marts` is rebuilt by dbt from `raw`, so only raw, ml and ops are
saved: one gzipped CSV per table under <root>/backups/YYYY-MM-DD/, plus a manifest with row
counts. The root is any fsspec URL: a local folder in dev, abfs://... (Azure Blob) in production.
Restore = recreate the schema with `gridpulse db init`, load the CSVs, run `dbt build`.
"""

import gzip
import json
import logging
from datetime import date

import fsspec
import psycopg

from gridpulse.db import init_schema

log = logging.getLogger(__name__)

TABLES = (
    "raw.energy_charts_public_power",
    "raw.entsoe_documents",
    "raw.open_meteo_cities",
    "raw.open_meteo_temperature",
    "ml.load_forecasts",
    "ml.backtest_metrics",
    "ml.backtest_predictions",
    "ops.pipeline_runs",
)


def _folder(root: str, day: date) -> str:
    return f"{root.rstrip('/')}/backups/{day.isoformat()}"


def prune_backups(root: str, today: date, keep_days: int) -> list[str]:
    """Delete backup folders older than keep_days. Returns the deleted dates."""
    fs, path = fsspec.core.url_to_fs(f"{root.rstrip('/')}/backups")
    if not fs.exists(path):
        return []
    deleted = []
    for entry in fs.ls(path, detail=False):
        name = entry.rstrip("/").rsplit("/", 1)[-1]
        try:
            age = (today - date.fromisoformat(name)).days
        except ValueError:
            continue  # not a backup folder
        if age > keep_days:
            fs.rm(entry, recursive=True)
            deleted.append(name)
    return sorted(deleted)


def run_backup(conn: psycopg.Connection, root: str, day: date) -> dict[str, int]:
    folder = _folder(root, day)
    counts: dict[str, int] = {}
    for table in TABLES:
        path = f"{folder}/{table}.csv.gz"
        sql = f"copy {table} to stdout with (format csv, header)"
        with (
            fsspec.open(path, "wb", auto_mkdir=True) as raw_f,
            gzip.open(raw_f, "wb") as f,
            conn.cursor().copy(sql) as copy,
        ):
            for chunk in copy:
                f.write(chunk)
        counts[table] = conn.execute(f"select count(*) from {table}").fetchone()[0]
        log.info("backed up %s (%d rows)", table, counts[table])
    with fsspec.open(f"{folder}/manifest.json", "w") as f:
        json.dump({"day": day.isoformat(), "row_counts": counts}, f, indent=2)
    return counts


def restore_backup(conn: psycopg.Connection, root: str, day: date) -> dict[str, int]:
    """Load a backup into an empty (or disposable) database. Existing rows are replaced."""
    folder = _folder(root, day)
    with fsspec.open(f"{folder}/manifest.json", "r") as f:
        expected = json.load(f)["row_counts"]
    init_schema(conn)
    restored: dict[str, int] = {}
    with conn.transaction():
        for table in reversed(TABLES):
            conn.execute(f"truncate {table}")
        for table in TABLES:
            # COPY writes identity values as given (like OVERRIDING SYSTEM VALUE), so run_ids
            # survive; the sequence is moved past them below.
            with (
                fsspec.open(f"{folder}/{table}.csv.gz", "rb") as raw_f,
                gzip.open(raw_f, "rb") as f,
            ):
                header = f.readline().decode().strip()
                sql = f"copy {table} ({header}) from stdin with (format csv)"
                with conn.cursor().copy(sql) as copy:
                    while chunk := f.read(1 << 20):
                        copy.write(chunk)
            restored[table] = conn.execute(f"select count(*) from {table}").fetchone()[0]
            if restored[table] != expected[table]:
                raise RuntimeError(
                    f"{table}: restored {restored[table]} rows, expected {expected[table]}"
                )
        conn.execute(
            "select setval(pg_get_serial_sequence('ops.pipeline_runs', 'run_id'),"
            " coalesce((select max(run_id) from ops.pipeline_runs), 1))"
        )
    return restored
