import logging
import shlex
from datetime import date, timedelta
from functools import partial
from typing import Annotated

import psycopg
import typer

from gridpulse.alerts import send_alert
from gridpulse.config import get_settings, pg_env
from gridpulse.db import init_schema, logged_run
from gridpulse.ingest import (
    ingest_energy_charts_public_power,
    ingest_entsoe,
    ingest_open_meteo_temperature,
)
from gridpulse.sources.entsoe import DATASETS as ENTSOE_DATASETS
from gridpulse.timeutil import days_between, yesterday_local

app = typer.Typer(help="GridPulse RO command line.", no_args_is_help=True)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")
forecast_app = typer.Typer(help="Day-ahead load forecast.", no_args_is_help=True)
app.add_typer(forecast_app, name="forecast")
backup_app = typer.Typer(help="Backups of raw, ml and ops tables.", no_args_is_help=True)
app.add_typer(backup_app, name="backup")

JOBS = {
    ("energy-charts", "public-power"): ingest_energy_charts_public_power,
    ("open-meteo", "temperature"): ingest_open_meteo_temperature,
    **{
        ("entsoe", name): partial(ingest_entsoe, dataset=name)
        for name in ENTSOE_DATASETS  # load-actual, load-forecast, generation, price
    },
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


@db_app.command("env")
def db_env(
    shell: Annotated[bool, typer.Option(help="Print quoted `export` lines for eval")] = False,
) -> None:
    """Print DATABASE_URL as PGHOST=... lines (for dbt and $GITHUB_ENV)."""
    for key, value in pg_env(get_settings().database_url).items():
        typer.echo(f"export {key}={shlex.quote(value)}" if shell else f"{key}={value}")


@app.command()
def alert(message: str) -> None:
    """Send an alert (Telegram if configured, otherwise the log)."""
    send_alert(message)


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
    settings = get_settings()
    with logged_run(
        settings.database_url, f"ingest {source} {dataset}", settings.runner
    ) as details:
        stats = job(settings, start_day, end_day)
        details.update(start=str(start_day), end=str(end_day), **stats)
    typer.echo(" ".join(f"{k}={v}" for k, v in sorted(stats.items())) or "nothing to do")


@forecast_app.command("backtest")
def forecast_backtest(
    months: Annotated[int, typer.Option(help="Test months, walk-forward")] = 12,
) -> None:
    """Walk-forward backtest: LightGBM vs seasonal naive vs TSO, with CIs and DM tests."""
    from gridpulse.ml.forecast import as_table, run_backtest

    settings = get_settings()
    with (
        logged_run(settings.database_url, "forecast backtest", settings.runner) as details,
        psycopg.connect(settings.database_url) as conn,
    ):
        run_id, scores = run_backtest(conn, months)
        details.update(run_id=run_id, mape={s.model: round(s.mape, 3) for s in scores})
    typer.echo(f"run {run_id}")
    typer.echo(as_table(scores))


@forecast_app.command("predict")
def forecast_predict(
    start: Annotated[str | None, typer.Option(help="First local day. Default: tomorrow")] = None,
    end: Annotated[str | None, typer.Option(help="Last local day. Default: start")] = None,
) -> None:
    """Forecast every hour of each local day and store it in ml.load_forecasts.

    Each day gets a model trained only on data before that day, so a range of past days
    is an honest replay of what the live forecast would have said.
    """
    from gridpulse.ml.forecast import predict_day

    first = date.fromisoformat(start) if start else yesterday_local() + timedelta(days=2)
    last = date.fromisoformat(end) if end else first
    settings = get_settings()
    with (
        logged_run(settings.database_url, "forecast predict", settings.runner) as details,
        psycopg.connect(settings.database_url) as conn,
    ):
        for day in days_between(first, last):
            n = predict_day(conn, day)
            typer.echo(f"{day}: {n} hourly forecasts stored")
        details.update(start=str(first), end=str(last))


@backup_app.command("run")
def backup_run(
    root: Annotated[
        str | None, typer.Option(help="fsspec URL. Default: GRIDPULSE_BACKUP_ROOT")
    ] = None,
    keep_days: Annotated[int, typer.Option(help="Delete backups older than this")] = 14,
) -> None:
    """Write today's backup (gzipped CSV per table + manifest) and drop old ones."""
    from gridpulse.backup import prune_backups, run_backup

    settings = get_settings()
    target = root or settings.backup_root
    day = yesterday_local() + timedelta(days=1)
    with (
        logged_run(settings.database_url, "backup run", settings.runner) as details,
        psycopg.connect(settings.database_url) as conn,
    ):
        counts = run_backup(conn, target, day)
        pruned = prune_backups(target, day, keep_days)
        details.update(day=str(day), rows=sum(counts.values()), pruned=pruned)
    typer.echo(f"backup {day}: {sum(counts.values())} rows in {len(counts)} tables -> {target}")


@backup_app.command("restore")
def backup_restore(
    day: Annotated[str, typer.Argument(help="Backup date, YYYY-MM-DD")],
    root: Annotated[
        str | None, typer.Option(help="fsspec URL. Default: GRIDPULSE_BACKUP_ROOT")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm replacing the tables")] = False,
) -> None:
    """Replace raw, ml and ops in DATABASE_URL with a backup. Then run `dbt build`."""
    from gridpulse.backup import restore_backup

    if not yes:
        raise typer.BadParameter("restore replaces existing rows; pass --yes to confirm")
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        counts = restore_backup(conn, root or settings.backup_root, date.fromisoformat(day))
    typer.echo(f"restored {sum(counts.values())} rows; now run dbt build")
