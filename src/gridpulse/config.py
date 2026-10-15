import os
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str
    raw_root: str
    runner: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://postgres@localhost:5432/gridpulse"
        ),
        # Any fsspec URL: a local folder now, abfs://raw@<account>.dfs.core.windows.net later.
        raw_root=os.environ.get("GRIDPULSE_RAW_ROOT", "data/raw"),
        runner=os.environ.get("GRIDPULSE_RUNNER", "local"),  # airflow | github | local
    )


def pg_env(database_url: str) -> dict[str, str]:
    """Split a postgresql:// URL into libpq variables. dbt reads these from profiles.yml."""
    u = urlsplit(database_url)
    env = {
        "PGHOST": u.hostname or "localhost",
        "PGPORT": str(u.port or 5432),
        "PGUSER": unquote(u.username or "postgres"),
        "PGDATABASE": u.path.lstrip("/") or "postgres",
    }
    if u.password:
        env["PGPASSWORD"] = unquote(u.password)
    sslmode = parse_qs(u.query).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = sslmode[0]
    return env
