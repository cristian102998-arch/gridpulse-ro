"""The "ask the data" agent: a tool loop with Haiku first and Sonnet when Haiku's SQL fails."""

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gridpulse.agent.providers import (
    AzureOpenAIConversation,
    ClaudeConversation,
    Conversation,
    Usage,
)
from gridpulse.agent.tools import TOOL_SPECS, ToolRunner

log = logging.getLogger(__name__)

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
MAX_TURNS = 8
MAX_SQL_ERRORS = 2

SYSTEM_PROMPT = """You answer questions about Romania's power system using a PostgreSQL \
warehouse: hourly consumption (load), generation by source, day-ahead prices, temperature, \
load forecasts and a daily summary table.

How to work:
- Call get_schema once, then answer with as few run_sql calls as you need. Aggregate in SQL; \
do not ask for raw rows and add them up yourself.
- Dates and hours in questions are local Romanian time unless the user says UTC. Use local_day \
and hour_local for filtering and grouping.
- For why/what-happened questions, or when numbers need context, use search_documents (when \
available) and cite each passage you rely on as (document title, year, p. N). Documents give \
context; numbers about load, generation and prices come from SQL.
- If a table has no rows for what was asked (for example prices before the ENTSO-E feed is \
connected), say the data is not available yet instead of guessing.

How to answer:
- Start with the number the user asked for, with its unit (MWh, GWh, MW, EUR/MWh, %, °C). \
Round sensibly: GWh to one decimal, MW and MWh to whole numbers, percentages to one decimal.
- Then one or two short sentences of context if useful. No preamble.
- Answer in the language of the question (Romanian or English).
- Never invent numbers that did not come from a query result."""


@dataclass
class AgentResult:
    answer: str
    model: str  # the model that produced the final answer
    escalated: bool
    sql: list[dict]
    usage: Usage
    seconds: float
    attempts: list[dict] = field(default_factory=list)
    ok: bool = True
    documents: list[dict] = field(default_factory=list)


class _Failed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _run_conversation(conv: Conversation, question: str, tools: ToolRunner, usage: Usage) -> str:
    """Run one model to a final answer, or raise _Failed."""
    sql_errors = 0
    turn = conv.send_user(question)
    for _ in range(MAX_TURNS):
        usage.add(turn.usage)
        if turn.stop_reason == "refusal":
            raise _Failed("refusal")
        if turn.stop_reason == "max_tokens":
            raise _Failed("max_tokens")
        if not turn.tool_calls:
            if not turn.text.strip():
                raise _Failed("empty answer")
            return turn.text.strip()
        results = []
        for call in turn.tool_calls:
            content, is_error = tools.run(call.name, call.args)
            if is_error and call.name == "run_sql":
                sql_errors += 1
            results.append((call.id, content, is_error))
        if sql_errors > MAX_SQL_ERRORS:
            raise _Failed(f"{sql_errors} failed SQL queries")
        turn = conv.send_tool_results(results)
    raise _Failed(f"no answer after {MAX_TURNS} turns")


def make_conversation(model: str, tool_specs: list[dict] = TOOL_SPECS) -> Conversation:
    if model.startswith("azure:"):
        return AzureOpenAIConversation(model.removeprefix("azure:"), SYSTEM_PROMPT, tool_specs)
    return ClaudeConversation(model, SYSTEM_PROMPT, tool_specs)


def ask(
    question: str,
    database_url: str | None = None,
    model: str = HAIKU,
    escalate_to: str | None = SONNET,
    conversation_factory: Callable[..., Conversation] = make_conversation,
) -> AgentResult:
    """Answer one question. Escalates once, with a fresh conversation, if the first model fails."""
    database_url = database_url or os.environ.get(
        "AGENT_DATABASE_URL", os.environ.get("DATABASE_URL", "")
    )
    tools = ToolRunner(database_url)
    specs = tools.tool_specs() if hasattr(tools, "tool_specs") else TOOL_SPECS
    usage = Usage()
    start = time.monotonic()
    attempts = []
    for i, m in enumerate([model, escalate_to] if escalate_to else [model]):
        try:
            conv = (
                conversation_factory(m, specs)
                if conversation_factory is make_conversation
                else conversation_factory(m)
            )
            answer = _run_conversation(conv, question, tools, usage)
            attempts.append({"model": m, "ok": True})
            return AgentResult(
                answer, m, i > 0, tools.sql_log, usage, time.monotonic() - start, attempts
            )
        except _Failed as e:
            log.warning("%s failed: %s", m, e.reason)
            attempts.append({"model": m, "ok": False, "reason": e.reason})
    return AgentResult(
        "Sorry, I could not answer that from the data. Try rephrasing, or ask about a "
        "specific day or month.",
        attempts[-1]["model"],
        len(attempts) > 1,
        tools.sql_log,
        usage,
        time.monotonic() - start,
        attempts,
        ok=False,
    )
