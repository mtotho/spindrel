---
name: System Diagnostics
description: Investigate why something on the Spindrel server failed — server errors, container logs, structured traces, daily health rollup. Procedural, cheapest-first walk through the diagnostic tools so a bot can answer "what broke?" without burning context. Suitable for heartbeats and nightly health-report jobs.
triggers: server errors, server logs, container logs, docker logs, daily summary, health summary, postgres errors, traceback, ERROR CRITICAL FATAL, why did this fail, what broke overnight, trace, traces, trace event, correlation id, list_session_traces, get_trace, tool_retrieval error, discovery_summary, ranker, llm_error, model_fallback, why is X failing, system health, diagnose, troubleshoot, investigate failure, nightly report, heartbeat report
category: operations
---

# System Diagnostics

This is the canonical procedure for diagnosing **server-side failure** on a Spindrel
instance — silent tool errors, unhandled tracebacks, container crashes, ranker
misfires, anything that lands in a log or a trace event but never bubbled up to
the user. Read this top-to-bottom **before** reaching for any of the individual
tools — the order is load-bearing.

The mental model: **walk down a cost gradient.** Each tier costs more tokens
than the one above it, but narrows the search. Skipping straight to raw logs is
expensive, slow, and often fails because you don't yet know which container or
signature to grep for.

```
L1  health summary       cheap, persisted     "what was wrong yesterday?"
L2  recent errors        cheap, live          "what's wrong right now?"
L3  trace drill-down     medium               "why did this turn fail?"
L4  trace event search   medium               "which turns hit ranker errors?"
L5  raw container logs   expensive, noisy     "give me the surrounding lines"
```

---

## Tools at a glance

| Tool | Tier | Use when |
|---|---|---|
| `get_latest_health_summary` | L1 | Acting on a daily/overnight rollup; pipelines and heartbeats. Persisted by the server once per day. |
| `get_system_status` | L1 | Need the fleet shape — bots, channels, integrations, providers. Confirms a bot/integration even exists before you blame it. |
| `get_recent_server_errors` | L2 | Live "what's broken in the last N hours" sweep across all log sources. Deduped by signature. |
| `list_session_traces` | L3 | Find a failing turn in the **current channel** — error counts and user-message previews per recent turn. |
| `get_trace` (detail mode) | L3 | Inspect one turn by `correlation_id`. Use `mode="summary"` first (phase index), then `mode="phase"` for the slice you want. |
| `get_trace` (list mode) | L4 | Scan `TraceEvent` rows of one `event_type` (e.g. `tool_retrieval`, `discovery_summary`, `error`, `llm_error`) across recent turns and bots. |
| `get_last_heartbeat` | L3 | Inspect prior heartbeat outcomes for the **current channel** before deciding to post. |
| `get_tool_info` | side | When a trace shows a tool argument-validation failure, fetch the tool's input/output schema to confirm the contract. |
| `read_container_logs` | L5 | Last resort — only after you have a service name **and** a signature/grep token from a higher tier. |

`agent-server` (the FastAPI app) writes a durable JSONL log at
`/var/log/spindrel/agent-server.log`. `read_container_logs(container="agent-server")`
reads that file directly; the other allowlisted sources are read via `docker logs`.
Pass `container=""` to list the allowlist.

---

## The standard procedure

### Step 1 — Get oriented (L1)

If the user's prompt is open-ended ("what broke last night?", "is anything
wrong?"), start here. These two calls together cost ~one round trip and tell you
which subsystem to drill into.

```
get_latest_health_summary(include_findings=true, max_findings=20)
```

Returns persisted counts (`error_count`, `critical_count`, `trace_event_count`,
`tool_error_count`) + top deduped findings + an `attention_item_id` if the
canvas-side beacon fired. **No LLM tokens were spent generating it** — it was
produced deterministically by `app/services/system_health_summary.py` at the
last daily roll.

If `generated_at` is null or stale, the summary hasn't run yet — fall through
to step 2.

```
get_system_status()
```

Cheap fleet snapshot. Use this to disambiguate ("which bot is `crumb`?") and to
confirm the integration the user named is actually configured.

### Step 2 — Live error sweep (L2)

If the user is reporting a problem **right now**, or step 1 was empty/stale:

