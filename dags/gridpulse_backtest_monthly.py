"""Monthly walk-forward backtest: refreshes the MAPE, confidence intervals and DM tests shown on
the Forecast page, with the month that just ended added to the test window."""

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

DBT = 'cd "$GRIDPULSE_DBT_DIR" && eval "$(gridpulse db env --shell)" && dbt'

with DAG(
    dag_id="gridpulse_backtest_monthly",
    schedule="0 10 2 * *",  # the 2nd, so the 1st's data is complete
    start_date=pendulum.datetime(2026, 10, 15, tz="Europe/Bucharest"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=30)},
    tags=["gridpulse"],
    doc_md=__doc__,
) as dag:
    backtest = BashOperator(
        task_id="backtest",
        bash_command="gridpulse forecast backtest --months 12",
        execution_timeout=timedelta(hours=1),
    )
    marts = BashOperator(
        task_id="dbt_forecast_marts",
        bash_command=f"{DBT} build --profiles-dir . --select fct_load_forecast_baseline+",
    )
    alert = BashOperator(
        task_id="alert_on_failure",
        bash_command='gridpulse alert "monthly backtest {{ ds }} failed"',
        trigger_rule="one_failed",
    )
    backtest >> marts
    [backtest, marts] >> alert
