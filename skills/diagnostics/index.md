---
name: Diagnostics
description: Entry point for investigating server-side failure on a Spindrel instance — silent tool errors, unhandled tracebacks, container crashes, ranker misfires. Routes to the right sub-skill by symptom and walks the cost-gradient (cheap rollup first, raw logs last). Also covers the recurring heartbeat / nightly digest pattern.
triggers: diagnose, troubleshoot, investigate failure, why did this fail, what broke overnight, server errors, server logs, container logs, system health, daily summary, traceback, ERROR CRITICAL FATAL, trace, correlation id, ranker off, discovery weak, llm_error, model_fallback, tool returned error, postgres errors, heartbeat report, nightly report, system diagnostics
category: core
---

# Diagnostics

Use this family when something on the **server** failed and you need to find
out what — silent tool errors, unhandled tracebacks, container crashes,
discovery layer misfires, anything that ended up in a log or a trace event but
never surfaced cleanly to the user.

The sub-skills split by **use case**, not by tool, and they're ordered by
**cost**: each tier costs more tokens than the one above it but narrows the
search. Skipping straight to raw container logs is expensive, slow, and usually
fails because you don't yet know which container or signature to grep for.

## Read This First When

- A bot's last reply looked wrong, was empty, or the wrong tool got picked
- Something silently failed and you want to know where the error is
- You need to write or interpret a recurring health digest (heartbeat / nightly)
- You're auditing a discovery / ranker pattern across many turns

## The cost gradient

```
L1  health summary       cheap, persisted     "what was wrong yesterday?"
L2  recent errors        cheap, live          "what's wrong right now?"
L3  trace drill-down     medium               "why did this turn fail?"
L4  trace event search   medium               "which turns hit ranker errors?"
L5  raw container logs   expensive, noisy     "give me the surrounding lines"
```

Always start at the highest tier that could plausibly answer the question.

## Which sub-skill next

| Symptom / intent | Sub-skill | Tier |
|---|---|---|
| "What broke overnight?" / acting on a daily rollup | [Health Summary](health_summary.md) | L1 |
| Confirming bots / channels / integrations exist before blaming them | [Health Summary](health_summary.md) | L1 |
| "What's been failing in the last few hours?" — live deduped sweep | [Recent Errors](recent_errors.md) | L2 |
| "The bot didn't do X in this channel" — debug one turn | [Traces](traces.md) | L3 |
| "Ranker / discovery / retrieval is off lately" — audit across turns | [Traces](traces.md) | L4 |
| "I need the raw stderr around event X" — last resort | [Raw Logs](raw_logs.md) | L5 |
| Wiring a heartbeat / nightly health digest into a channel | [Reports](reports.md) | — |

If unsure, fetch [Health Summary](health_summary.md) first — it's the cheapest
shape-of-the-system call and almost always rules out half the search space.

## Routing examples

- "Why did the agent silently fail?" → Traces (find the turn, drill into phases).
- "Postgres looks unhappy" → Recent Errors (`services=["postgres"]`), then Raw
  Logs only if you need the surrounding lines.
- "Schedule a daily digest in #ops" → Reports.
- "Is anything wrong right now?" → Health Summary, then Recent Errors if the
  summary is stale.
- "Tool X returned an error" → Traces + `get_tool_info` to confirm the contract.

## Boundaries

These tools are **read-only**. They do not restart containers, rotate logs,
re-run failed turns, or mutate state. Remediation is a separate decision the
bot should escalate via the configured notification target. Per-channel scoping
matters: `list_session_traces` and `get_last_heartbeat` are bound to the current
channel — to diagnose a bot's behavior in a different channel, use
`get_trace` list mode with `bot_id`.
