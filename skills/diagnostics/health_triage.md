---
name: Diagnostics - Health Triage
description: Promote and close live health findings through System Health and Attention APIs. Use after Recent Errors identifies review-worthy failures and the user wants triage, not just observation.
triggers: health triage, promote errors, close health errors, mark errors resolved, attention health, triage recent errors, daily health follow-up, resolve benign errors, current health queue
category: operations
---

# Health Triage

Use this when the user wants an agent to act on live server-health findings:
review current errors, keep likely code bugs visible, and close only findings
that are clearly benign, duplicate, external, stale, or already recovered.

## Start read-only

1. Call `get_latest_health_summary(include_findings=true, max_findings=20)`.
2. If the summary is stale, empty, or the user asks what is happening now, call
   `get_recent_server_errors(since="2h", limit=20)` or widen to `24h`.
3. Summarize by `severity`, `service`, `signature`, `count`, and `last_seen`.
   Do not paste raw logs unless the user needs surrounding context.

## Promote findings for durable review

Use `call_api` when findings should become shared work:

```
POST /api/v1/system-health/recent-errors/promote
{
  "since": "24h",
  "limit": 20,
  "min_severity": "error"
}
```

The API creates or reuses `WorkspaceAttentionItem` rows keyed by each finding's
`dedupe_key`. Default promotion includes `error` and `critical`, not warnings.
Use `dedupe_keys` when you only want specific findings. Promotion skips findings
already reviewed as `resolved_duplicate` unless you explicitly pass that
`dedupe_key` or set `include_resolved=true`.

## Resolve only with evidence

Before resolving, re-check the finding through:

```
GET /api/v1/system-health/recent-errors?since=2h&limit=20&include_attention=true
```

Resolve an Attention item only when the classification is clear:

```
POST /api/v1/workspace/attention/{id}/resolve
{
  "resolution": "duplicate",
  "duplicate_of": "open-root-attention-item-id",
  "note": "Covered by the root finding; keeping that item open."
}
```

Allowed resolution values are `fixed`, `benign`, `duplicate`,
`not_reproducible`, `external`, `stale`, `already_recovered`, and `other`.
Always include a short note for health findings.

`recent-errors?include_attention=true` returns both the raw log finding and the
review overlay. `review_state=resolved_duplicate` still means the log happened
recently; it does not mean the event vanished. Treat it as already-triaged work
unless the duplicate target is missing or the user asks to re-open it.

## Keep likely bugs open

If a finding points to Spindrel code, failed schema handling, repeated tool
contract failure, migration trouble, auth/permission logic, or a fresh
traceback, leave the Attention item open. Report:

- finding `dedupe_key`
- service and signature
- why it looks like a code bug
- likely file or subsystem if known
- the smallest next verification step

Unknown is not benign. Do not resolve findings just to quiet the queue.

## Runtime boundary

This is a Spindrel runtime skill for in-app agents. It assumes the agent has
runtime tools such as `get_latest_health_summary`, `get_recent_server_errors`,
and `call_api`; it does not assume access to the Git repo or `.agents/skills`.
