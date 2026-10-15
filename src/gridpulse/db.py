import hashlib
from contextlib import contextmanager
from importlib import resources
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

UpsertResult = Literal["inserted", "updated", "unchanged"]


def _sql_files() -> list[str]:
    folder = resources.files("gridpulse") / "sql"
    files = sorted((f for f in folder.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)
    return [f.read_text(encoding="utf-8") for f in files]


def init_schema(conn: psycopg.Connection) -> None:
    with conn.transaction():
        for sql in _sql_files():
            conn.execute(sql)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_energy_charts_day(
    conn: psycopg.Connection,
    *,
    country: str,
    day,
    payload_json: str,
    n_intervals: int,
    is_complete: bool,
) -> UpsertResult:
    """Insert or update one raw day. Re-running with the same payload changes nothing."""
    row = conn.execute(
        """
        insert into raw.energy_charts_public_power
            (country, day, payload, n_intervals, is_complete, payload_sha256)
        values (%s, %s, %s::jsonb, %s, %s, %s)
        on conflict (country, day) do update set
            payload        = excluded.payload,
            n_intervals    = excluded.n_intervals,
            is_complete    = excluded.is_complete,
            payload_sha256 = excluded.payload_sha256,
            fetched_at     = now()
        where raw.energy_charts_public_power.payload_sha256 is distinct from excluded.payload_sha256
        returning (xmax = 0) as inserted
        """,
        (country, day, payload_json, n_intervals, is_complete, sha256(payload_json)),
    ).fetchone()
    if row is None:
        return "unchanged"
    return "inserted" if row[0] else "updated"


@contextmanager
def logged_run(database_url: str, job: str, runner: str):
    """Record a job in ops.pipeline_runs. Yields a dict the job can fill with details."""
    details: dict = {}
    with psycopg.connect(database_url, autocommit=True) as conn:
        (run_id,) = conn.execute(
            "insert into ops.pipeline_runs (job, runner) values (%s, %s) returning run_id",
            (job, runner),
        ).fetchone()
        status = "failed"
        try:
            yield details
            status = "success"
        except Exception as e:
            details["error"] = f"{type(e).__name__}: {e}"[:500]
            raise
        finally:
            conn.execute(
                "update ops.pipeline_runs set finished_at = now(), status = %s, details = %s"
                " where run_id = %s",
                (status, Jsonb(details), run_id),
            )


def upsert_entsoe_day(
    conn: psycopg.Connection, *, dataset: str, area: str, day, xml: str, points: list[dict]
) -> UpsertResult:
    row = conn.execute(
        """
        insert into raw.entsoe_documents
            (dataset, area, day, xml, points, n_points, payload_sha256)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (dataset, area, day) do update set
            xml            = excluded.xml,
            points         = excluded.points,
            n_points       = excluded.n_points,
            payload_sha256 = excluded.payload_sha256,
            fetched_at     = now()
        where raw.entsoe_documents.payload_sha256 is distinct from excluded.payload_sha256
        returning (xmax = 0) as inserted
        """,
        (dataset, area, day, xml, Jsonb(points), len(points), sha256(xml)),
    ).fetchone()
    if row is None:
        return "unchanged"
    return "inserted" if row[0] else "updated"


def upsert_open_meteo(conn: psycopg.Connection, rows, cities) -> int:
    """Bulk upsert via COPY into a temp table. Returns the number of rows inserted or changed."""
    conn.execute(
        "create temp table if not exists tmp_om"
        " (like raw.open_meteo_temperature including defaults) on commit drop"
    )
    with conn.cursor().copy(
        "copy tmp_om (city, hour_utc, temp_actual, temp_forecast_d1, temp_forecast_d2) from stdin"
    ) as copy:
        for r in rows:
            copy.write_row(
                (r.city, r.hour_utc, r.temp_actual, r.temp_forecast_d1, r.temp_forecast_d2)
            )
    cur = conn.execute(
        """
        insert into raw.open_meteo_temperature
            (city, hour_utc, temp_actual, temp_forecast_d1, temp_forecast_d2)
        select city, hour_utc, temp_actual, temp_forecast_d1, temp_forecast_d2 from tmp_om
        on conflict (city, hour_utc) do update set
            temp_actual      = excluded.temp_actual,
            temp_forecast_d1 = excluded.temp_forecast_d1,
            temp_forecast_d2 = excluded.temp_forecast_d2,
            fetched_at       = now()
        where (raw.open_meteo_temperature.temp_actual,
               raw.open_meteo_temperature.temp_forecast_d1,
               raw.open_meteo_temperature.temp_forecast_d2)
            is distinct from (excluded.temp_actual, excluded.temp_forecast_d1,
                              excluded.temp_forecast_d2)
        """
    )
    for c in cities:
        conn.execute(
            """
            insert into raw.open_meteo_cities (city, lat, lon, population) values (%s, %s, %s, %s)
            on conflict (city) do update set
                lat = excluded.lat, lon = excluded.lon, population = excluded.population
            """,
            (c.name, c.lat, c.lon, c.population),
        )
    return cur.rowcount
