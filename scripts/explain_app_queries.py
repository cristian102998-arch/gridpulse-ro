"""Measure the queries the Streamlit app runs, with EXPLAIN (ANALYZE, BUFFERS).

For each query: the scan used on the main table, the median execution time over several runs
(the first run warms the cache and is not counted) and the 8 kB pages it touched.

    uv run python scripts/explain_app_queries.py            # DATABASE_URL, local by default
    uv run python scripts/explain_app_queries.py --runs 15 --plan

Read-only: EXPLAIN ANALYZE does run each query, but these are all SELECTs.
"""

import argparse
import statistics
from datetime import date, timedelta

import psycopg

from gridpulse.config import get_settings

# The same SQL as app/data.py, with the date windows the views open on by default.
QUERIES = {
    "latest_day (every page)": (
        """
        select max(local_day) as d from marts.fct_generation_hourly
        where local_day < (now() at time zone 'Europe/Bucharest')::date
        """,
        lambda last: {},
    ),
    "generation_hourly (Mix page, 7 days)": (
        """
        select f.hour_local, s.source_label, s.is_renewable, s.display_order,
               f.generation_mwh::float as mwh
        from marts.fct_generation_hourly as f
        join marts.dim_source as s using (source_code)
        where f.local_day between %(start)s and %(end)s
        order by f.hour_utc, s.display_order
        """,
        lambda last: {"start": last - timedelta(days=6), "end": last},
    ),
    "load_vs_forecasts (Forecast page, 8 days)": (
        """
        select hour_local, load_actual_mwh::float as actual,
               forecast_naive_168h_mwh::float as naive_168h, forecast_tso_mwh::float as tso,
               forecast_lgbm_mwh::float as lgbm
        from marts.fct_load_forecast_baseline
        where local_day between %(start)s and %(end)s
        order by hour_utc
        """,
        lambda last: {"start": last - timedelta(days=5), "end": last + timedelta(days=2)},
    ),
}

SCAN_NODES = {"Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan", "Bitmap Index Scan"}


def _walk(node: dict):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


def _scans(plan: dict) -> list[str]:
    out = []
    for n in _walk(plan):
        if n["Node Type"] in SCAN_NODES and n.get("Relation Name", "").startswith("fct_"):
            what = n["Node Type"]
            if "Index Name" in n:
                what += f" using {n['Index Name']}"
            out.append(f"{what} on {n['Relation Name']}")
        elif n["Node Type"] == "Bitmap Index Scan":
            out.append(f"Bitmap Index Scan using {n['Index Name']}")
    return out


def explain(conn: psycopg.Connection, sql: str, params: dict, runs: int) -> dict:
    times, plan = [], None
    for i in range(runs + 1):
        (result,) = conn.execute(
            "explain (analyze, buffers, format json) " + sql, params
        ).fetchone()
        if i == 0:
            continue  # warm-up
        times.append(result[0]["Execution Time"])
        plan = result[0]["Plan"]
    return {
        "median_ms": statistics.median(times),
        "pages": plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0),
        "rows": plan["Actual Rows"],
        "scans": _scans(plan),
        "plan": plan,
    }


def _print_plan(node: dict, depth: int = 0) -> None:
    label = node["Node Type"]
    if "Relation Name" in node:
        label += f" on {node['Relation Name']}"
    if "Index Name" in node:
        label += f" using {node['Index Name']}"
    extra = node.get("Index Cond") or node.get("Filter") or ""
    print(
        f"{'  ' * depth}-> {label}  rows={node['Actual Rows']}"
        f"  removed_by_filter={node.get('Rows Removed by Filter', 0)}  {extra}"
    )
    for child in node.get("Plans", []):
        _print_plan(child, depth + 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=int, default=9)
    p.add_argument("--plan", action="store_true", help="print the full plan tree")
    args = p.parse_args()

    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        (last,) = conn.execute(
            "select max(local_day) from marts.fct_generation_hourly "
            "where local_day < (now() at time zone 'Europe/Bucharest')::date"
        ).fetchone()
        assert isinstance(last, date)
        (n,) = conn.execute("select count(*) from marts.fct_generation_hourly").fetchone()
        print(f"fct_generation_hourly: {n:,} rows, latest day {last}, {args.runs} timed runs\n")
        for name, (sql, params) in QUERIES.items():
            r = explain(conn, sql, params(last), args.runs)
            print(f"{name}")
            print(f"  median {r['median_ms']:.2f} ms | {r['pages']:,} pages | {r['rows']:,} rows")
            for s in r["scans"]:
                print(f"  {s}")
            if args.plan:
                _print_plan(r["plan"], 1)
            print()


if __name__ == "__main__":
    main()
