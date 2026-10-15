import json
import os
from pathlib import Path

import psycopg
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dst_day_payload() -> dict:
    """Real Energy-Charts response for RO on 2025-10-26 (a 25-hour day)."""
    return json.loads((FIXTURES / "energy_charts_public_power_ro_2025-10-26.json").read_text())


@pytest.fixture
def db_conn():
    # A separate database: this fixture drops the raw schema.
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    try:
        conn = psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres not reachable: {e}")
    with conn:
        for schema in ("raw", "ml", "ops"):
            conn.execute(f"drop schema if exists {schema} cascade")
        conn.commit()
        yield conn
