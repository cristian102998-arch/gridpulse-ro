"""The agent's two tools. Both run on the read-only role, inside a read-only transaction."""

import json
import logging
from datetime import date, datetime
from decimal import Decimal

import psycopg

from gridpulse.agent.sql_guard import UnsafeSQL, check_sql

log = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 10_000
MAX_RESULT_CHARS = 12_000

TOOL_SPECS = [
    {
        "name": "get_schema",
        "description": (
            "List the tables in the `marts` schema with their columns, types and descriptions. "
            "Call it first, once per conversation, before writing SQL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one read-only PostgreSQL SELECT against the `marts` schema and get the rows "
            "back as JSON. Always schema-qualify tables (marts.table). Times are in "
            "timestamptz (UTC) and hour_local (Europe/Bucharest). At most 200 rows are returned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT statement."},
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]

SEARCH_DOCUMENTS_SPEC = {
    "name": "search_documents",
    "description": (
        "Search public reports from Transelectrica (the Romanian TSO) and ANRE (the regulator) "
        "for context the numbers cannot give: explanations, events, outages, investments, "
        "regulation. Returns the most relevant passages with document title, year and page. "
        "Query in Romanian or English."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to look for."}},
        "required": ["query"],
        "additionalProperties": False,
    },
}

SCHEMA_SQL = """
select c.table_name, c.column_name, c.data_type,
       col_description(format('%I.%I', c.table_schema, c.table_name)::regclass,
                       c.ordinal_position) as column_comment,
       obj_description(format('%I.%I', c.table_schema, c.table_name)::regclass)
           as table_comment
from information_schema.columns as c
where c.table_schema = 'marts'
order by c.table_name, c.ordinal_position
"""


def _json_default(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    return str(v)


class ToolRunner:
    """Executes tool calls. Keeps a log of every SQL run, for the UI and the eval."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.sql_log: list[dict] = []
        self.doc_log: list[dict] = []
        self._schema_cache: str | None = None

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (content, is_error)."""
        try:
            if name == "get_schema":
                return self.get_schema(), False
            if name == "run_sql":
                return self.run_sql(args.get("sql", "")), False
            if name == "search_documents":
                return self.search_documents(args.get("query", "")), False
            return f"unknown tool {name}", True
        except UnsafeSQL as e:
            self.sql_log.append({"sql": args.get("sql"), "error": str(e), "rejected": True})
            return f"Rejected before running: {e}", True
        except psycopg.Error as e:
            msg = str(e).strip().splitlines()[0]
            self.sql_log.append({"sql": args.get("sql"), "error": msg, "rejected": False})
            return f"Database error: {msg}", True

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.database_url, connect_timeout=15)
        conn.read_only = True  # every transaction on this connection is READ ONLY
        conn.execute(f"set statement_timeout = {STATEMENT_TIMEOUT_MS}")
        return conn

    def get_schema(self) -> str:
        if self._schema_cache is None:
            with self._connect() as conn:
                rows = conn.execute(SCHEMA_SQL).fetchall()
            tables: dict[str, dict] = {}
            for table, column, dtype, col_comment, table_comment in rows:
                t = tables.setdefault(table, {"description": table_comment, "columns": []})
                c = f"{column} ({dtype})"
                t["columns"].append(f"{c}: {col_comment}" if col_comment else c)
            self._schema_cache = json.dumps(tables, indent=1)
        return self._schema_cache

    def run_sql(self, sql: str) -> str:
        checked = check_sql(sql)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(checked.sql)
            cols = [c.name for c in cur.description]
            rows = cur.fetchall()
        self.sql_log.append({"sql": checked.sql, "rows": len(rows), "error": None})
        body = json.dumps(
            {"columns": cols, "rows": [list(r) for r in rows], "row_count": len(rows)},
            default=_json_default,
        )
        if len(body) > MAX_RESULT_CHARS:
            body = body[:MAX_RESULT_CHARS] + '... (truncated: aggregate in SQL instead)"'
        return body

    def has_documents(self) -> bool:
        """True when the rag schema exists and holds chunks (pgvector deployments only)."""
        try:
            with self._connect() as conn:
                if conn.execute("select to_regclass('rag.chunks')").fetchone()[0] is None:
                    return False
                return conn.execute("select exists (select 1 from rag.chunks)").fetchone()[0]
        except psycopg.Error:
            return False

    def tool_specs(self) -> list[dict]:
        return TOOL_SPECS + ([SEARCH_DOCUMENTS_SPEC] if self.has_documents() else [])

    def search_documents(self, query: str) -> str:
        from gridpulse import rag

        with self._connect() as conn:
            hits = rag.search(conn, query[:500], k=5)
        self.doc_log.append({"query": query, "hits": [(h.doc_id, h.page) for h in hits]})
        return json.dumps(
            [
                {
                    "title": h.title,
                    "year": h.year,
                    "page": h.page,
                    "url": h.url,
                    "score": round(h.score, 3),
                    "text": h.text,
                }
                for h in hits
            ],
            ensure_ascii=False,
        )