```
get_recent_server_errors(since="2h")
# or since="24h" for an overnight window — matches the daily summary
```

Returns deduped `LogFinding` rows: `{service, severity, signature, dedupe_key,
title, sample, first_seen, last_seen, count}`. The `signature` is the same
normalized key the 60-second `WorkspaceAttentionItem` detector uses, so a
finding here will tie back to the canvas attention beacon if one fired.

**Read findings, don't dump them.** Pick the one or two whose `severity` is
`critical` or whose `count` is anomalously high. Note their `service` and
`signature` — both feed step 5 if you ever need raw context.

### Step 3 — Per-turn drill-down (L3)

If the user said "the bot didn't do X in this channel" or "that last reply was
wrong":

```
list_session_traces(limit=10)
```

Returns recent turns in the current channel with `error_count`, `tool_count`,
and `user_message_preview`. Pick the failing `correlation_id`.

Then walk **summary → phase**, never jumping to `mode="full"`:

```
get_trace(correlation_id="<uuid>", mode="summary")
→ {phases: [{name, kind, item_count, first_at, last_at}, ...], error_count, ...}
```

The `phases` array is the index. Each `name` is either `tool_calls` (the
bucket of all LLM tool invocations on the turn) or a `TraceEvent.event_type`.
Common phase names you'll see:

| Phase | What it tells you |
|---|---|
| `tool_calls` | Every tool the LLM invoked, with args + result preview. The bucket where you'd find a tool that returned an error. |
| `discovery_summary` | What the discovery layer surfaced this turn. Empty/weak surfacings = ranker problem. |
| `skill_index` / `tool_retrieval` | What the retrieval layer scored. Use to debug "why didn't skill X fire?". |
| `token_usage` | Per-iteration token counts. Spike = compaction missed something. |
| `llm_error` | Provider-side failures (rate limit, 5xx, model outage). |
| `model_fallback` | The provider chain dropped to a backup model. |
| `error` | Generic structured error events emitted by app code. |
| `compaction_start` / `compaction_done` / `compaction_tier` | Compaction pipeline ran — useful when context felt wrong. |
| `subagent_started` / `subagent_finished` | Delegation happened — drill into the child trace separately. |

Now drill into one phase, paginated:

```
get_trace(correlation_id="<uuid>", mode="phase", phase="error", limit=50)
get_trace(correlation_id="<uuid>", mode="phase", phase="tool_calls", cursor=50)
```

Only use `mode="full"` if you genuinely need the merged timeline at once and
you've already confirmed it's small (`event_count + tool_call_count` from the
summary). Most turns have 30–500 items — `full` blows context.

### Step 4 — Cross-turn trace search (L4)

When the symptom isn't bound to one turn ("ranker has been flaky all day",
"are we hitting `llm_error` more often this week?"), use **list mode** of
`get_trace`:

```
get_trace(event_type="error", limit=50)
get_trace(event_type="llm_error", bot_id="crumb", limit=20)
get_trace(event_type="tool_retrieval", include_user_message=true, limit=30)
```

Returns recent `TraceEvent` rows matching that type, with `correlation_id` per
row so you can pivot back into step 3 for any interesting one.

`include_user_message=true` is the right flag whenever you're auditing a
ranker / discovery / retrieval event — the user's intent is what tells you
whether the surfacing was reasonable.

### Step 5 — Raw container logs (L5)

Only reach for this after a higher tier gave you (a) a service name and (b) a
substring to grep for. Without both, you'll page hundreds of unrelated lines.

```
read_container_logs(container="")                          # discover allowlist
read_container_logs(container="agent-server", since="2h", tail=500, grep="<signature substring>")
read_container_logs(container="postgres-...", since="30m", tail=2000, grep="ERROR")
```

For `agent-server` specifically, this reads the durable JSONL log file (not
`docker logs`) — survives container restarts and is faster.

Anything outside the allowlist returns an explicit error. If a sibling service
you care about is missing, surface that as a Loose End — don't try to
work around it.

---

## Diagnostic playbooks

Composed procedures for specific symptoms. Each names the steps in order.

