import pytest

from gridpulse.agent.sql_guard import UnsafeSQL, check_sql


def test_plain_select_gets_a_limit():
    out = check_sql("select local_day, load_mwh from marts.mart_daily_kpis")
    assert out.sql.endswith("LIMIT 200")
    assert out.tables == ("marts.mart_daily_kpis",)


def test_small_limit_is_kept_large_one_is_capped():
    assert check_sql("select * from marts.dim_date limit 5").sql.endswith("LIMIT 5")
    assert check_sql("select * from marts.dim_date limit 100000").sql.endswith("LIMIT 200")


def test_cte_and_join_are_fine():
    sql = """
        with peak as (select local_day, max(load_actual_mwh) m from marts.fct_load_hourly
                      group by local_day)
        select p.local_day, p.m, d.is_holiday from peak p join marts.dim_date d
          on d.date_day = p.local_day
    """
    out = check_sql(sql)
    assert out.tables == ("marts.dim_date", "marts.fct_load_hourly")


@pytest.mark.parametrize(
    "sql",
    [
        "delete from marts.dim_date",
        "update marts.dim_date set is_holiday = true",
        "insert into marts.dim_date (date_day) values ('2030-01-01')",
        "drop table marts.dim_date",
        "create table marts.x as select 1",
        "select * into marts.copy from marts.dim_date",
        "select 1; select 2",
        "copy marts.dim_date to '/tmp/x'",
        "grant select on marts.dim_date to public",
    ],
)
def test_anything_but_select_is_rejected(sql):
    with pytest.raises(UnsafeSQL):
        check_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "select * from raw.energy_charts_public_power",
        "select * from ops.pipeline_runs",
        "select * from pg_catalog.pg_roles",
        "select * from information_schema.tables",
        "select * from dim_date",  # no schema: could resolve anywhere on the search_path
        "select * from marts.dim_date where date_day in (select day from raw.entsoe_documents)",
    ],
)
def test_only_marts_tables(sql):
    with pytest.raises(UnsafeSQL, match="not allowed"):
        check_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "select pg_sleep(30)",
        "select pg_read_file('/etc/passwd')",
        "select current_setting('data_directory')",
        "select set_config('statement_timeout', '0', false)",
    ],
)
def test_dangerous_functions_are_blocked(sql):
    with pytest.raises(UnsafeSQL, match="function"):
        check_sql(sql)


def test_garbage_is_rejected():
    with pytest.raises(UnsafeSQL):
        check_sql("selec * frm")


def test_untokenizable_sql_is_rejected_not_raised():
    with pytest.raises(UnsafeSQL):
        check_sql("select 'unterminated from marts.dim_source")
