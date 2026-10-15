import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    raw_root: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://postgres@localhost:5432/gridpulse"
        ),
        # Any fsspec URL: a local folder now, abfs://raw@<account>.dfs.core.windows.net later.
        raw_root=os.environ.get("GRIDPULSE_RAW_ROOT", "data/raw"),
    )
