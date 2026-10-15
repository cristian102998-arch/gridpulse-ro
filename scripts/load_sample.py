"""Load the fixture files into the raw layer, so CI can run `dbt build` without calling any API.

Usage: uv run python scripts/load_sample.py
"""

import json
from pathlib import Path

import psycopg

from gridpulse.config import get_settings
from gridpulse.db import init_schema, upsert_energy_charts_day
from gridpulse.sources.energy_charts import PublicPowerResponse, split_by_local_day

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    with psycopg.connect(get_settings().database_url) as conn:
        init_schema(conn)
        for path in sorted(FIXTURES.glob("energy_charts_public_power_*.json")):
            country = path.stem.split("_")[-2]
            resp = PublicPowerResponse.model_validate(json.loads(path.read_text()))
            for s in split_by_local_day(resp):
                with conn.transaction():
                    result = upsert_energy_charts_day(
                        conn,
                        country=country,
                        day=s.day,
                        payload_json=s.payload.model_dump_json(),
                        n_intervals=s.n_intervals,
                        is_complete=s.is_complete,
                    )
                print(f"{path.name}: {s.day} {result}")


if __name__ == "__main__":
    main()
