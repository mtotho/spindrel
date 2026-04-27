---
name: System Diagnostics
description: Inspect server-side errors and the daily health summary. Use this when investigating why something silently failed, when reading container logs to debug a regression, or when wiring an automation that acts on the daily error rollup.
triggers: server logs, container logs, docker logs, server errors, daily summary, health summary, postgres errors, traceback, ERROR CRITICAL FATAL, why is X failing, what broke overnight
category: operations
---

# System Diagnostics

Three tools cover the full picture of what went wrong on the server:

| Tool | What it does | When to reach for it |
|---|---|---|
| `read_container_logs` | Raw recent log lines from one allowlisted container | Targeted debugging; you already know which container |
| `get_recent_server_errors` | Deduped error findings across all sources | Operational sweep; no specific service in mind |
| `get_latest_health_summary` | Persisted daily summary row + attention rollup | Automations; "what was wrong yesterday" |

## Sources

- **`agent-server`** — the FastAPI app's own durable JSONL log file (`/var/log/spindrel/agent-server.log`). Survives container restarts. Faster than `docker logs` against ourselves.
- **`postgres`** + Spindrel-managed Compose stacks — read via `docker logs` against the host daemon.
- The structured `trace_events` and `tool_calls` tables already feed the 60-second `WorkspaceAttentionItem` detector. Those errors *also* appear in the daily summary's `trace_event_count` / `tool_error_count` totals — don't re-grep them yourself.

## Discovery

Pass `container=""` to `read_container_logs` to enumerate the allowlist:

```
read_container_logs(container="")
→ {"allowed": ["agent-server", "postgres-...", "spindrel-..."]}
```

Anything outside the allowlist returns an explicit error rather than a silent miss.

## Common patterns

**"Why did the agent silently fail?"** — start with `get_recent_server_errors(since="2h")`. If a finding's `signature` matches a Loose End or known issue, reach for `read_container_logs(container=<service>, grep=<token>, since="2h")` for the surrounding context.

**"What broke overnight?"** — `get_latest_health_summary()`. The persisted summary gives you signature + service + count + sample without re-paging logs. Cross-reference `attention_item_id` if you need the canvas-side beacon.

**Acting on yesterday's errors** — wire a task pipeline (`channel_pipeline_subscriptions`) keyed on `system_health_summary.generated`-style triggers, or schedule a one-shot pipeline that calls `get_latest_health_summary` and decides what to do. The summary is generated deterministically by Python — no LLM tokens are spent on the routine sweep.

## Boundaries

- These tools are read-only. They do not modify containers, restart services, or rotate logs.
- The `read_container_logs` allowlist exists to keep the host Docker socket from becoming an arbitrary `docker logs` foothold. If a sibling service you care about isn't in the list, surface the gap as a Loose End rather than working around it.
- Tracebacks are normalized via the same `_error_signature` helper the structured-attention detector uses — that's the contract that keeps daily-summary findings dedupe-aligned with the 60s detector.
