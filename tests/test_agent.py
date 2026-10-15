"""Agent loop and provider adapters, with fake LLM clients (no API calls, no cost)."""

from types import SimpleNamespace as NS

import pytest

from gridpulse.agent import core
from gridpulse.agent.providers import (
    AzureOpenAIConversation,
    ClaudeConversation,
    ToolCall,
    Turn,
    Usage,
)


class FakeTools:
    def __init__(self, database_url, fail_sql=False):
        self.sql_log = []
        self.fail_sql = fail_sql

    def run(self, name, args):
        if name == "get_schema":
            return '{"mart_daily_kpis": {}}', False
        if self.fail_sql:
            self.sql_log.append({"sql": args["sql"], "error": "column does not exist"})
            return "Database error: column does not exist", True
        self.sql_log.append({"sql": args["sql"], "rows": 1, "error": None})
        return '{"columns": ["load_mwh"], "rows": [[146383]], "row_count": 1}', False


class ScriptedConversation:
    """Plays back a fixed list of turns."""

    def __init__(self, model, turns):
        self.model = model
        self.turns = list(turns)

    def send_user(self, text):
        return self.turns.pop(0)

    def send_tool_results(self, results):
        return self.turns.pop(0)


def _turn(text="", calls=(), stop="end", cost=0.001):
    return Turn(text, list(calls), stop, Usage(100, 20, cost_usd=cost), "m")


GOOD = [
    _turn(calls=[ToolCall("t1", "get_schema", {})], stop="tool_use"),
    _turn(calls=[ToolCall("t2", "run_sql", {"sql": "select 1"})], stop="tool_use"),
    _turn("146,383 MWh were consumed on 13 October 2026."),
]
BAD_SQL = [
    _turn(calls=[ToolCall(f"t{i}", "run_sql", {"sql": "select nope"})], stop="tool_use")
    for i in range(5)
]


def _ask(monkeypatch, scripts):
    monkeypatch.setattr(core, "ToolRunner", lambda url: FakeTools(url))
    used = []

    def factory(model):
        used.append(model)
        return ScriptedConversation(model, scripts[model])

    return core.ask(
        "How much was consumed on 13 October?", "postgresql://x", conversation_factory=factory
    ), used


def test_haiku_answers_without_escalation(monkeypatch):
    result, used = _ask(monkeypatch, {core.HAIKU: GOOD})
    assert result.ok and not result.escalated
    assert result.model == core.HAIKU
    assert "146,383" in result.answer
    assert result.usage.input_tokens == 300
    assert used == [core.HAIKU]


def test_escalates_to_sonnet_after_repeated_sql_errors(monkeypatch):
    calls = []

    class SwitchingTools(FakeTools):
        def run(self, name, args):
            calls.append(name)
            self.fail_sql = len(calls) <= 3  # Haiku's three queries fail, Sonnet's work
            return super().run(name, args)

    monkeypatch.setattr(core, "ToolRunner", lambda url: SwitchingTools(url))
    scripts = {core.HAIKU: BAD_SQL, core.SONNET: GOOD}
    result = core.ask(
        "q",
        "postgresql://x",
        conversation_factory=lambda m: ScriptedConversation(m, scripts[m]),
    )
    assert result.ok and result.escalated and result.model == core.SONNET
    assert result.attempts[0] == {
        "model": core.HAIKU,
        "ok": False,
        "reason": "3 failed SQL queries",
    }


def test_refusal_escalates(monkeypatch):
    result, _ = _ask(monkeypatch, {core.HAIKU: [_turn(stop="refusal")], core.SONNET: GOOD})
    assert result.escalated and result.ok


def test_both_fail_gives_a_polite_answer(monkeypatch):
    result, _ = _ask(
        monkeypatch, {core.HAIKU: [_turn(stop="refusal")], core.SONNET: [_turn(stop="refusal")]}
    )
    assert not result.ok
    assert "could not answer" in result.answer
    assert [a["ok"] for a in result.attempts] == [False, False]


# --- provider adapters -------------------------------------------------------------------


