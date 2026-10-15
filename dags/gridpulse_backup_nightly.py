"""Nightly backup of raw, ml and ops to Azure Blob (GRIDPULSE_BACKUP_ROOT), keeping 14 days.
Staging and marts are not backed up: `dbt build` recreates them from raw."""

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

with DAG(
    dag_id="gridpulse_backup_nightly",
    schedule="0 2 * * *",
    start_date=pendulum.datetime(2026, 10, 15, tz="Europe/Bucharest"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=15)},
    tags=["gridpulse"],
    doc_md=__doc__,
) as dag:
    backup = BashOperator(task_id="backup", bash_command="gridpulse backup run --keep-days 14")
    alert = BashOperator(
        task_id="alert_on_failure",
        bash_command='gridpulse alert "nightly backup {{ ds }} failed"',
        trigger_rule="one_failed",
    )
    backup >> alert
