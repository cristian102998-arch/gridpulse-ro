"""Guardrails for model-written SQL. Defence in depth, the database is the last line:

1. here: one SELECT statement, only tables in the `marts` schema, no dangerous functions,
   a LIMIT on every query;
2. the connection: a read-only transaction with a statement timeout;
3. the role (`gridpulse_app`): SELECT on marts/ops only, no access to raw.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

ALLOWED_SCHEMAS = {"marts"}
MAX_ROWS = 200
BLOCKED_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "set_config",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "query_to_xml",
    "current_setting",
}


class UnsafeSQL(ValueError):
    """The query was rejected before reaching the database."""


@dataclass(frozen=True)
class CheckedSQL:
    sql: str
    tables: tuple[str, ...]


def check_sql(sql: str, max_rows: int = MAX_ROWS) -> CheckedSQL:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.SqlglotError as e:  # ParseError and TokenError (e.g. a stray quote)
        raise UnsafeSQL(f"could not parse the SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeSQL("send exactly one statement")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeSQL("only SELECT queries are allowed")
    for node in tree.walk():
        if isinstance(node, exp.DML | exp.DDL | exp.Command | exp.Into):
            raise UnsafeSQL("only SELECT queries are allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or "").lower()
        if not schema and name in cte_names:
            continue
        if schema not in ALLOWED_SCHEMAS:
            raise UnsafeSQL(
                f"table {table.sql()} is not allowed; use the marts schema, e.g. marts.{name}"
            )
        tables.append(f"{schema}.{name}")

    for func in tree.find_all(exp.Func):
        fname = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).lower()
        if fname in BLOCKED_FUNCTIONS:
            raise UnsafeSQL(f"function {fname} is not allowed")

    limit = tree.args.get("limit")
    current = None
    if isinstance(limit, exp.Limit) and isinstance(limit.expression, exp.Literal):
        current = int(limit.expression.this)
    if current is None or current > max_rows:
        tree = tree.limit(max_rows)
    return CheckedSQL(tree.sql(dialect="postgres"), tuple(sorted(set(tables))))
