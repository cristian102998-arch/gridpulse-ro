"""DAG import test. Runs in the CI `dags` job, where Airflow is installed; skipped elsewhere."""

from pathlib import Path

import pytest

airflow = pytest.importorskip("airflow")

DAGS = Path(__file__).resolve().parents[1] / "dags"


def test_dags_import_without_errors():
    from airflow.models import DagBag

    bag = DagBag(dag_folder=str(DAGS), include_examples=False)
    assert bag.import_errors == {}
    dag = bag.get_dag("gridpulse_daily")
    assert dag is not None
    assert {t.task_id for t in dag.tasks} == {
        "db_init",
        "ingest_energy_charts",
        "dbt_build",
        "source_freshness",
        "alert_on_failure",
    }
    alert = dag.get_task("alert_on_failure")
    assert alert.trigger_rule == "one_failed"
