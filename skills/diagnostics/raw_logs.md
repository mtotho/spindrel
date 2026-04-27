---
name: Diagnostics — Raw Logs
description: L5 last-resort tier. Read raw stderr/stdout from an allowlisted Spindrel-server container. Only useful AFTER a higher tier (Health Summary, Recent Errors, Traces) gave you a service name AND a signature substring. Without both, this tool will dump hundreds of unrelated lines.
triggers: read_container_logs, raw logs, container logs, docker logs, agent-server logs, postgres logs, surrounding lines, log context, grep logs, allowlisted containers, jsonl log
category: operations
---

# Raw Logs (L5)

The most expensive tier. Reach for this **only** after a higher tier produced
both:

- **a service name** (you know which container to read)
- **a signature substring** (you know what to grep for)

Without both, you'll page through hundreds of unrelated lines and waste
context. If you don't have them, go back to [Health
Summary](health_summary.md), [Recent Errors](recent_errors.md), or
[Traces](traces.md) first.

## When to fetch this skill

- A higher tier gave you a finding/event whose context isn't enough — you
  need the surrounding 5-50 lines to understand what state the system was
  in when it failed.
- A sibling container is misbehaving in ways that don't show up in
  `agent-server`'s structured logs.
- You're confirming a fix shipped (the error stopped appearing in raw logs
  after deploy).

## `read_container_logs`

```
read_container_logs(container="")                                # discover allowlist
read_container_logs(container="agent-server", since="2h", tail=500)
read_container_logs(container="agent-server", since="2h", grep="<signature substring>")
read_container_logs(container="postgres-spindrel", since="30m", tail=2000, grep="ERROR")
```

**Parameters:**
- `container` — allowlisted container name. Empty string returns the
  allowlist (always do this first if you don't know the names).
- `since` — `15m`, `1h`, `24h`. Default `1h`.
- `tail` — max lines (capped at 5000, default 500).
- `grep` — case-insensitive substring filter applied to each line. **Always
  pass this** unless you already narrowed `since` aggressively.

**Returns:** `{container, allowed, lines, truncated, error?}`. The `allowed`
list comes back on every call so you can see the allowlist without re-asking.

## `agent-server` is special

The `agent-server` source reads from the durable JSONL log file at
`/var/log/spindrel/agent-server.log` — **not** `docker logs`. This means:

- It survives container restarts.
- Each line is structured (`ts level [logger] message` plus optional
  `exc_info`) — easier to read than raw `docker logs`.
- Faster than `docker logs` against the FastAPI app itself.

For all other allowlisted containers, this tool shells `docker logs` against
the host daemon.

## How to use grep well

`get_recent_server_errors` and `get_trace` give you `signature` /
`event_type` / error-message tokens. Use those as your `grep` argument
verbatim — they're pre-normalized by the same parser, so they'll match.

```
# Found via L2: signature "AttributeError NoneType.scopes"
read_container_logs(container="agent-server", since="6h", grep="AttributeError NoneType.scopes")

# Found via L3: tool_call status "ERROR: connection reset"
read_container_logs(container="agent-server", since="2h", grep="connection reset")
```

Don't grep for noisy generic tokens (`error`, `failed`, `null`) without
narrowing `since` — you'll page noise.

## Boundaries

- **Allowlist** — anything outside it returns an explicit error rather than a
  silent miss. This exists so the host Docker socket doesn't become an
  arbitrary `docker logs` foothold. If a sibling service you care about
  isn't in the list, surface that as a Loose End — don't try to work around
  it.
- **Read-only** — this tool does not restart, rotate, exec into, or mutate
  any container.
- **Truncation** — `truncated: true` in the response means you hit the line
  cap; either narrow `since` / `grep` or raise `tail` (max 5000).
- **Don't replace the higher tiers with this.** Going straight to raw logs
  for "what's wrong?" wastes context on lines a higher tier already deduped
  for free.
