---
name: Diagnostics — Traces
description: L3-L4 structured-trace inspection. Drill into one failing turn (`list_session_traces` → `get_trace`) or audit a TraceEvent pattern across many turns. Covers ranker, discovery, retrieval, llm_error, model_fallback, compaction, tool-call failure.
triggers: trace, traces, get_trace, list_session_traces, correlation id, why did this turn fail, ranker off, discovery weak, tool_retrieval, discovery_summary, llm_error, model_fallback, compaction, subagent, token usage spike, tool returned error, tool error, tool args, get_tool_info, audit pattern, audit ranker, cross-turn audit
category: operations
---

# Traces (L3 + L4)

The structured-trace tier. Every turn in Spindrel emits a stream of
`TraceEvent` rows and `ToolCall` rows keyed by a `correlation_id`. Two
top-level intents:

- **L3 — drill-down**: "this one turn failed, why?" → `list_session_traces`,
  then `get_trace(correlation_id=...)` in **summary → phase** order.
- **L4 — pattern audit**: "ranker has been flaky for days" → `get_trace`
  in **list mode** by `event_type`, optionally filtered by `bot_id`.

Both flows live in the same tool (`get_trace`) — the parameter shape decides
which mode you're in.

## `list_session_traces` — find the failing turn (L3 entry)

Scoped to the **current channel**. Returns recent turns with error counts and
user-message previews.

```
list_session_traces(limit=10)
```

Returns `{count, traces: [{correlation_id, started_at, tool_count,
event_count, error_count, user_message_preview}, ...]}`.

Pick the entry whose `error_count > 0` and whose `user_message_preview`
matches the user's complaint. Note the `correlation_id`.

## `get_trace` detail mode — inspect one turn

Walk **summary → phase**. Never jump to `mode="full"` until you've confirmed
it's small.

### Step 1: summary

```
get_trace(correlation_id="<uuid>", mode="summary")
```

Returns the **phase index** plus turn metadata (`tool_call_count`,
`event_count`, `error_count`). The phase index is the cheap navigation map —
each entry is `{name, kind, item_count, first_at, last_at}`.

### Phase-name reference

The `name` is either `tool_calls` (the bucket of all LLM tool invocations
that turn) or a `TraceEvent.event_type`. Common ones:

| Phase name | What it tells you |
|---|---|
| `tool_calls` | Every tool invocation, with args + result preview. Where you find tools that returned errors. |
| `discovery_summary` | What the discovery layer surfaced this turn. Empty/weak surfacings = ranker problem. |
| `skill_index` | What skill candidates were considered. |
| `tool_retrieval` | What the tool RAG layer scored and returned. |
| `tool_surface_summary` | Final tool surface presented to the LLM. |
| `token_usage` | Per-iteration token counts. Spike = compaction missed something. |
| `llm_error` | Provider-side failure (rate limit, 5xx, model outage). |
| `model_fallback` | Provider chain dropped to a backup model. |
| `error` / `warning` | Generic structured events emitted by app code. |
| `compaction_start` / `compaction_done` / `compaction_tier` | Compaction pipeline ran — useful when context felt wrong. |
| `subagent_started` / `subagent_finished` | Delegation happened — drill into the child trace separately by its own correlation_id. |
| `context_breakdown` / `context_injection_summary` / `context_pruning` | Context-admission decisions. |
| `tagged_context` / `fs_context` | What ambient context was admitted. |
| `rag_rerank` | RAG reranker output. |
| `tool_result_summarization` | A tool result got summarized for context fit. |
| `task_timeout` | A backgrounded task hit its deadline. |
| `heartbeat_budget_pressure` | The heartbeat planner detected token pressure. |
| `response` | Final response text emitted. |
| `exec` | Shell-style execution event. |

### Step 2: drill into one phase

```
get_trace(correlation_id="<uuid>", mode="phase", phase="error", limit=50)
get_trace(correlation_id="<uuid>", mode="phase", phase="tool_calls", cursor=50, limit=50)
```

**Page** with `cursor` / `next_cursor`. Default page size 50, max 200.

For `tool_calls` items, look at `status` — `"ok"` or `"ERROR: <message>"` —
and `args` / `result_preview`. Long args/results are auto-truncated to 2000
chars with a `_truncated` marker.

### Step 3 (only if necessary): full mode

```
get_trace(correlation_id="<uuid>", mode="full")
```

Returns the entire merged timeline. Use only when `event_count +
tool_call_count` from the summary is small. Most turns have 30–500 items —
`full` blows context. Prefer paginated phase reads.

## `get_trace` list mode — cross-turn audit (L4)

When the symptom isn't bound to one turn ("ranker has been flaky all day",
"are we hitting `llm_error` more than usual this week?"), use list mode by
passing `event_type`:

```
get_trace(event_type="error", limit=50)
get_trace(event_type="llm_error", bot_id="crumb", limit=20)
get_trace(event_type="tool_retrieval", include_user_message=true, limit=30)
```

Returns recent `TraceEvent` rows with `correlation_id` per row — pivot back
into detail mode for any interesting one.

**`include_user_message=true`** is the right flag whenever you're auditing a
ranker / discovery / retrieval event. The user's intent is what tells you
whether the surfacing was reasonable; the trace payload alone often doesn't
capture it.

## `get_tool_info` — confirm a tool's contract

When a `tool_calls` phase shows what looks like an arg-validation failure,
fetch the tool's input/output schema:

```
get_tool_info(tool_name="search_history")
```

Use the schema to confirm whether the LLM passed bad args (its mistake) vs.
the tool returning a structurally invalid result (server bug). The latter is
worth flagging — the former is fixable with a clearer skill or prompt.

## Diagnostic playbooks

**"Why did the agent silently fail?"**
1. `list_session_traces(limit=10)` — find the turn.
2. `get_trace(correlation_id=..., mode="summary")` — read phase index.
3. If `error_count > 0`: `mode="phase", phase="error"`.
4. Else: `mode="phase", phase="tool_calls"` — look for `status: "ERROR: ..."`.
5. If a tool's args look wrong: `get_tool_info(tool_name=...)` to confirm.

**"The ranker is off / discovery feels weak"**
1. `get_trace(event_type="discovery_summary", include_user_message=true, limit=30)` — see what surfaced for what intent.
2. `get_trace(event_type="tool_retrieval", include_user_message=true, limit=30)` — same for the retrieval layer.
3. Filter to one bot if relevant: add `bot_id="..."`.
4. Hand the pattern to the `orchestrator.analyze_discovery` audit pipeline (see [orchestrator/audits](../orchestrator/audits.md)).

**"Tool X returned an error"**
1. Find the turn via `list_session_traces`.
2. `get_trace(..., mode="phase", phase="tool_calls")` — find the failing call.
3. `get_tool_info(tool_name="X")` — confirm input schema.
4. If the error is server-side, not arg-side: fall to
   [Recent Errors](recent_errors.md) with `services=["agent-server"]`.

## Boundaries

- `list_session_traces` is **scoped to the current channel**. To diagnose a
  bot's behavior in another channel, use list-mode `get_trace` with `bot_id`.
- `get_trace` reads from the `trace_events` and `tool_calls` tables. If those
  tables are empty for a turn (e.g. very old, retention-dropped), there's
  nothing to inspect — fall to [Raw Logs](raw_logs.md) for the same window.
- The `data` field on `TraceEvent` rows is auto-truncated at 2000 chars in
  detail mode. List mode returns the full payload — use it when the
  truncated marker bit you in detail mode.
