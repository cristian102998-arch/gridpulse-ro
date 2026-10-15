import logging
from datetime import date
from typing import Annotated

import psycopg
import typer

from gridpulse.config import get_settings
from gridpulse.db import init_schema
from gridpulse.ingest import ingest_energy_charts_public_power
from gridpulse.timeutil import yesterday_local

app = typer.Typer(help="GridPulse RO command line.", no_args_is_help=True)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")

JOBS = {
    ("energy-charts", "public-power"): ingest_energy_charts_public_power,
}


def _parse_date(value: str | None) -> date:
    return yesterday_local() if value is None else date.fromisoformat(value)


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@db_app.command("init")
def db_init() -> None:
    """Create schemas and raw tables (idempotent)."""
    with psycopg.connect(get_settings().database_url) as conn:
        init_schema(conn)
    typer.echo("schema ok")


@app.command()
def ingest(
    source: Annotated[str, typer.Argument(help="e.g. energy-charts")],
    dataset: Annotated[str, typer.Argument(help="e.g. public-power")],
    start: Annotated[
        str | None, typer.Option(help="YYYY-MM-DD, local day. Default: yesterday")
    ] = None,
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD, inclusive. Default: start")] = None,
) -> None:
    """Fetch a dataset for [start, end] and load it into the raw layer. Safe to re-run."""
    job = JOBS.get((source, dataset))
    if job is None:
        known = ", ".join(f"{s} {d}" for s, d in JOBS)
        raise typer.BadParameter(f"unknown job '{source} {dataset}'. Known: {known}")
    start_day = _parse_date(start)
    end_day = _parse_date(end) if end else start_day
    stats = job(get_settings(), start_day, end_day)
    typer.echo(" ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "nothing to do")
