import hashlib
from importlib import resources
from typing import Literal

import psycopg

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
