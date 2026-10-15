"""Daily pipeline: ingest -> dbt build -> forecast tomorrow -> freshness.
Calls the same CLI as the GitHub Actions cron.

Runs at 07:30 Bucharest time, when yesterday is complete in Energy-Charts.
The last 3 local days are re-fetched every run, so late revisions are picked up;
the upsert makes this free when nothing changed.
"""

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

DBT = 'cd "$GRIDPULSE_DBT_DIR" && eval "$(gridpulse db env --shell)" && dbt'
YESTERDAY = "{{ macros.ds_add(ds, -1) }}"
TOMORROW = "{{ macros.ds_add(ds, 1) }}"
THREE_DAYS_AGO = "{{ macros.ds_add(ds, -3) }}"

with DAG(
    dag_id="gridpulse_daily",
    schedule="30 7 * * *",
    start_date=pendulum.datetime(2026, 10, 15, tz="Europe/Bucharest"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
    tags=["gridpulse"],
    doc_md=__doc__,
) as dag:
    init = BashOperator(task_id="db_init", bash_command="gridpulse db init")

    ingest_energy_charts = BashOperator(
        task_id="ingest_energy_charts",
        bash_command=(
            "gridpulse ingest energy-charts public-power"
            f" --start {THREE_DAYS_AGO} --end {YESTERDAY}"
        ),
    )

    ingest_open_meteo = BashOperator(
        task_id="ingest_open_meteo",
        bash_command=(
            f"gridpulse ingest open-meteo temperature --start {THREE_DAYS_AGO} --end {TOMORROW}"
        ),
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{DBT} build --profiles-dir .",
        execution_timeout=timedelta(minutes=30),
    )

    forecast = BashOperator(
        task_id="forecast_tomorrow",
        bash_command=f"gridpulse forecast predict --start {TOMORROW}",
        execution_timeout=timedelta(minutes=15),
    )

    dbt_forecast_marts = BashOperator(
        task_id="dbt_forecast_marts",
        bash_command=f"{DBT} build --profiles-dir . --select fct_load_forecast_baseline+",
    )

    freshness = BashOperator(
        task_id="source_freshness",
        bash_command=f"{DBT} source freshness --profiles-dir .",
        retries=0,
    )

    alert_on_failure = BashOperator(
        task_id="alert_on_failure",
        bash_command='gridpulse alert "daily run {{ ds }} failed, see the Airflow logs"',
        trigger_rule="one_failed",
        retries=0,
    )

    init >> [ingest_energy_charts, ingest_open_meteo] >> dbt_build
    dbt_build >> forecast >> dbt_forecast_marts >> freshness
    [
        ingest_energy_charts,
        ingest_open_meteo,
        dbt_build,
        forecast,
        dbt_forecast_marts,
        freshness,
    ] >> alert_on_failure
