# 0006 – Claude Haiku 5.5 by default, Sonnet 5.5 when Haiku fails

**Status:** accepted, 2026-10-15, to be confirmed by the eval

**Context.** The public chat must stay cheap, and the answers must be right. Haiku 5.5 costs $0.10 / $0.50 per million tokens, Sonnet 5.5 $2 / $10: about 0.2 cents against 3.4 cents per question.

**Decision.** The agent runs on Haiku. It escalates once, in a fresh conversation, to Sonnet when Haiku's SQL fails more than twice, when it refuses, or when it gives no answer. Sonnet requests use the server-side refusal fallback; Haiku has none, so refusals are handled in code. Azure OpenAI sits behind the same interface as a third provider for comparison. The choice is checked with `gridpulse agent eval` on the same 25 questions for each model (accuracy, cost, latency).

**Consequences.** Cost per question is logged, and capped by a daily global limit and a per-visitor hourly limit stored in `ops.agent_log`. If the eval shows Haiku is wrong too often, the default changes; that is a one-line config change.