**"Why did the agent silently fail?"**
1. `list_session_traces(limit=10)` — find the turn.
2. `get_trace(correlation_id=..., mode="summary")` — read phase index.
3. If `error_count > 0`: `mode="phase", phase="error"`.
4. Else: `mode="phase", phase="tool_calls"` — look for `status: "ERROR: ..."` rows.
5. If a tool call's args look wrong: `get_tool_info(tool_name=...)` to confirm the contract.

**"What broke overnight?"**
1. `get_latest_health_summary()`.
2. For each finding above noise threshold, note `service` + `signature`.
3. If counts are surprisingly high, cross-check live: `get_recent_server_errors(since="24h")`.
4. Drill into one structured trace with `get_trace(event_type="error", limit=20)`.

**"The ranker is off / discovery feels weak"**
1. `get_trace(event_type="discovery_summary", include_user_message=true, limit=30)` — see what surfaced for what intent.
2. `get_trace(event_type="tool_retrieval", include_user_message=true, limit=30)` — same for the retrieval layer.
3. If a specific bot: add `bot_id="..."`.
4. Hand the pattern to the `orchestrator.analyze_discovery` audit pipeline (see `orchestrator/audits`).

**"Tool X returned an error"**
1. Find the turn via `list_session_traces`.
2. `get_trace(..., mode="phase", phase="tool_calls")` — find the failing call.
3. `get_tool_info(tool_name="X")` — confirm input schema.
4. If the error is server-side, not arg-side: `get_recent_server_errors(since="2h", services=["agent-server"])`.

**"Postgres / a sibling container is unhappy"**
1. `get_recent_server_errors(since="2h", services=["postgres"])` — start deduped.
2. `read_container_logs(container="postgres", since="30m", tail=1000, grep="ERROR")` for raw context.

---

## Heartbeat / nightly report pattern

The summary is the right hook for a recurring report.

**Heartbeat-style** (running on the channel that should receive the digest, with
`post_heartbeat_to_channel` injected):

```python
from spindrel import tools
import json

summary = json.loads(tools.get_latest_health_summary(include_findings=True, max_findings=10))
if summary.get("error_count", 0) == 0 and summary.get("critical_count", 0) == 0:
    # Nothing worth interrupting the channel for.
    print("clean")
else:
    lines = [f"**System health** — window: {summary['period_start']} → {summary['period_end']}"]
    lines.append(f"errors: {summary['error_count']} (critical: {summary['critical_count']}, tool_errors: {summary['tool_error_count']})")
    for f in summary.get("findings", [])[:5]:
        lines.append(f"- `{f['service']}` × {f['count']}: {f['title']}")
    tools.post_heartbeat_to_channel(message="\n".join(lines))
    print("posted")
```

Use `run_script` (see `programmatic_tool_use`) to chain the lookup + decide +
post in one round trip rather than three.

**Pipeline-style** (scheduled, multi-step, cross-channel notifications): wire a
task pipeline that step-1 calls `get_latest_health_summary`, step-2 branches on
counts, step-3 routes to a notification target. See `pipelines/index` for the
authoring contract.

The summary is generated server-side once per day, so a heartbeat firing more
often than that will see the same row repeatedly — gate on `generated_at`
changing, or on `attention_item_id`, to avoid duplicate posts.

---

## Boundaries

- These tools are **read-only**. They do not restart containers, rotate logs,
  re-run failed turns, or mutate state. Remediation is a separate decision the
  bot should escalate via the configured notification target.
- The `read_container_logs` allowlist exists so the host Docker socket isn't an
  arbitrary `docker logs` foothold. New services need the operator to extend
  the allowlist — work around it via `get_recent_server_errors` (which already
  iterates the allowlist) or surface the gap.
- `list_session_traces` and `get_last_heartbeat` are **scoped to the current
  channel**. To diagnose a bot's behavior in a *different* channel, use
  `get_trace` list mode with `bot_id` instead.
- Tracebacks are normalized via the same `_error_signature` helper the 60s
  structured-attention detector uses — that contract is what keeps daily-summary
  signatures aligned with the live attention beacon. Don't roll your own
  dedupe.
- `trace_event_count` and `tool_error_count` in the daily summary already
  include the structured errors that show up in `get_trace(event_type="error")`.
  Don't double-count across sources.
