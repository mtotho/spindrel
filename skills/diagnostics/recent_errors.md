---
name: Diagnostics — Recent Errors
description: L2 live error sweep. Deduped findings across all Spindrel-server log sources (FastAPI app durable JSONL + sibling containers) over a configurable window. Use when the user is reporting a problem RIGHT NOW or when the daily health summary is stale.
triggers: recent errors, live errors, what's failing, current errors, error sweep, last hour, last 6 hours, log sweep, get_recent_server_errors, postgres errors, agent-server errors, sibling container errors
category: operations
---

# Recent Errors (L2)

The live, cross-source error sweep. One tool. Use when the daily summary
hasn't caught up yet or the user is reporting a current problem.

## When to fetch this skill

- The user reports a problem **right now** ("the bot just crashed", "I just
  saw an error").
- [Health Summary](health_summary.md) returned `generated_at: null` or stale.
- You need to scope a sweep to a specific service set rather than the whole
  fleet.

## `get_recent_server_errors`

```
get_recent_server_errors(since="2h")
get_recent_server_errors(since="24h", services=["agent-server", "postgres"])
get_recent_server_errors(since="6h", limit=20)
```

**Parameters:**
- `since` — time window. Accepts `30m`, `2h`, `24h`, `7d`. Default `24h`
  (matches the daily summary window).
- `services` — optional subset of allowlisted source names (call
  `read_container_logs(container="")` once if you don't know the allowlist).
  Default = all.
- `limit` — max findings (default 50, max 500).

**Returns:** `{since, total, findings: [...]}` where each finding is
`{service, severity, signature, dedupe_key, title, sample, first_seen,
last_seen, count, kind}`. Same `LogFinding` shape the daily summary uses.

## How to read the results

**Read findings, don't dump them.** The window may produce dozens of
findings — you want the one or two that matter:

1. Sort by severity: `critical` first, then `error`, then `warning`.
2. Within the same severity, anomalous `count` wins (a finding hit 50 times
   matters more than one hit twice).
3. Note `service` + `signature` for each — both feed the next tier if you
   need raw context.

**Dedupe contract:** the parser normalizes tracebacks via the same
`_error_signature` helper the 60s structured-attention detector uses. So
findings here align with both the canvas attention beacon and with daily
summary findings — don't re-grep them yourself.

## Sources covered

- **`agent-server`** — the FastAPI app's own durable JSONL log file
  (`/var/log/spindrel/agent-server.log`). Survives container restarts.
- **`postgres`** + Spindrel-managed Compose stacks — read via `docker logs`.

The structured `trace_events` and `tool_calls` tables are a **separate
source** — they already feed the daily summary's `trace_event_count` and
`tool_error_count` totals. To investigate those, use [Traces](traces.md), not
this tool.

## When to fall through

| Result | Next step |
|---|---|
| Empty findings, but user insists something broke | [Traces](traces.md) — the failure was structured, not stderr |
| Finding identifies a service + signature, but you need surrounding lines | [Raw Logs](raw_logs.md) with that service + grep token |
| Many findings, none look load-bearing | Widen `since` to `24h` or check [Health Summary](health_summary.md) for the daily rollup view |
| Finding is in `agent-server` and looks like a tool error | [Traces](traces.md) — the tool call has structured data the log line doesn't |

## Boundaries

- The allowlist exists so the host Docker socket isn't an arbitrary
  `docker logs` foothold. If a sibling service you care about isn't in the
  list, surface that gap as a Loose End — don't try to work around it.
- This is a **read-only summary**. It does not restart, rotate, or remediate.
- The `sample` field is one line of context per finding. For the surrounding
  log lines, fall through to [Raw Logs](raw_logs.md) with a grep token.
