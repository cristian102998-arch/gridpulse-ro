"""DAG import test. Runs in the CI `dags` job, where Airflow is installed; skipped elsewhere."""

import os
from pathlib import Path

import pytest

# Airflow 3 dropped DagBag(include_examples=...); the example DAGs are switched off here instead.
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "false")
airflow = pytest.importorskip("airflow")

DAGS = Path(__file__).resolve().parents[1] / "dags"


@pytest.fixture(scope="module")
def bag():
    from airflow.models import DagBag

    return DagBag(dag_folder=str(DAGS))


def test_dags_import_without_errors(bag):
    assert bag.import_errors == {}
    assert set(bag.dag_ids) == {
        "gridpulse_daily",
        "gridpulse_backtest_monthly",
        "gridpulse_backup_nightly",
    }


def test_daily_dag_tasks(bag):
    dag = bag.dags["gridpulse_daily"]  # get_dag() would also query the metadata database
    assert {t.task_id for t in dag.tasks} == {
        "db_init",
        "ingest_energy_charts",
        "ingest_open_meteo",
        "dbt_build",
        "forecast_tomorrow",
        "dbt_forecast_marts",
        "bulletin",
        "source_freshness",
        "alert_on_failure",
    }
    assert dag.get_task("alert_on_failure").trigger_rule == "one_failed"
    assert dag.get_task("forecast_tomorrow").upstream_task_ids == {"dbt_build"}
