# 0007 – Guardrails for model-written SQL: three independent layers

**Status:** accepted, 2026-10-15

**Context.** Anyone on the internet can type a question, and the model writes the SQL. Prompt instructions are not a security boundary.

**Decision.** Three layers, each enough on its own for the worst cases:
1. `sql_guard` parses the query with sqlglot: exactly one SELECT, only tables in `marts`, no dangerous functions (`pg_sleep`, `pg_read_file`, `set_config`, ...), and a `LIMIT 200` added or capped.
2. The connection runs every transaction `READ ONLY` with a 10-second statement timeout.
3. The role `gridpulse_app` can only read `marts` and `ops`, and insert into the chat log. It cannot see `raw`.

**Consequences.** Some legitimate queries are refused (for example on `raw`); the error message tells the model how to fix them. 23 tests cover rejected statements.