def _claude_response(content, stop="end_turn", model="claude-haiku-5-5"):
    return NS(
        content=content,
        stop_reason=stop,
        model=model,
        stop_details=None,
        usage=NS(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=3000,
            cache_creation_input_tokens=0,
        ),
    )


class FakeAnthropic:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.messages = NS(create=self._create)
        self.beta = NS(messages=NS(create=self._create_beta))

    def _create(self, **kw):
        self.calls.append(("messages", kw))
        return self.response

    def _create_beta(self, **kw):
        self.calls.append(("beta", kw))
        return self.response


def test_claude_haiku_request_shape_and_cost():
    client = FakeAnthropic(
        _claude_response(
            [
                NS(type="thinking", thinking=""),
                NS(type="tool_use", id="tu1", name="run_sql", input={"sql": "select 1"}),
            ],
            stop="tool_use",
        )
    )
    conv = ClaudeConversation("claude-haiku-5-5", "sys", core.TOOL_SPECS, client=client)
    turn = conv.send_user("hello")
    kind, kw = client.calls[0]
    assert kind == "messages"
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert all(t["strict"] for t in kw["tools"])
    assert "fallbacks" not in kw  # Haiku 5.5 has no server-side fallback
    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls[0].args == {"sql": "select 1"}
    # (1000 * 0.10 + 200 * 0.50 + 3000 * 0.01) per million tokens
    assert turn.usage.cost_usd == pytest.approx(0.00023)
    # The assistant turn, thinking block included, is kept as-is (append-only history).
    assert conv.messages[-1]["content"][0].type == "thinking"


def test_claude_sonnet_uses_server_side_fallback():
    client = FakeAnthropic(
        _claude_response([NS(type="text", text="ok")], model="claude-sonnet-5-5")
    )
    conv = ClaudeConversation("claude-sonnet-5-5", "sys", core.TOOL_SPECS, client=client)
    turn = conv.send_user("hello")
    kind, kw = client.calls[0]
    assert kind == "beta"
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert turn.text == "ok" and turn.stop_reason == "end"


def test_claude_refusal_is_reported_not_read():
    client = FakeAnthropic(_claude_response([], stop="refusal"))
    conv = ClaudeConversation("claude-haiku-5-5", "sys", core.TOOL_SPECS, client=client)
    assert conv.send_user("x").stop_reason == "refusal"


def test_claude_tool_results_go_back_in_one_message():
    client = FakeAnthropic(_claude_response([NS(type="text", text="done")]))
    conv = ClaudeConversation("claude-haiku-5-5", "sys", core.TOOL_SPECS, client=client)
    conv.messages = [{"role": "user", "content": "q"}]
    conv.send_tool_results([("a", "r1", False), ("b", "boom", True)])
    sent = client.calls[0][1]["messages"][1]
    assert sent["role"] == "user"
    assert [c["tool_use_id"] for c in sent["content"]] == ["a", "b"]
    assert sent["content"][1]["is_error"] is True


def test_azure_openai_adapter():
    tool_call = NS(id="c1", function=NS(name="run_sql", arguments='{"sql": "select 1"}'))
    response = NS(
        model="gpt-x",
        choices=[NS(finish_reason="tool_calls", message=NS(content=None, tool_calls=[tool_call]))],
        usage=NS(
            prompt_tokens=500, completion_tokens=50, prompt_tokens_details=NS(cached_tokens=100)
        ),
    )
    calls = []
    client = NS(chat=NS(completions=NS(create=lambda **kw: calls.append(kw) or response)))
    conv = AzureOpenAIConversation("gpt-deploy", "sys", core.TOOL_SPECS, client=client)
    turn = conv.send_user("q")
    assert calls[0]["model"] == "gpt-deploy"
    assert calls[0]["tools"][1]["function"]["name"] == "run_sql"
    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls[0].args == {"sql": "select 1"}
    assert turn.usage.input_tokens == 400 and turn.usage.cache_read_tokens == 100
    conv.send_tool_results([("c1", "rows", False)])
    assert conv.messages[-2] == {"role": "tool", "tool_call_id": "c1", "content": "rows"}
