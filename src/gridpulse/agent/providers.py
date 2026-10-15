"""A thin layer over two LLM APIs, so the agent loop and the eval do not care which one runs.

Claude goes through the Anthropic SDK; Azure OpenAI through the OpenAI SDK. Each conversation
keeps its own message history in its provider's native format and is append-only.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

# USD per million tokens. Claude prices from Anthropic's model table (Haiku 5.5: prompts
# up to 100K tokens, which is always the case here). Azure depends on the deployment, so it is
# configured through the environment.
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cost_usd += other.cost_usd


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str  # end | tool_use | refusal | max_tokens
    usage: Usage
    model: str
    details: dict = field(default_factory=dict)


class Conversation(Protocol):
    model: str

    def send_user(self, text: str) -> Turn: ...

    def send_tool_results(self, results: list[tuple[str, str, bool]]) -> Turn: ...


def _price(model: str, u: Usage) -> float:
    p = PRICES.get(model)
    if p is None:
        p = {
            "input": float(os.environ.get("AZURE_OPENAI_PRICE_INPUT", "0")),
            "output": float(os.environ.get("AZURE_OPENAI_PRICE_OUTPUT", "0")),
            "cache_read": 0.0,
            "cache_write": 0.0,
        }
    return (
        u.input_tokens * p["input"]
        + u.output_tokens * p["output"]
        + u.cache_read_tokens * p["cache_read"]
        + u.cache_write_tokens * p["cache_write"]
    ) / 1_000_000


class ClaudeConversation:
    """Claude Messages API. Haiku 5.5 by default; Sonnet 5.5 for escalations.

    Sonnet requests opt into the server-side refusal fallback (`fallbacks: "default"`).
    Haiku 5.5 has no server-side fallback, so its refusals are returned as stop_reason="refusal"
    and the agent escalates.
    """

    def __init__(
        self, model: str, system: str, tools: list[dict], effort: str = "medium", client=None
    ):
        import anthropic

        self.client = client or anthropic.Anthropic()
        self.model = model
        self.system = system
        self.tools = [{**t, "strict": True} for t in tools]
        self.effort = effort
        self.messages: list = []

    def _call(self) -> Turn:
        kwargs = dict(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
        )
        if self.model.startswith("claude-sonnet-5-5"):
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        else:
            response = self.client.messages.create(**kwargs)

        # Append-only history: the full content (thinking blocks included) goes back as-is.
        self.messages.append({"role": "assistant", "content": response.content})
        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        )
        usage.cost_usd = _price(self.model, usage)
        stop = {"end_turn": "end", "tool_use": "tool_use"}.get(
            response.stop_reason, response.stop_reason
        )
        if response.stop_reason == "refusal":
            return Turn(
                "",
                [],
                "refusal",
                usage,
                response.model,
                {"stop_details": getattr(response, "stop_details", None)},
            )
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"
        ]
        return Turn(text, calls, stop, usage, response.model)

    def send_user(self, text: str) -> Turn:
        self.messages.append({"role": "user", "content": text})
        return self._call()

    def send_tool_results(self, results: list[tuple[str, str, bool]]) -> Turn:
        # All results of one assistant turn go back in a single user message.
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": err}
                    for tid, content, err in results
                ],
            }
        )
        return self._call()


class AzureOpenAIConversation:
    """Azure OpenAI chat completions with function calling. The deployment name is the model."""

    def __init__(self, deployment: str, system: str, tools: list[dict], client=None):
        from openai import AzureOpenAI

        self.client = client or AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
        self.model = deployment
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                    "strict": True,
                },
            }
            for t in tools
        ]
        self.messages: list[dict] = [{"role": "system", "content": system}]

    def _call(self) -> Turn:
        response = self.client.chat.completions.create(
            model=self.model, messages=self.messages, tools=self.tools
        )
        choice = response.choices[0]
        msg = choice.message
        calls = [
            ToolCall(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
            for tc in (msg.tool_calls or [])
        ]
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        self.messages.append(entry)
        cached = 0
        details = getattr(response.usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        usage = Usage(
            input_tokens=response.usage.prompt_tokens - cached,
            output_tokens=response.usage.completion_tokens,
            cache_read_tokens=cached,
        )
        usage.cost_usd = _price(self.model, usage)
        stop = {
            "stop": "end",
            "tool_calls": "tool_use",
            "length": "max_tokens",
            "content_filter": "refusal",
        }.get(choice.finish_reason, choice.finish_reason)
        return Turn(msg.content or "", calls, stop, usage, response.model or self.model)

    def send_user(self, text: str) -> Turn:
        self.messages.append({"role": "user", "content": text})
        return self._call()

    def send_tool_results(self, results: list[tuple[str, str, bool]]) -> Turn:
        for tid, content, err in results:
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tid,
                    "content": f"ERROR: {content}" if err else content,
                }
            )
        return self._call()
